"""
Entity Matching: Institutional participation inference for macro-signal events.

This module identifies financial institutions (banks, asset managers, policy institutions)
from event titles, descriptions, and participant text.

Core Principle: Banks are participants, not publishers. This module infers institutional
participation in macro-signal events hosted by associations, think tanks, and policy forums.
"""
import sys
import re
import hashlib
from pathlib import Path
from typing import List, Set, Dict

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


# Canonical bank registry with aliases
BANK_REGISTRY: Dict[str, List[str]] = {
    'JPMorgan Chase': [
        'jpmorgan chase',
        'jpmorgan',
        'j.p. morgan',
        'jp morgan',
        'jpm',
        'jpmorganchase'
    ],
    'Goldman Sachs': [
        'goldman sachs',
        'goldman',
        'gs'
    ],
    'Morgan Stanley': [
        'morgan stanley',
        'ms'
    ],
    'Bank of America': [
        'bank of america',
        'bofa',
        'boa',
        'b of a',
        'bankofamerica'
    ],
    'Citigroup': [
        'citigroup',
        'citi',
        'c'
    ],
    'Barclays': [
        'barclays',
        'barclays bank',
        'barclays plc'
    ],
    'Deutsche Bank': [
        'deutsche bank',
        'deutsche',
        'db'
    ],
    'UBS': [
        'ubs',
        'union bank of switzerland'
    ],
    'Société Générale': [
        'société générale',
        'societe generale',
        'socgen',
        'sg'
    ],
    'BNP Paribas': [
        'bnp paribas',
        'bnpp',
        'bnp'
    ]
}


def normalize_text(text: str) -> str:
    """
    Normalize text for matching.
    
    - Convert to lowercase
    - Strip punctuation
    - Collapse whitespace
    """
    if not text:
        return ''
    
    # Lowercase
    text = text.lower()
    
    # Replace common punctuation with spaces
    text = re.sub(r'[.,;:!?\'"()\[\]{}]', ' ', text)
    
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def extract_bank_participants(text: str) -> List[str]:
    """
    Extract bank participants from text.
    
    Rules:
    - Input: raw speaker/participant text (title, description, speakers)
    - Output: sorted list of canonical bank names
    - Deduplicate aliases
    - Never return partial matches (word-boundary matching)
    
    Args:
        text: Raw text to search for bank names
    
    Returns:
        Sorted list of canonical bank names found in text
    """
    if not text:
        return []
    
    normalized = normalize_text(text)
    if not normalized:
        return []
    
    found_banks: Set[str] = set()
    
    # For each canonical bank, check all aliases
    for canonical_name, aliases in BANK_REGISTRY.items():
        # Check canonical name
        canonical_normalized = normalize_text(canonical_name)
        if canonical_normalized:
            # Word-boundary matching for canonical name
            pattern = r'\b' + re.escape(canonical_normalized) + r'\b'
            if re.search(pattern, normalized):
                found_banks.add(canonical_name)
                continue
        
        # Check aliases
        for alias in aliases:
            alias_normalized = normalize_text(alias)
            if not alias_normalized:
                continue
            
            # Word-boundary matching to avoid false positives
            # Special handling for short aliases (JPM, MS, GS, etc.)
            if len(alias_normalized) <= 3:
                # For short aliases, require word boundaries or start/end of string
                pattern = r'(?:^|\s)' + re.escape(alias_normalized) + r'(?:\s|$)'
            else:
                # For longer aliases, standard word-boundary matching
                pattern = r'\b' + re.escape(alias_normalized) + r'\b'
            
            if re.search(pattern, normalized):
                found_banks.add(canonical_name)
                break  # Found this bank, move to next
    
    return sorted(list(found_banks))


def save_evidence(text: str, matched_banks: List[str], method: str = 'unknown') -> str:
    """
    Save entity matching evidence to file.
    
    Args:
        text: Raw text that was analyzed
        matched_banks: List of banks found
        method: Matching method (title/description/speakers)
    
    Returns:
        Path to evidence file
    """
    evidence_dir = backend_dir / "_evidence"
    evidence_dir.mkdir(exist_ok=True)
    
    # Generate hash from text
    text_hash = hashlib.md5(text[:1000].encode()).hexdigest()[:8]
    
    evidence_file = evidence_dir / f"entity_match_{text_hash}.txt"
    
    with open(evidence_file, 'w') as f:
        f.write(f"Entity Matching Evidence\n")
        f.write(f"{'='*60}\n\n")
        f.write(f"Method: {method}\n")
        f.write(f"Matched Banks: {', '.join(matched_banks) if matched_banks else 'None'}\n")
        f.write(f"\n{'='*60}\n")
        f.write(f"Raw Text (first 3000 chars):\n")
        f.write(f"{'='*60}\n")
        f.write(text[:3000])
        if len(text) > 3000:
            f.write(f"\n\n[... truncated, total length: {len(text)} chars]")
    
    return str(evidence_file)


def extract_bank_participants_with_evidence(text: str, method: str = 'unknown') -> tuple[List[str], str]:
    """
    Extract bank participants and save evidence.
    
    Args:
        text: Raw text to search
        method: Matching method (title/description/speakers)
    
    Returns:
        (matched_banks, evidence_file_path)
    """
    matched_banks = extract_bank_participants(text)
    evidence_path = save_evidence(text, matched_banks, method)
    return matched_banks, evidence_path
