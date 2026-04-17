"""
tools/search.py — DuckDuckGo search wrapper for Researcher agents.

Public surface:
    search(query, max_results=5, timeout=10) -> list[dict]
    batch_search(queries, max_results=5) -> dict[str, list[dict]]

Each result dict has keys: "title", "url", "snippet".
"""
from __future__ import annotations
import os, json, time, hashlib, traceback
from pathlib import Path

CACHE_DIR = Path(os.environ.get("VFLOW_CACHE_DIR", "/tmp/vflow_search_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MAX_RESULTS = 5
DEFAULT_TIMEOUT     = 10
MAX_RETRIES         = 2
BACKOFF_BASE        = 2.0


def _cache_path(query: str, max_results: int) -> Path:
    h = hashlib.sha1(f"{query}|{max_results}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.json"


def _load_cache(query: str, max_results: int):
    p = _cache_path(query, max_results)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    return None


def _save_cache(query: str, max_results: int, results: list[dict]):
    try:
        _cache_path(query, max_results).write_text(json.dumps(results))
    except Exception:
        pass


def search(query: str, max_results: int = DEFAULT_MAX_RESULTS,
           timeout: int = DEFAULT_TIMEOUT, use_cache: bool = True) -> list[dict]:
    """Run a single DDG search. Returns [] on terminal failure — never raises."""
    if use_cache:
        cached = _load_cache(query, max_results)
        if cached is not None:
            return cached

    try:
        from ddgs import DDGS
    except ImportError:
        print("[search] ddgs not installed — returning empty results")
        return []

    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            with DDGS(timeout=timeout) as ddgs:
                raw = list(ddgs.text(query, max_results=max_results))
            results = [
                {
                    "title":   r.get("title", ""),
                    "url":     r.get("href", "") or r.get("url", ""),
                    "snippet": r.get("body", "") or r.get("snippet", ""),
                }
                for r in raw
            ]
            if use_cache:
                _save_cache(query, max_results, results)
            return results
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE ** attempt)
            continue

    print(f"[search] FAILED after {MAX_RETRIES + 1} attempts: {query!r} -- {last_err}")
    return []


def batch_search(queries: list[str], max_results: int = DEFAULT_MAX_RESULTS,
                 use_cache: bool = True) -> dict[str, list[dict]]:
    """Run multiple searches sequentially. Returns {query: results}."""
    out = {}
    for q in queries:
        out[q] = search(q, max_results=max_results, use_cache=use_cache)
    return out


if __name__ == "__main__":
    # Smoke test: python -m tools.search "your query"
    import sys
    q = " ".join(sys.argv[1:]) or "CRISPR diagnostic market size"
    for r in search(q, max_results=3):
        print(f"- {r['title']}\n  {r['url']}\n  {r['snippet'][:120]}...")
