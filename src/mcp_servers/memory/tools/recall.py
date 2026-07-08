from __future__ import annotations

import asyncio
import contextlib
import json
import math

from ..client import get_embedding
from ..models.schemas import RecallArgs
from .db import get_db_conn


def cosine_similarity(v1: list[float] | None, v2: list[float] | None) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2, strict=True))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


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
    query_embedding = get_embedding(args.query)

    # Build SQL query with basic category filter
    sql = "SELECT id, key, content, category, tags, embedding, created_at, updated_at FROM memories"
    params = []
    if args.category:
        sql += " WHERE category = ?"
        params.append(args.category)

    with get_db_conn(read_only=True) as conn:
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()

    scored_results = []
    for row in rows:
        mem_id, key, content, category, tags_json, embedding_val, created_at, updated_at = row

        # Parse tags
        tags = []
        if tags_json:
            with contextlib.suppress(Exception):
                tags = json.loads(tags_json)

        # Filter by tags if specified (matching any of the tags)
        if args.tags and (not tags or not any(t in tags for t in args.tags)):
            continue

        # Score the memory
        if query_embedding and embedding_val:
            score = cosine_similarity(query_embedding, embedding_val)
        else:
            score = get_keyword_score(content, key, args.query)

        # Only include memories that have some relevance
        if score > 0.0:
            scored_results.append(
                (
                    score,
                    {
                        "id": mem_id,
                        "key": key,
                        "content": content,
                        "category": category,
                        "tags": tags,
                        "created_at": created_at.isoformat() if created_at else None,
                        "updated_at": updated_at.isoformat() if updated_at else None,
                    },
                )
            )

    # Sort by score descending
    scored_results.sort(key=lambda x: x[0], reverse=True)

    # Return top N results
    top_results = [item[1] for item in scored_results[: args.limit]]
    return json.dumps({"results": top_results})


async def recall(args: RecallArgs) -> str:
    """Search stored memories for facts, preferences, or details relevant to a query.

    Uses vector embeddings if configured, falling back to keyword and token overlap search.

    Args:
        query: Search term or query text.
        category: Filter by category (optional).
        tags: Filter by tags (optional).
        limit: Max results (optional).
    """
    return await asyncio.to_thread(_execute_recall, args)
