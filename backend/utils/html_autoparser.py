"""
HTML Autoparser: Automatically detect event structure and generate selectors.

This module analyzes HTML pages to:
1. Detect structured data (JSON-LD, microdata)
2. Cluster DOM elements to find event containers
3. Generate CSS selectors for event extraction
4. Detect if dates need detail page fetching
"""
import json
import re
from typing import Dict, List, Optional, Tuple
from collections import Counter
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse


def parse_html_autoparser(url: str, html_text: str, final_url: Optional[str] = None) -> Dict:
    """
    Parse HTML and automatically generate selectors for event extraction.
    
    Args:
        url: Original URL
        html_text: HTML content
        final_url: Final URL after redirects (if different from url)
    
    Returns:
        {
            tier: 'A'|'B'|'C',
            detected_mode: 'jsonld'|'microdata'|'dom_cluster'|'detail_only'|'js_rendered'|'gated_login'|'no_events',
            selectors_json: {...},
            detail_fetch_patch: {...} or None,
            sample_events: [...],
            diagnostics: {...}
        }
    """
    if final_url is None:
        final_url = url
    
    soup = BeautifulSoup(html_text, 'html.parser')
    html_lower = html_text.lower()
    
    diagnostics = {
        'html_length': len(html_text),
        'script_count': len(soup.find_all('script')),
        'link_count': len(soup.find_all('a', href=True))
    }
    
    # Check for JS-rendered patterns
    js_indicators = [
        'enable javascript', 'javascript required', 'please enable javascript',
        'react-root', 'ng-app', 'data-reactroot', '__next', 'vue-app', 'angular'
    ]
    js_detected = [ind for ind in js_indicators if ind in html_lower]
    is_very_short = len(html_text) < 5000
    
    # Check for gated/login - evidence-based (require explicit markers + content check)
    is_gated = False
    is_gated_suspected = False
    
    # Explicit gate markers
    gate_markers = [
        'access denied',
        'authentication required',
        'please log in to continue',
        'subscribe to continue',
        'sign in to view',
        'captcha',
        'please complete the security check'
    ]
    
    # Check for gate markers in first 5000 chars (main content area)
    main_content = html_text[:5000].lower()
    found_markers = [marker for marker in gate_markers if marker in main_content]
    
    # Also check for HTTP status codes in response
    has_http_error = '403' in html_text[:1000] or '401' in html_text[:1000]
    
    # Check if page has meaningful content (not just gate template)
    # Look for common page structure elements
    has_meaningful_content = len(soup.find_all(['article', 'main', 'section', 'div'], class_=True)) > 5 or \
                            len(soup.find_all('a', href=True)) > 10
    
    if found_markers and (has_http_error or not has_meaningful_content):
        is_gated = True
    elif found_markers:
        is_gated_suspected = True  # Has markers but also has content - suspicious
    
    # Save evidence snippet for debugging
    evidence_snippet = html_text[:1500] if is_gated or is_gated_suspected else None
    
    if is_gated:
        return {
            'tier': 'C',
            'detected_mode': 'gated_login',
            'selectors_json': {},
            'detail_fetch_patch': None,
            'sample_events': [],
            'diagnostics': {
                **diagnostics, 
                'gated': True,
                'gate_markers': found_markers,
                'evidence_snippet': evidence_snippet
            }
        }
    
    if is_gated_suspected:
        # Don't block, but flag in diagnostics
        diagnostics['gated_suspected'] = True
        diagnostics['gate_markers'] = found_markers
        diagnostics['evidence_snippet'] = evidence_snippet
    
    # Strategy 1: JSON-LD structured data
    jsonld_events = _extract_jsonld_events(soup, final_url)
    if len(jsonld_events) >= 3:
        selectors = _generate_selectors_from_jsonld(jsonld_events, soup)
        return {
            'tier': 'A',
            'detected_mode': 'jsonld',
            'selectors_json': selectors,
            'detail_fetch_patch': None,
            'sample_events': jsonld_events[:10],
            'diagnostics': {**diagnostics, 'jsonld_events': len(jsonld_events)}
        }
    
    # Strategy 2: Microdata
    microdata_events = _extract_microdata_events(soup, final_url)
    if len(microdata_events) >= 3:
        selectors = _generate_selectors_from_microdata(microdata_events, soup)
        return {
            'tier': 'A' if len(microdata_events) >= 5 else 'B',
            'detected_mode': 'microdata',
            'selectors_json': selectors,
            'detail_fetch_patch': None,
            'sample_events': microdata_events[:10],
            'diagnostics': {**diagnostics, 'microdata_events': len(microdata_events)}
        }
    
    # Strategy 3: DOM clustering
    dom_result = _cluster_dom_events(soup, final_url)
    if dom_result and len(dom_result['sample_events']) >= 3:
        # Check if dates are missing (detail-only mode)
        events_with_dates = sum(1 for e in dom_result['sample_events'] if e.get('date_iso') or e.get('date_text'))
        date_ratio = events_with_dates / len(dom_result['sample_events']) if dom_result['sample_events'] else 0
        
        if date_ratio < 0.3:  # Less than 30% have dates
            # Detail-only mode: events found but dates need detail fetch
            # This is a first-class lane - many sites work this way
            return {
                'tier': 'B',
                'detected_mode': 'detail_only',
                'selectors_json': dom_result['selectors_json'],
                'detail_fetch_patch': {
                    'enabled': True,
                    'date_selector': 'script[type="application/ld+json"], time[datetime], meta[itemprop="startDate"], meta[property*="date"], .date, .event-date, [class*="date"]',
                    'date_attr': 'datetime',
                    'max': 10,
                    'stop_after_first_valid': True,  # Stop after finding first valid date
                    'priority_order': ['jsonld', 'time_datetime', 'meta_itemprop', 'meta_property', 'class_date']
                },
                'sample_events': dom_result['sample_events'],
                'diagnostics': {
                    **diagnostics, 
                    'date_ratio': date_ratio, 
                    'dom_events': len(dom_result['sample_events']),
                    'detail_fetch_required': True
                }
            }
        else:
            # Regular DOM clustering with dates
            return {
                'tier': 'B' if len(dom_result['sample_events']) >= 5 else 'C',
                'detected_mode': 'dom_cluster',
                'selectors_json': dom_result['selectors_json'],
                'detail_fetch_patch': None,
                'sample_events': dom_result['sample_events'],
                'diagnostics': {**diagnostics, 'dom_events': len(dom_result['sample_events'])}
            }
    
    # Strategy 4: JS-rendered suspicion
    if js_detected or is_very_short:
        # Check if page has event keywords but no DOM items
        event_keywords_in_text = sum(1 for kw in ['event', 'webinar', 'conference', 'seminar'] if kw in html_lower)
        if event_keywords_in_text >= 2 and len(soup.find_all('a', href=True)) < 5:
            return {
                'tier': 'C',
                'detected_mode': 'js_rendered',
                'selectors_json': {},
                'detail_fetch_patch': None,
                'sample_events': [],
                'diagnostics': {**diagnostics, 'js_indicators': js_detected, 'event_keywords_but_no_links': True}
            }
    
    # No events found
    return {
        'tier': 'C',
        'detected_mode': 'no_events',
        'selectors_json': {},
        'detail_fetch_patch': None,
        'sample_events': [],
        'diagnostics': diagnostics
    }


