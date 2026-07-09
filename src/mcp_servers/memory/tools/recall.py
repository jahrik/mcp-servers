from __future__ import annotations

import asyncio
import contextlib
import json

import duckdb

from ..models.schemas import RecallArgs
from .db import fts_index_exists, get_db_conn, truncate_content

# Columns fetched for each candidate row, in order.
_ROW_COLUMNS = "id, key, content, category, tags, created_at, updated_at"


def _fts_ranked_rows(conn: duckdb.DuckDBPyConnection, args: RecallArgs) -> list | None:
    """Return candidate rows ranked by BM25 desc using the local full-text index.

    Ranking, the category filter, and (when no tag filter is needed) the LIMIT are
    pushed into SQL, so only matching rows are materialized — not the whole table.
    Returns None when the fts extension or index is unavailable, so the caller falls
    back to lexical token-overlap scoring.
    """
    try:
        conn.execute("LOAD fts;")
    except duckdb.Error:
        return None
    if not fts_index_exists(conn):
        return None

    where = "score IS NOT NULL"
    params: list = [args.query]
    if args.category:
        where += " AND category = ?"
        params.append(args.category)

    # A tag filter is applied in Python after ranking, so the SQL LIMIT is only
    # safe to push down when there is no tag filter.
    limit_clause = ""
    if not args.tags:
        limit_clause = " LIMIT ?"
        params.append(args.limit)

    sql = f"""
        SELECT {_ROW_COLUMNS} FROM (
            SELECT *, fts_main_memories.match_bm25(id, ?) AS score FROM memories
        ) WHERE {where}
        ORDER BY score DESC{limit_clause}
    """
    try:
        return conn.execute(sql, params).fetchall()
    except duckdb.Error:
        return None


def _lexical_ranked_rows(conn: duckdb.DuckDBPyConnection, args: RecallArgs) -> list:
    """Fallback ranking: score category-filtered rows in Python by token overlap."""
    sql = f"SELECT {_ROW_COLUMNS} FROM memories"
    params: list = []
    if args.category:
        sql += " WHERE category = ?"
        params.append(args.category)
    rows = conn.execute(sql, params).fetchall()

    scored = []
    for row in rows:
        score = get_keyword_score(row[2], row[1], args.query)
        if score > 0.0:
            scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored]


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
    with get_db_conn(read_only=True) as conn:
        # Prefer local BM25 full-text ranking (done in SQL); fall back to token overlap.
        ranked_rows = _fts_ranked_rows(conn, args)
        if ranked_rows is None:
            ranked_rows = _lexical_ranked_rows(conn, args)

    results = []
    for row in ranked_rows:
        mem_id, key, content, category, tags_json, created_at, updated_at = row

        # Parse tags
        tags = []
        if tags_json:
            with contextlib.suppress(Exception):
                tags = json.loads(tags_json)

        # Filter by tags if specified (matching any of the tags)
        if args.tags and (not tags or not any(t in tags for t in args.tags)):
            continue

        # Rows arrive already ranked. Scoring used the full content; the returned
        # copy is capped so a large memory cannot overflow the caller's context.
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
        results.append(item)

        if len(results) >= args.limit:
            break

    return json.dumps({"results": results})


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
