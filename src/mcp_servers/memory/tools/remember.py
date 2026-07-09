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
        if args.key:
            # Atomic upsert keyed on the UNIQUE key column: no check-then-insert race,
            # so concurrent writes to the same key can't both INSERT. The RETURNING
            # clause reports whether the row was newly created (created_at == updated_at
            # only on a fresh insert; an update bumps updated_at but keeps created_at).
            row = conn.execute(
                """
                INSERT INTO memories (id, key, content, category, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (key) DO UPDATE SET
                    content = excluded.content,
                    category = excluded.category,
                    tags = excluded.tags,
                    updated_at = excluded.updated_at
                RETURNING id, (created_at = updated_at) AS created
                """,
                [mem_id, args.key, args.content, args.category, tags_str, now, now],
            ).fetchone()
            # INSERT ... RETURNING always yields the affected row.
            assert row is not None
            result_id = row[0]
            action = "created" if row[1] else "updated"
        else:
            # Keyless memories never collide, so a plain insert is sufficient.
            conn.execute(
                """
                INSERT INTO memories (id, key, content, category, tags, created_at, updated_at)
                VALUES (?, NULL, ?, ?, ?, ?, ?)
                """,
                [mem_id, args.content, args.category, tags_str, now, now],
            )
            result_id, action = mem_id, "created"

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
