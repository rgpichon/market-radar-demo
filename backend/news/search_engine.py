"""
Hybrid search engine for the news feed.
Combines TF-IDF semantic similarity with keyword boosting.
Index is built lazily on first search and cached in memory.
"""
import logging
import re
import time
from typing import Dict, List

logger = logging.getLogger(__name__)

_tfidf = None
_matrix = None
_index_items: List[Dict] = []
_index_built_at: float = 0.0
INDEX_TTL = 300

SYNONYMS = {
    "fed": ["federal reserve", "fomc", "powell", "monetary policy"],
    "ecb": ["european central bank", "lagarde", "euro area"],
    "rate hike": ["tightening", "rate increase", "hawkish", "interest rate"],
    "rate cut": ["easing", "dovish", "rate reduction", "loosening"],
    "inflation": ["cpi", "pce", "price pressure", "cost of living"],
    "recession": ["contraction", "slowdown", "gdp decline", "downturn"],
    "tariff": ["trade war", "import duty", "trade policy", "protectionism"],
    "china": ["prc", "beijing", "chinese", "xi jinping"],
    "ai": ["artificial intelligence", "machine learning", "llm", "gpt"],
    "semiconductor": ["chip", "chipmaker", "foundry", "wafer", "nvidia", "tsmc"],
    "energy": ["oil", "gas", "crude", "lng", "renewable", "solar", "wind"],
    "defense": ["military", "nato", "weapons", "arms", "warfare"],
    "crypto": ["bitcoin", "ethereum", "blockchain", "digital asset"],
    "climate": ["carbon", "emissions", "net zero", "green energy", "esg"],
    "bank": ["lending", "credit", "deposit", "banking", "financial"],
    "stock": ["equity", "shares", "market cap", "valuation"],
    "bond": ["fixed income", "treasury", "yield", "debt", "credit"],
}


def _expand_query(query: str) -> str:
    q_lower = query.lower().strip()
    expansions = [q_lower]
    for key, syns in SYNONYMS.items():
        if key in q_lower:
            expansions.extend(syns)
        for syn in syns:
            if syn in q_lower:
                expansions.append(key)
                break
    return " ".join(set(expansions))


def _build_corpus(items: List[Dict]) -> List[str]:
    corpus = []
    for item in items:
        parts = [
            (item.get("title") or "") * 3,
            (item.get("description") or "") * 2,
            item.get("topic") or "",
            item.get("source_name") or "",
            (item.get("extra") or {}).get("intel_type") or "",
        ]
        corpus.append(" ".join(p for p in parts if p).lower())
    return corpus


def _ensure_index(items: List[Dict]) -> None:
    global _tfidf, _matrix, _index_items, _index_built_at

    now = time.time()
    if _tfidf is not None and _matrix is not None and _index_items is items and (now - _index_built_at) < INDEX_TTL:
        return

    if _tfidf is not None and _matrix is not None and (now - _index_built_at) < INDEX_TTL and len(_index_items) == len(items):
        return

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer

        logger.info("[search] Building TF-IDF index over %d items...", len(items))
        corpus = _build_corpus(items)
        _tfidf = TfidfVectorizer(
            max_features=15000,
            ngram_range=(1, 2),
            min_df=1,
            stop_words="english",
            sublinear_tf=True,
        )
        _matrix = _tfidf.fit_transform(corpus)
        _index_items = items
        _index_built_at = now
        logger.info("[search] Index built successfully.")
    except Exception as e:
        logger.warning("[search] Failed to build TF-IDF index: %s", e)
        _tfidf = None
        _matrix = None
        _index_items = items


def _keyword_score(item: Dict, query_terms: List[str]) -> float:
    text = " ".join(
        [
            item.get("title") or "",
            item.get("description") or "",
            item.get("topic") or "",
            item.get("source_name") or "",
        ]
    ).lower()

    score = 0.0
    for term in query_terms:
        if not term:
            continue
        term_lower = term.lower()
        if term_lower in (item.get("title") or "").lower():
            score += 3.0
        if term_lower in (item.get("description") or "").lower():
            score += 1.5
        if term_lower in (item.get("topic") or "").lower():
            score += 2.0
        if term_lower in text:
            score += 0.5
    return score


def search(query: str, items: List[Dict], limit: int = 30, min_score: float = 0.05) -> List[Dict]:
    if not query or not query.strip():
        return []

    query = query.strip()
    expanded = _expand_query(query)
    query_terms = list(set(re.findall(r"\b\w{3,}\b", query.lower())))

    tfidf_scores: Dict[int, float] = {}
    _ensure_index(items)

    if _tfidf is not None and _matrix is not None:
        try:
            from sklearn.metrics.pairwise import cosine_similarity

            query_vec = _tfidf.transform([expanded])
            similarities = cosine_similarity(query_vec, _matrix).flatten()
            for idx, score in enumerate(similarities):
                if score > 0:
                    tfidf_scores[idx] = float(score)
        except Exception as e:
            logger.warning("[search] TF-IDF scoring failed: %s", e)

    results = []
    for idx, item in enumerate(items):
        tfidf = tfidf_scores.get(idx, 0.0)
        keyword = _keyword_score(item, query_terms)
        combined = tfidf * 4.0 + keyword
        if combined >= min_score:
            result = dict(item)
            result["search_score"] = round(combined, 4)
            results.append(result)

    results.sort(key=lambda x: x["search_score"], reverse=True)
    return results[:limit]
