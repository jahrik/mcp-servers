from __future__ import annotations

import asyncio
import contextlib
import json

from ..models.schemas import ListMemoriesArgs
from .db import get_db_conn, truncate_content


def _execute_list_memories(args: ListMemoriesArgs) -> str:
    sql = "SELECT id, key, content, category, tags, created_at, updated_at FROM memories"
    params = []

    if args.category:
        sql += " WHERE category = ?"
        params.append(args.category)

    sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([args.limit, args.offset])

    with get_db_conn(read_only=True) as conn:
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()

    results = []
    for row in rows:
        mem_id, key, content, category, tags_json, created_at, updated_at = row
        tags = []
        if tags_json:
            with contextlib.suppress(Exception):
                tags = json.loads(tags_json)
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

    return json.dumps({"memories": results})


async def list_memories(args: ListMemoriesArgs) -> str:
    """Retrieve a list of stored memories, optionally filtered by category, sorted by updated time.

    Args:
        category: Filter by category (optional).
        limit: Max results to return (optional).
        offset: Number of memories to skip for pagination (optional).
    """
    return await asyncio.to_thread(_execute_list_memories, args)
