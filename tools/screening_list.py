"""
Trade.gov Consolidated Screening List search tool.
Downloads/caches CSL data and performs fuzzy name matching with rapidfuzz.
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx

from logger import get_logger
from config import SCREENING_LIST_PATH

logger = get_logger(__name__)

# CSL API endpoint
CSL_API_URL = "https://api.trade.gov/gateway/v2/consolidated_screening_list/search"

# Local cache
_csl_cache: Optional[dict] = None
_csl_cache_time: float = 0
CSL_CACHE_TTL = 86400  # 24 hours


async def search_screening_list(name: str, fuzzy: bool = True, threshold: float = 0.70) -> dict:
    """
    Search the Trade.gov Consolidated Screening List.

    Args:
        name: Name to search for
        fuzzy: Whether to use fuzzy matching
        threshold: Minimum similarity score (0-1) for fuzzy matches

    Returns:
        Dict with matches and metadata
    """
    logger.info(f"Screening list search: {name}")

    matches = []

    # Try API search first
    try:
        api_results = await _search_csl_api(name)
        if api_results:
            matches.extend(api_results)
    except Exception as e:
        logger.warning(f"CSL API search failed: {e}")

    # Fuzzy match against local cache if available
    if fuzzy:
        try:
            local_matches = _fuzzy_search_local(name, threshold)
            # Deduplicate with API results
            existing_names = {m.get("matched_name", "").lower() for m in matches}
            for lm in local_matches:
                if lm.get("matched_name", "").lower() not in existing_names:
                    matches.append(lm)
        except Exception as e:
            logger.debug(f"Local fuzzy search unavailable: {e}")

    # Score and classify matches
    classified = []
    for match in matches:
        score = match.get("score", 0)
        if score >= 0.95:
            match["classification"] = "POTENTIAL_MATCH"
        elif score >= threshold:
            match["classification"] = "INVESTIGATE"
        else:
            match["classification"] = "LOW_RELEVANCE"
        classified.append(match)

    return {
        "success": True,
        "query": name,
        "total_matches": len(classified),
        "matches": classified,
        "sources_checked": ["Trade.gov CSL"],
    }


async def _search_csl_api(name: str) -> list[dict]:
    """Search the Trade.gov CSL API."""
    results = []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {
                "q": name,
                "limit": 10,
            }
            # API key is optional for basic searches
            api_key = os.environ.get("TRADE_GOV_API_KEY")
            if api_key:
                params["api_key"] = api_key

            response = await client.get(CSL_API_URL, params=params)

            if response.status_code == 200:
                data = response.json()
                for entry in data.get("results", []):
                    # Calculate name similarity
                    entry_name = entry.get("name", "")
                    score = _simple_name_similarity(name, entry_name)

                    results.append({
                        "matched_name": entry_name,
                        "list_name": entry.get("source", "CSL"),
                        "score": score,
                        "details": {
                            "type": entry.get("type", ""),
                            "programs": entry.get("programs", []),
                            "country": entry.get("country", ""),
                            "source": entry.get("source", ""),
                            "remarks": entry.get("remarks", ""),
                            "alt_names": entry.get("alt_names", []),
                        },
                    })
            else:
                logger.warning(f"CSL API returned {response.status_code}")

    except Exception as e:
        logger.warning(f"CSL API error: {e}")

    return results


def _simple_name_similarity(name1: str, name2: str) -> float:
    """Calculate name similarity score. Uses rapidfuzz if available, falls back to simple ratio."""
    try:
        from rapidfuzz import fuzz
        # Use token_sort_ratio for name order independence
        return fuzz.token_sort_ratio(name1.lower(), name2.lower()) / 100.0
    except ImportError:
        # Simple fallback
        n1 = set(name1.lower().split())
        n2 = set(name2.lower().split())
        if not n1 or not n2:
            return 0.0
        intersection = n1 & n2
        union = n1 | n2
        return len(intersection) / len(union)


def _fuzzy_search_local(name: str, threshold: float) -> list[dict]:
    """Search local screening list cache with fuzzy matching."""
    cache_path = Path(SCREENING_LIST_PATH) / "csl_cache.json"
    if not cache_path.exists():
        return []

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
    except Exception:
        return []

    matches = []
    for entry in entries:
        entry_name = entry.get("name", "")
        score = _simple_name_similarity(name, entry_name)
        if score >= threshold:
            matches.append({
                "matched_name": entry_name,
                "list_name": entry.get("source", "local_cache"),
                "score": score,
                "details": entry,
            })

    # Sort by score descending
    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches[:10]
