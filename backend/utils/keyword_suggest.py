"""
Keyword Suggestion Module

Provides deterministic heuristics to suggest include/exclude keywords
for newsletter targets based on observed subjects and body snippets.
"""
import re
from typing import List, Dict, Set, Tuple
from collections import Counter


# Known high-signal keywords for macro events
KNOWN_INCLUDE_KEYWORDS = {
    'webinar', 'briefing', 'outlook', 'strategy', 'roundtable',
    'conference call', 'registration', 'rsvp', 'join us', 'virtual event',
    'live', 'panel', 'fireside', 'macro', 'rates', 'fx', 'credit',
    'forum', 'summit', 'discussion', 'seminar', 'symposium',
    'market update', 'economic', 'monetary policy', 'central bank',
    'fixed income', 'foreign exchange', 'liquidity', 'inflation',
    'interest rate', 'geopolitics', 'regulation', 'risk'
}

# Known low-signal / noise keywords to exclude
KNOWN_EXCLUDE_KEYWORDS = {
    'earnings', 'results', 'quarterly', 'press release', 'recruitment',
    'career', 'internship', 'marketing', 'podcast', 'survey',
    'report download', 'dividend', 'appointment', 'promotion',
    'annual report', 'q1', 'q2', 'q3', 'q4', 'fiscal', '10-k', '10-q',
    'hiring', 'job', 'vacancy', 'graduate program', 'sale', 'discount',
    'offer', 'whitepaper', 'ebook', 'download now', 'unsubscribe'
}


def tokenize_text(text: str) -> List[str]:
    """
    Tokenize text into lowercase words/phrases.
    """
    if not text:
        return []
    
    # Normalize
    text = text.lower()
    
    # Extract words
    words = re.findall(r'\b[a-z]{2,}\b', text)
    
    # Also extract 2-word phrases
    phrases = []
    for i in range(len(words) - 1):
        phrases.append(f"{words[i]} {words[i+1]}")
    
    return words + phrases


def score_keyword_relevance(keyword: str, subjects: List[str], bodies: List[str] = None) -> float:
    """
    Score how relevant a keyword is based on frequency in subjects/bodies.
    
    Returns:
        Score from 0.0 to 1.0
    """
    all_text = ' '.join(subjects)
    if bodies:
        all_text += ' ' + ' '.join(bodies)
    all_text = all_text.lower()
    
    # Count occurrences
    count = all_text.count(keyword.lower())
    
    # Normalize by text length
    if len(all_text) == 0:
        return 0.0
    
    # Higher weight for subject matches
    subject_text = ' '.join(subjects).lower()
    subject_count = subject_text.count(keyword.lower())
    
    # Score: subject matches count 3x
    score = (subject_count * 3 + count) / max(1, len(subjects))
    
    return min(1.0, score)


def suggest_keywords(
    subjects: List[str],
    bodies: List[str] = None,
    existing_include: List[str] = None,
    existing_exclude: List[str] = None
) -> Dict[str, List[Dict]]:
    """
    Suggest include/exclude keywords based on observed text.
    
    Args:
        subjects: List of email subjects
        bodies: List of email body snippets (optional)
        existing_include: Currently configured include keywords
        existing_exclude: Currently configured exclude keywords
    
    Returns:
        Dict with 'suggested_include', 'suggested_exclude', 'remove_include', 'remove_exclude'
        Each is a list of dicts with 'keyword', 'reason', 'score'
    """
    existing_include = set(k.lower() for k in (existing_include or []))
    existing_exclude = set(k.lower() for k in (existing_exclude or []))
    
    # Tokenize all text
    all_tokens = []
    for subj in subjects:
        all_tokens.extend(tokenize_text(subj))
    if bodies:
        for body in bodies:
            all_tokens.extend(tokenize_text(body[:2000]))  # Limit body length
    
    token_counts = Counter(all_tokens)
    
    results = {
        'suggested_include': [],
        'suggested_exclude': [],
        'remove_include': [],
        'remove_exclude': []
    }
    
    # Find include suggestions
    for kw in KNOWN_INCLUDE_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower in existing_include:
            continue
        
        score = score_keyword_relevance(kw, subjects, bodies)
        if score >= 0.1:
            results['suggested_include'].append({
                'keyword': kw,
                'reason': f'Found in {int(score * 100)}% of samples; known high-signal keyword',
                'score': round(score, 2)
            })
    
    # Find exclude suggestions
    for kw in KNOWN_EXCLUDE_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower in existing_exclude:
            continue
        
        score = score_keyword_relevance(kw, subjects, bodies)
        if score >= 0.1:
            results['suggested_exclude'].append({
                'keyword': kw,
                'reason': f'Found in {int(score * 100)}% of samples; known noise keyword',
                'score': round(score, 2)
            })
    
    # Check if existing includes are NOT appearing (maybe remove?)
    for kw in existing_include:
        score = score_keyword_relevance(kw, subjects, bodies)
        if score < 0.05 and len(subjects) >= 3:
            results['remove_include'].append({
                'keyword': kw,
                'reason': 'Rarely appears in observed samples',
                'score': round(score, 2)
            })
    
    # Sort by score
    for key in results:
        results[key] = sorted(results[key], key=lambda x: -x['score'])
    
    return results