def _extract_jsonld_events(soup: BeautifulSoup, base_url: str) -> List[Dict]:
    """Extract events from JSON-LD structured data."""
    events = []
    
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if not isinstance(data, list):
                data = [data]
            
            for item in data:
                if isinstance(item, dict):
                    # Handle @graph
                    if '@graph' in item:
                        item = item['@graph']
                        if not isinstance(item, list):
                            item = [item]
                    
                    for event_item in (item if isinstance(item, list) else [item]):
                        if not isinstance(event_item, dict):
                            continue
                        
                        # Check if it's an Event
                        event_type = event_item.get('@type', '')
                        if isinstance(event_type, list):
                            event_type = ' '.join(event_type)
                        
                        if 'Event' in event_type:
                            event = {
                                'title': event_item.get('name') or event_item.get('headline') or '',
                                'url': event_item.get('url') or '',
                                'date_text': None,
                                'date_iso': event_item.get('startDate') or event_item.get('datePublished') or None
                            }
                            
                            # Build full URL
                            if event['url'] and not event['url'].startswith('http'):
                                event['url'] = urljoin(base_url, event['url'])
                            
                            if event['title']:
                                events.append(event)
        except (json.JSONDecodeError, KeyError, AttributeError):
            continue
    
    return events


def _extract_microdata_events(soup: BeautifulSoup, base_url: str) -> List[Dict]:
    """Extract events from microdata."""
    events = []
    
    for item in soup.find_all(attrs={'itemtype': re.compile(r'.*Event', re.I)}):
        event = {
            'title': '',
            'url': '',
            'date_text': None,
            'date_iso': None
        }
        
        # Extract name
        name_elem = item.find(attrs={'itemprop': 'name'})
        if name_elem:
            event['title'] = name_elem.get_text(strip=True)
        
        # Extract URL
        url_elem = item.find(attrs={'itemprop': 'url'})
        if url_elem:
            href = url_elem.get('href') or (url_elem.get('content') if url_elem.name == 'meta' else None)
            if href:
                event['url'] = urljoin(base_url, href) if not href.startswith('http') else href
        
        # Extract startDate
        date_elem = item.find(attrs={'itemprop': 'startDate'})
        if date_elem:
            event['date_iso'] = date_elem.get('datetime') or date_elem.get('content') or date_elem.get_text(strip=True)
        
        if event['title']:
            events.append(event)
    
    return events


