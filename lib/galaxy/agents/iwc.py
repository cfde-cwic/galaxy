"""IWC (Intergalactic Workflows Commission) manifest fetching and search helpers.

The previous attempt at IWC integration kept its manifest cache on
``AgentOperationsManager``, which is instantiated per request, so the cache
never hit. Putting the cache at module scope keeps it shared across requests
within a worker process.
"""

import logging
import re
import threading
import time
from typing import (
    Any,
    Optional,
)

from galaxy.util import requests

log = logging.getLogger(__name__)

IWC_MANIFEST_URL = "https://iwc.galaxyproject.org/workflow_manifest.json"
CACHE_TTL_SECONDS = 60 * 60  # one hour

_cache_lock = threading.Lock()
_cached_manifest: Optional[list[dict[str, Any]]] = None
_cached_at: float = 0.0


def clear_manifest_cache() -> None:
    """Reset the manifest cache. Tests use this; production normally won't."""
    global _cached_manifest, _cached_at
    with _cache_lock:
        _cached_manifest = None
        _cached_at = 0.0


def fetch_manifest(timeout: float = 30.0) -> list[dict[str, Any]]:
    """Fetch the IWC manifest, returning a cached copy when fresh."""
    global _cached_manifest, _cached_at
    with _cache_lock:
        now = time.monotonic()
        if _cached_manifest is not None and (now - _cached_at) < CACHE_TTL_SECONDS:
            return _cached_manifest

        response = requests.get(IWC_MANIFEST_URL, timeout=timeout)
        response.raise_for_status()
        manifest = response.json()
        if not isinstance(manifest, list):
            raise ValueError(f"IWC manifest at {IWC_MANIFEST_URL} did not return a JSON array")
        _cached_manifest = manifest
        _cached_at = now
        return manifest


def all_workflows(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten the manifest into a single list of workflow entries."""
    workflows: list[dict[str, Any]] = []
    for entry in manifest:
        workflows.extend(entry.get("workflows", []) or [])
    return workflows


def clean_readme_summary(readme: str, max_length: int = 300) -> str:
    if not readme:
        return ""
    lines: list[str] = []
    for line in readme.split("\n"):
        if line.strip().startswith("#"):
            continue
        if not lines and not line.strip():
            continue
        lines.append(line)
    text = " ".join(" ".join(lines).split())
    if len(text) > max_length:
        text = text[: max_length - 3].rsplit(" ", 1)[0] + "..."
    return text


def extract_tool_names_from_steps(steps: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for step in steps.values():
        if not isinstance(step, dict):
            continue
        tool_id = step.get("tool_id")
        if not tool_id:
            continue
        # toolshed format: server/repos/owner/<name>/<name>/<version> -> <name>
        parts = tool_id.split("/")
        name = parts[-2] if len(parts) > 1 else tool_id
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def enrich_workflow(workflow: dict[str, Any], include_full_readme: bool = False) -> dict[str, Any]:
    definition = workflow.get("definition", {}) or {}
    readme = workflow.get("readme", "") or ""
    creators = definition.get("creator") or []
    authors = []
    if isinstance(creators, list):
        authors = [
            {"name": c.get("name", ""), "orcid": c.get("identifier", "")} for c in creators if isinstance(c, dict)
        ]
    steps = definition.get("steps", {}) or {}
    result: dict[str, Any] = {
        "trsID": workflow.get("trsID", ""),
        "name": definition.get("name", ""),
        "description": definition.get("annotation", ""),
        "tags": definition.get("tags", []) or [],
        "readme_summary": clean_readme_summary(readme),
        "step_count": len(steps) if isinstance(steps, dict) else 0,
        "authors": authors,
        "categories": workflow.get("categories", []) or [],
        "tools_used": extract_tool_names_from_steps(steps),
    }
    if include_full_readme:
        result["readme"] = readme
    return result


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _score(query_tokens: list[str], text: str) -> int:
    if not query_tokens:
        return 0
    text_tokens = set(_tokenize(text))
    return sum(1 for t in query_tokens if t in text_tokens)


def search_workflows(workflows: list[dict[str, Any]], query: str, limit: Optional[int] = None) -> list[dict[str, Any]]:
    """Rank workflows by token overlap against name/description/readme/tags.

    Each returned entry has ``match_score`` attached so callers can surface
    ranking confidence (mirrors galaxy-mcp's recommend_iwc_workflows shape).
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scored: list[tuple[int, dict[str, Any]]] = []
    for wf in workflows:
        enriched = enrich_workflow(wf)
        haystack = " ".join(
            [
                enriched["name"],
                enriched["description"],
                " ".join(enriched["tags"]),
                enriched["readme_summary"],
                " ".join(enriched["tools_used"]),
            ]
        )
        score = _score(query_tokens, haystack)
        if score > 0:
            enriched["match_score"] = score
            scored.append((score, enriched))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    results = [enriched for _, enriched in scored]
    if limit is not None:
        results = results[:limit]
    return results