def generate_keyword_patch(
    target_id: str,
    target_name: str,
    subjects: List[str],
    bodies: List[str] = None,
    existing_include: List[str] = None,
    existing_exclude: List[str] = None
) -> Dict:
    """
    Generate a proposed keyword patch for a target.
    
    Returns:
        Dict with target_id, target_name, suggestions, and proposed_changes
    """
    suggestions = suggest_keywords(subjects, bodies, existing_include, existing_exclude)
    
    # Build proposed changes
    proposed_add_include = [s['keyword'] for s in suggestions['suggested_include'][:5]]
    proposed_add_exclude = [s['keyword'] for s in suggestions['suggested_exclude'][:5]]
    proposed_remove_include = [s['keyword'] for s in suggestions['remove_include'][:3]]
    
    return {
        'target_id': target_id,
        'target_name': target_name,
        'sample_count': len(subjects),
        'suggestions': suggestions,
        'proposed_changes': {
            'add_include': proposed_add_include,
            'add_exclude': proposed_add_exclude,
            'remove_include': proposed_remove_include
        }
    }


def format_keyword_patch_report(patches: List[Dict]) -> str:
    """
    Format keyword patches as a readable report.
    """
    lines = []
    lines.append("# Keyword Suggestions Report")
    lines.append("")
    
    for patch in patches:
        if not patch['proposed_changes']['add_include'] and not patch['proposed_changes']['add_exclude']:
            continue
        
        lines.append(f"## {patch['target_name']} ({patch['target_id']})")
        lines.append("")
        lines.append(f"Based on {patch['sample_count']} observed message(s):")
        lines.append("")
        
        if patch['proposed_changes']['add_include']:
            lines.append("**Suggested Include Keywords:**")
            for kw in patch['proposed_changes']['add_include']:
                # Find the suggestion detail
                detail = next((s for s in patch['suggestions']['suggested_include'] if s['keyword'] == kw), None)
                if detail:
                    lines.append(f"- `{kw}` (score: {detail['score']})")
            lines.append("")
        
        if patch['proposed_changes']['add_exclude']:
            lines.append("**Suggested Exclude Keywords:**")
            for kw in patch['proposed_changes']['add_exclude']:
                detail = next((s for s in patch['suggestions']['suggested_exclude'] if s['keyword'] == kw), None)
                if detail:
                    lines.append(f"- `{kw}` (score: {detail['score']})")
            lines.append("")
        
        if patch['proposed_changes']['remove_include']:
            lines.append("**Consider Removing from Include:**")
            for kw in patch['proposed_changes']['remove_include']:
                detail = next((s for s in patch['suggestions']['remove_include'] if s['keyword'] == kw), None)
                if detail:
                    lines.append(f"- `{kw}` ({detail['reason']})")
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    return '\n'.join(lines)
