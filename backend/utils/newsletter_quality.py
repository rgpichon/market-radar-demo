#!/usr/bin/env python3
"""
Newsletter Quality Scoring Module

Assesses newsletter quality based on macro-signal content and historical yield.
"""
import re
from typing import Dict, List, Optional
from datetime import datetime, timezone


# Macro keywords (positive signals)
MACRO_KEYWORDS = [
    'rates', 'interest rates', 'inflation', 'growth', 'gdp', 'fx', 'forex',
    'currency', 'credit', 'spread', 'yield', 'geopolitics', 'geopolitical',
    'monetary policy', 'fiscal policy', 'central bank', 'fed', 'ecb', 'boj',
    'yield curve', 'sovereign', 'corporate credit', 'equity', 'equities',
    'commodities', 'oil', 'gold', 'dollar', 'euro', 'yen', 'pound',
    'outlook', 'forecast', 'scenario', 'risk', 'volatility', 'liquidity',
    'macro', 'macroeconomic', 'strategy', 'tactical', 'allocation'
]

# Outlook language patterns
OUTLOOK_PATTERNS = [
    r'\bour\s+view\b',
    r'\bwe\s+expect\b',
    r'\bwe\s+believe\b',
    r'\bscenario\b',
    r'\boutlook\b',
    r'\bforecast\b',
    r'\bprojection\b',
    r'\brisk\s+factors?\b',
    r'\bkey\s+drivers?\b',
    r'\bwe\s+see\b',
    r'\bwe\s+anticipate\b'
]

# Noise keywords (negative signals)
NOISE_KEYWORDS = [
    'product marketing', 'promotion', 'advertisement', 'advert',
    'career', 'careers', 'recruiting', 'recruitment', 'job', 'jobs',
    'hiring', 'internship', 'intern', 'position available',
    'press release', 'announcement', 'media', 'pr',
    'survey', 'poll', 'questionnaire', 'feedback',
    'podcast', 'video', 'watch now', 'subscribe to our channel'
]

# Event/invite keywords (positive for macro-signal)
EVENT_KEYWORDS = [
    'webinar', 'conference', 'roundtable', 'briefing', 'seminar',
    'forum', 'panel', 'summit', 'event', 'meeting', 'call',
    'presentation', 'launch', 'invitation', 'invite', 'rsvp',
    'register', 'registration', 'join us', 'upcoming'
]


def calculate_newsletter_quality_score(
    subject: str,
    body_text: str = '',
    emails_seen: int = 0,
    intel_items_extracted: int = 0,
    rejection_rate: float = 0.0
) -> Dict[str, any]:
    """
    Calculate newsletter quality score (0-100).
    
    Args:
        subject: Email subject line
        body_text: Email body text
        emails_seen: Historical count of emails from this newsletter
        intel_items_extracted: Historical count of accepted intel items
        rejection_rate: Historical rejection rate (0-1)
    
    Returns:
        Dict with:
        - quality_score: 0-100
        - macro_keyword_density: 0-1
        - has_outlook_language: bool
        - has_event_keywords: bool
        - noise_penalty: 0-1
        - historical_yield: 0-1
        - explanation: str
    """
    full_text = f"{subject} {body_text}".lower()
    
    # 1. Macro keyword density (0-30 points)
    macro_count = sum(1 for kw in MACRO_KEYWORDS if kw in full_text)
    total_words = len(full_text.split())
    macro_density = min(1.0, macro_count / max(20, total_words * 0.05))
    macro_score = int(macro_density * 30)
    
    # 2. Outlook language (0-20 points)
    outlook_score = 0
    has_outlook_language = False
    for pattern in OUTLOOK_PATTERNS:
        if re.search(pattern, full_text, re.I):
            has_outlook_language = True
            outlook_score = 20
            break
    
    # 3. Event/invite keywords (0-15 points)
    event_count = sum(1 for kw in EVENT_KEYWORDS if kw in full_text)
    event_score = min(15, event_count * 3)
    
    # 4. Noise penalty (0-25 points deducted)
    noise_count = sum(1 for kw in NOISE_KEYWORDS if kw in full_text)
    noise_penalty = min(25, noise_count * 5)
    
    # 5. Historical yield (0-20 points)
    historical_yield = 0.0
    if emails_seen > 0:
        historical_yield = intel_items_extracted / emails_seen
    yield_score = int(historical_yield * 20)
    
    # Calculate base score
    base_score = macro_score + outlook_score + event_score - noise_penalty + yield_score
    
    # Apply rejection rate penalty
    rejection_penalty = int(rejection_rate * 15)
    final_score = max(0, min(100, base_score - rejection_penalty))
    
    # Build explanation
    explanation_parts = []
    if macro_score > 0:
        explanation_parts.append(f"macro keywords ({macro_count})")
    if outlook_score > 0:
        explanation_parts.append("outlook language")
    if event_score > 0:
        explanation_parts.append(f"event keywords ({event_count})")
    if noise_penalty > 0:
        explanation_parts.append(f"noise penalty ({noise_count})")
    if yield_score > 0:
        explanation_parts.append(f"historical yield ({historical_yield:.1%})")
    if rejection_penalty > 0:
        explanation_parts.append(f"rejection penalty ({rejection_rate:.1%})")
    
    explanation = ", ".join(explanation_parts) if explanation_parts else "minimal signals"
    
    return {
        'quality_score': final_score,
        'macro_keyword_density': round(macro_density, 3),
        'has_outlook_language': has_outlook_language,
        'has_event_keywords': event_count > 0,
        'noise_penalty': round(noise_penalty / 25, 3),
        'historical_yield': round(historical_yield, 3),
        'explanation': explanation
    }