def _cluster_dom_events(soup: BeautifulSoup, base_url: str) -> Optional[Dict]:
    """Cluster DOM elements to find event containers."""
    # Find candidate containers
    event_keywords = ['event', 'webinar', 'conference', 'seminar', 'workshop', 'meeting']
    event_path_hints = ['/event', '/events', '/webinar', '/conference', '/seminar', '/workshop']
    
    # Strategy 1: Look for repeated containers (article, li, div with event classes)
    candidates = []
    
    # Try common container patterns (prioritize article tags)
    container_patterns = [
        ('article', None),  # Highest priority - most semantic
        ('article', 'event'),
        ('div', 'event-card'),
        ('div', 'event-item'),
        ('li', 'event-card'),
        ('li', 'event'),
        ('div', 'event'),
        ('section', 'event'),
        ('div', 'card'),
        ('div', 'item'),
        ('li', None)  # Try any li as fallback
    ]
    
    for tag_name, class_hint in container_patterns:
        if class_hint:
            containers = soup.find_all(tag_name, class_=lambda c: c and (
                any(hint in ' '.join(c).lower() for hint in [class_hint] + event_keywords)
            ))
        else:
            containers = soup.find_all(tag_name)
        
        # For li, also check if parent is a list container
        if tag_name == 'li' and len(containers) >= 3:
            # Check if they're in a list structure
            parent_list = containers[0].parent if containers else None
            if parent_list and parent_list.name in ['ul', 'ol']:
                # Good, they're in a list
                pass
            elif len(containers) < 5:
                # Need more li elements if not in obvious list structure
                continue
        
        if len(containers) < 3:
            continue
        
        # Extract events from containers
        sample_events = []
        for container in containers[:10]:
            # Find link
            link = container.find('a', href=True)
            if not link:
                continue
            
            title = link.get_text(strip=True)
            if len(title) < 12:  # Skip short titles
                continue
            
            href = link.get('href', '')
            if not href:
                continue
            
            # Check if link looks event-like
            href_lower = href.lower()
            is_event_like = any(hint in href_lower for hint in event_path_hints) or \
                          any(kw in title.lower() for kw in event_keywords)
            
            # Filter out obvious nav links
            nav_keywords = ['menu', 'back', 'home', 'about', 'contact', 'news', 'press', 'careers', 'university', 'students', 'programs']
            is_nav_link = any(nav_kw in title.lower() for nav_kw in nav_keywords) or \
                         any(nav_kw in href_lower for nav_kw in ['/menu', '/nav', '/header', '/footer'])
            
            if is_nav_link and not is_event_like:
                continue  # Skip nav links
            
            # If we have time[datetime] elements, be more lenient
            has_time_elem = container.find('time', datetime=True) is not None
            if not is_event_like and len(containers) < 5 and not has_time_elem:
                continue  # Require event hints if few containers and no time elements
            
            full_url = urljoin(base_url, href) if not href.startswith('http') else href
            
            # Find date
            date_text = None
            date_iso = None
            
            # Look for time[datetime] in container
            time_elem = container.find('time', datetime=True)
            if time_elem:
                date_iso = time_elem.get('datetime')
            
            # Look for date-like elements
            if not date_iso:
                date_elems = container.find_all(class_=re.compile(r'date|time', re.I))
                for de in date_elems:
                    text = de.get_text(strip=True)
                    if text and len(text) < 50:
                        date_text = text
                        break
            
            # Also check meta tags
            if not date_iso:
                meta_date = container.find('meta', attrs={'itemprop': 'startDate'})
                if meta_date:
                    date_iso = meta_date.get('content')
            
            sample_events.append({
                'title': title,
                'url': full_url,
                'date_text': date_text,
                'date_iso': date_iso
            })
        
        if len(sample_events) >= 3:
            # Score candidate with strict penalties/boosts
            score = _score_candidate_cluster(containers, sample_events, tag_name, class_hint)
            
            if score > 0:  # Only add if score passes minimum threshold
                # Generate selectors
                first_container = containers[0]
                first_link = first_container.find('a', href=True)
                selectors = _generate_selectors_from_container(first_container, first_link)
                if selectors:
                    # Adjust item selector to match pattern
                    if tag_name == 'article':
                        selectors['item_selector'] = 'article'
                    elif tag_name == 'li':
                        selectors['item_selector'] = 'li' + (f'.{class_hint}' if class_hint else '')
                    else:
                        if class_hint:
                            selectors['item_selector'] = f'{tag_name}.{class_hint}'
                    
                    candidates.append({
                        'score': score,
                        'selectors': selectors,
                        'sample_events': sample_events,
                        'element': first_container
                    })
    
    # Strategy 2: Look for repeated blocks with event-like links (fallback)
    if not candidates:
        links = soup.find_all('a', href=True)
        link_groups = {}
        
        for link in links:
            href = link.get('href', '')
            if not href:
                continue
            
            href_lower = href.lower()
            is_event_link = any(hint in href_lower for hint in event_path_hints)
            if not is_event_link:
                continue
            
            # Find parent container
            parent = link.parent
            depth = 0
            while parent and depth < 5:
                if parent.name in ['article', 'div', 'li', 'section']:
                    parent_id = id(parent)
                    if parent_id not in link_groups:
                        link_groups[parent_id] = {
                            'element': parent,
                            'links': []
                        }
                    link_groups[parent_id]['links'].append(link)
                    break
                parent = parent.parent
                depth += 1
        
        # Score candidates
        for parent_id, group in link_groups.items():
            elem = group['element']
            links_in_group = group['links']
            
            if len(links_in_group) < 2:
                continue
            
            # Extract sample events
            sample_events = []
            for link in links_in_group[:10]:
                title = link.get_text(strip=True)
                if len(title) < 12:
                    continue
                
                href = link.get('href', '')
                full_url = urljoin(base_url, href) if not href.startswith('http') else href
                
                # Find date in container
                date_text = None
                date_iso = None
                
                time_elem = elem.find('time', datetime=True)
                if time_elem:
                    date_iso = time_elem.get('datetime')
                
                if not date_iso:
                    date_elems = elem.find_all(class_=re.compile(r'date|time', re.I))
                    for de in date_elems:
                        text = de.get_text(strip=True)
                        if text and len(text) < 50:
                            date_text = text
                            break
                
                sample_events.append({
                    'title': title,
                    'url': full_url,
                    'date_text': date_text,
                    'date_iso': date_iso
                })
            
            if len(sample_events) >= 3:
                # Score with strict penalties/boosts
                score = _score_candidate_cluster([elem] * len(sample_events), sample_events, elem.name, None)
                
                if score > 0:
                    selectors = _generate_selectors_from_container(elem, links_in_group[0])
                    if selectors:
                        candidates.append({
                            'score': score,
                            'selectors': selectors,
                            'sample_events': sample_events,
                            'element': elem
                        })
    
    if not candidates:
        return None
    
    if not candidates:
        return None
    
    # Return best candidate
    best = max(candidates, key=lambda c: c['score'])
    
    # Self-check: validate event-likeness
    sample_events = best['sample_events']
    event_hints = ['/event', '/events', '/webinar', '/seminar', '/conference', '/register', '/calendar']
    event_like_count = sum(1 for e in sample_events if any(hint in e.get('url', '').lower() for hint in event_hints))
    event_likeness_ratio = event_like_count / len(sample_events) if sample_events else 0
    
    # If < 40% look event-like, mark as needs_refinement
    needs_refinement = event_likeness_ratio < 0.4
    
    result = {
        'selectors_json': best['selectors'],
        'sample_events': sample_events
    }
    
    if needs_refinement:
        result['needs_refinement'] = True
        result['event_likeness_ratio'] = event_likeness_ratio
    
    return result


