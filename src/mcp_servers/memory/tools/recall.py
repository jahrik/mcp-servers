from __future__ import annotations

import asyncio
import contextlib
import json

import duckdb

from ..models.schemas import RecallArgs
from .db import get_db_conn, truncate_content


def _bm25_scores(conn: duckdb.DuckDBPyConnection, query: str) -> dict[str, float] | None:
    """Return {id: BM25 score} using the local full-text index, or None if unavailable.

    Falls back to None (so the caller uses lexical token-overlap scoring) when the
    fts extension or index is not present — e.g. offline before it is cached, or
    before the first write has built the index.
    """
    try:
        conn.execute("LOAD fts;")
        rows = conn.execute(
            """
            SELECT id, score FROM (
                SELECT id, fts_main_memories.match_bm25(id, ?) AS score
                FROM memories
            ) WHERE score IS NOT NULL
            """,
            [query],
        ).fetchall()
        return {row[0]: row[1] for row in rows}
    except duckdb.Error:
        return None


def get_keyword_score(content: str, key: str | None, query: str) -> float:
    content_lower = content.lower()
    key_lower = (key or "").lower()
    query_lower = query.lower()

    # Exact substring match bonus
    score = 0.0
    if query_lower in content_lower:
        score += 1.0
    if key_lower and query_lower in key_lower:
        score += 1.5

    # Token overlap score
    query_tokens = set(query_lower.split())
    content_tokens = set(content_lower.split() + key_lower.split())
    if query_tokens:
        overlap = len(query_tokens.intersection(content_tokens))
        score += overlap / len(query_tokens)

    return score


def _execute_recall(args: RecallArgs) -> str:
    # Build SQL query with basic category filter
    sql = "SELECT id, key, content, category, tags, created_at, updated_at FROM memories"
    params = []
    if args.category:
        sql += " WHERE category = ?"
        params.append(args.category)

    with get_db_conn(read_only=True) as conn:
        # Prefer local BM25 full-text ranking; fall back to token overlap.
        bm25 = _bm25_scores(conn, args.query)
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()

    scored_results = []
    for row in rows:
        mem_id, key, content, category, tags_json, created_at, updated_at = row

        # Parse tags
        tags = []
        if tags_json:
            with contextlib.suppress(Exception):
                tags = json.loads(tags_json)

        # Filter by tags if specified (matching any of the tags)
        if args.tags and (not tags or not any(t in tags for t in args.tags)):
            continue

        # Score the memory: BM25 when the full-text index is available, else lexical.
        if bm25 is not None:
            score = bm25.get(mem_id, 0.0)
        else:
            score = get_keyword_score(content, key, args.query)

        # Only include memories that have some relevance. Scoring above uses the
        # full content; the returned copy is capped so a large memory cannot
        # overflow the caller's context window.
        if score > 0.0:
            content_text, truncated = truncate_content(content)
            item = {
                "id": mem_id,
                "key": key,
                "content": content_text,
                "category": category,
                "tags": tags,
                "created_at": created_at.isoformat() if created_at else None,
                "updated_at": updated_at.isoformat() if updated_at else None,
            }
            if truncated:
                item["content_truncated"] = True
                item["content_length"] = len(content)
            scored_results.append((score, item))

    # Sort by score descending
    scored_results.sort(key=lambda x: x[0], reverse=True)

    # Return top N results
    top_results = [item[1] for item in scored_results[: args.limit]]
    return json.dumps({"results": top_results})


async def recall(args: RecallArgs) -> str:
    """Search stored memories for facts, preferences, or details relevant to a query.

    Ranks matches with a local BM25 full-text index, falling back to keyword and
    token-overlap scoring when the index is unavailable. Runs fully offline.

    Args:
        query: Search term or query text.
        category: Filter by category (optional).
        tags: Filter by tags (optional).
        limit: Max results (optional).
    """
    return await asyncio.to_thread(_execute_recall, args)
