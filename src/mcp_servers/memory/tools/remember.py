from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime

from ..models.schemas import RememberArgs
from .db import get_db_conn, rebuild_fts_index


def _execute_remember(args: RememberArgs) -> str:
    # 1. Resolve key uniqueness and generate an ID
    mem_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    tags_str = json.dumps(args.tags) if args.tags is not None else None

    with get_db_conn(read_only=False) as conn:
        existing_id = None
        if args.key:
            # Check if key already exists
            cursor = conn.execute("SELECT id FROM memories WHERE key = ?", [args.key])
            row = cursor.fetchone()
            if row:
                existing_id = row[0]

        if existing_id:
            # Update the existing memory
            conn.execute(
                """
                UPDATE memories
                SET content = ?, category = ?, tags = ?, updated_at = ?
                WHERE id = ?
                """,
                [
                    args.content,
                    args.category,
                    tags_str,
                    now,
                    existing_id,
                ],
            )
            action, result_id = "updated", existing_id
        else:
            # Insert a new memory
            conn.execute(
                """
                INSERT INTO memories (id, key, content, category, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    mem_id,
                    args.key,
                    args.content,
                    args.category,
                    tags_str,
                    now,
                    now,
                ],
            )
            action, result_id = "created", mem_id

        # Refresh the full-text index so the new/updated content is searchable.
        rebuild_fts_index(conn)

    return json.dumps(
        {
            "status": "success",
            "action": action,
            "id": result_id,
            "key": args.key,
        }
    )


async def remember(args: RememberArgs) -> str:
    """Store a fact, preference, project detail, or instruction in long-term memory.

    If a memory with the same key already exists, it is overwritten with the new content.

    Args:
        content: The text/fact to remember.
        key: Unique lookup key (optional).
        category: Category group (optional).
        tags: List of labels (optional).
    """
    return await asyncio.to_thread(_execute_remember, args)