def _generate_selectors_from_jsonld(events: List[Dict], soup: BeautifulSoup) -> Dict:
    """Generate selectors when JSON-LD is found (fallback to DOM matching)."""
    # Try to match JSON-LD events to DOM elements
    if not events:
        return {}
    
    # Find links that match event URLs
    first_event = events[0]
    if first_event.get('url'):
        matching_link = soup.find('a', href=first_event['url'])
        if matching_link:
            return _generate_selectors_from_container(matching_link.parent, matching_link)
    
    # Fallback: generic article/div selector
    return {
        'item_selector': 'article, .event-item, .event-card',
        'title_selector': 'h2 a, h3 a, a[href*="/event"]',
        'link_selector': 'a[href*="/event"]'
    }


def _generate_selectors_from_microdata(events: List[Dict], soup: BeautifulSoup) -> Dict:
    """Generate selectors from microdata items."""
    # Find first microdata event item
    first_item = soup.find(attrs={'itemtype': re.compile(r'.*Event', re.I)})
    if not first_item:
        return {}
    
    return _generate_selectors_from_container(first_item, first_item.find('a', href=True))


def _score_candidate_cluster(containers, sample_events, tag_name, class_hint) -> int:
    """
    Score a candidate cluster with strict penalties/boosts.
    Returns score (higher is better), or 0 if should be rejected.
    """
    if len(sample_events) < 3:
        return 0
    
    score = len(sample_events) * 10  # Base score
    
    # Extract metrics
    hrefs = [e.get('url', '') for e in sample_events if e.get('url')]
    titles = [e.get('title', '') for e in sample_events if e.get('title')]
    
    # Penalty 1: Unique link ratio (low = many duplicates/nav links)
    unique_hrefs = len(set(hrefs))
    unique_ratio = unique_hrefs / len(hrefs) if hrefs else 0
    if unique_ratio < 0.5:
        return 0  # Hard reject if < 50% unique links
    score += int(unique_ratio * 20)  # Boost for uniqueness
    
    # Penalty 2: Event-link hint ratio
    event_hints = ['/event', '/events', '/webinar', '/seminar', '/conference', '/register', '/calendar']
    event_like_hrefs = sum(1 for h in hrefs if any(hint in h.lower() for hint in event_hints))
    event_hint_ratio = event_like_hrefs / len(hrefs) if hrefs else 0
    if event_hint_ratio < 0.3 and len(containers) < 5:
        return 0  # Hard reject if < 30% event-like and few containers
    score += int(event_hint_ratio * 30)
    
    # Penalty 3: Title entropy (reject if too many repeated/short titles)
    title_lengths = [len(t) for t in titles if t]
    avg_title_length = sum(title_lengths) / len(title_lengths) if title_lengths else 0
    if avg_title_length < 15:
        score -= 20  # Penalty for short titles
    if avg_title_length < 10:
        return 0  # Hard reject if avg < 10
    
    # Check for repeated titles (nav menu pattern)
    title_counts = {}
    for t in titles:
        title_counts[t] = title_counts.get(t, 0) + 1
    max_repeats = max(title_counts.values()) if title_counts else 1
    if max_repeats > len(titles) * 0.5:
        return 0  # Hard reject if > 50% titles are duplicates
    
    # Boost 1: Article tags or headings
    if tag_name == 'article':
        score += 30
    elif any(container.find(['h1', 'h2', 'h3', 'h4', 'h5']) for container in containers[:3]):
        score += 20
    
    # Boost 2: Stable structure (same number of anchors per item)
    anchor_counts = []
    for container in containers[:5]:
        anchors = len(container.find_all('a', href=True))
        anchor_counts.append(anchors)
    if anchor_counts:
        anchor_variance = max(anchor_counts) - min(anchor_counts)
        if anchor_variance <= 2:  # Stable structure
            score += 15
    
    # Boost 3: Dates found
    events_with_dates = sum(1 for e in sample_events if e.get('date_iso') or e.get('date_text'))
    if events_with_dates > 0:
        score += events_with_dates * 5
    
    return score