def should_auto_subscribe(quality_score: int, has_captcha: bool, requires_login: bool) -> str:
    """
    Determine subscription decision based on quality score and obstacles.
    
    Returns:
        'auto_subscribe' | 'manual_review_required' | 'reject'
    """
    if has_captcha or requires_login:
        return 'manual_review_required'
    
    if quality_score >= 70:
        return 'auto_subscribe'
    elif quality_score >= 40:
        return 'manual_review_required'
    else:
        return 'reject'


def update_newsletter_quality_stats(
    newsletter_id: str,
    email_processed: bool = True,
    intel_extracted: bool = False,
    rejected: bool = False
) -> Dict:
    """
    Update newsletter quality statistics in database.
    
    Returns:
        Updated stats dict
    """
    from backend.db import get_db
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get current stats
    cursor.execute("""
        SELECT emails_seen, intel_items_extracted, rejection_rate
        FROM newsletter_quality
        WHERE newsletter_id = ?
    """, (newsletter_id,))
    
    row = cursor.fetchone()
    if row:
        emails_seen = row['emails_seen'] or 0
        intel_items = row['intel_items_extracted'] or 0
        rejection_rate = row['rejection_rate'] or 0.0
    else:
        emails_seen = 0
        intel_items = 0
        rejection_rate = 0.0
    
    # Update counts
    if email_processed:
        emails_seen += 1
    if intel_extracted:
        intel_items += 1
    if rejected:
        # Update rejection rate (simple moving average)
        total_processed = emails_seen
        if total_processed > 0:
            current_rejections = rejection_rate * (total_processed - 1)
            rejection_rate = (current_rejections + 1) / total_processed
    
    # Recalculate rejection rate
    if emails_seen > 0:
        rejection_rate = 1.0 - (intel_items / emails_seen)
    
    # Upsert stats
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO newsletter_quality
        (newsletter_id, emails_seen, intel_items_extracted, rejection_rate, last_updated)
        VALUES (?, ?, ?, ?, ?)
    """, (newsletter_id, emails_seen, intel_items, rejection_rate, now))
    
    conn.commit()
    conn.close()
    
    return {
        'newsletter_id': newsletter_id,
        'emails_seen': emails_seen,
        'intel_items_extracted': intel_items,
        'rejection_rate': rejection_rate,
        'yield': intel_items / emails_seen if emails_seen > 0 else 0.0
    }