def _generate_selectors_from_container(container, link_elem) -> Dict:
    """Generate CSS selectors from a container element and link."""
    if not container or not link_elem:
        return {}
    
    selectors = {}
    
    # Item selector: use container's tag + class
    container_tag = container.name
    container_classes = container.get('class', [])
    if container_classes:
        # Prefer event-related classes
        event_classes = [c for c in container_classes if any(kw in c.lower() for kw in ['event', 'card', 'item', 'listing'])]
        if event_classes:
            primary_class = event_classes[0]
            selectors['item_selector'] = f'{container_tag}.{primary_class}'
        else:
            # Use first class
            primary_class = container_classes[0]
            selectors['item_selector'] = f'{container_tag}.{primary_class}'
    else:
        selectors['item_selector'] = container_tag
    
    # Title selector: prefer heading with link (most reliable)
    title_elem = None
    for heading in ['h1', 'h2', 'h3', 'h4', 'h5']:
        heading_elem = container.find(heading)
        if heading_elem:
            link_in_heading = heading_elem.find('a', href=True)
            if link_in_heading:
                selectors['title_selector'] = f'{heading} a'
                selectors['link_selector'] = f'{heading} a'
                title_elem = heading_elem
                break
    
    if not title_elem:
        # Fallback: find best link in container
        # Prefer links with event-like hrefs
        best_link = container.find('a', href=lambda h: h and any(hint in h.lower() for hint in ['/event', '/events', '/webinar', '/conference']))
        if best_link:
            selectors['title_selector'] = 'a[href*="/event"]'
            selectors['link_selector'] = 'a[href*="/event"]'
        else:
            # Last resort: any link
            if link_elem:
                selectors['title_selector'] = 'a[href]'
                selectors['link_selector'] = 'a[href]'
            else:
                selectors['title_selector'] = 'a[href*="/event"]'
                selectors['link_selector'] = 'a[href*="/event"]'
    
    # Date selector: look for time[datetime] or date-like elements
    time_elem = container.find('time', datetime=True)
    if time_elem:
        selectors['date_selector'] = 'time[datetime]'
        selectors['date_attr'] = 'datetime'
    else:
        # Look for date-like classes
        date_classes = [c for c in container.get('class', []) if 'date' in c.lower() or 'time' in c.lower()]
        if date_classes:
            selectors['date_selector'] = f'.{date_classes[0]}'
        else:
            # Generic fallback
            selectors['date_selector'] = '.date, .event-date, time'
    
    return selectors
