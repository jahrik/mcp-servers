from __future__ import annotations

import asyncio
import glob
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from typing import Any

from ..client import get_embedding
from ..models.schemas import SyncExistingDataArgs
from .db import get_db_conn


def parse_brain_artifacts(brain_dir: str) -> list[dict[str, Any]]:
    """Scan the brain directory for markdown artifacts."""
    memories = []
    # Find all .md files under brain_dir
    pattern = os.path.join(brain_dir, "**", "*.md")
    for filepath in glob.glob(pattern, recursive=True):
        # Skip files under .system_generated
        if ".system_generated" in filepath:
            continue
        try:
            rel_path = os.path.relpath(filepath, brain_dir)
            with open(filepath, encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                continue

            # Extract parent directory as conversation ID
            parts = rel_path.split(os.sep)
            conv_id = parts[0] if len(parts) > 1 else "unknown"

            # Create a unique stable key
            key = f"brain/{rel_path}"

            memories.append(
                {
                    "key": key,
                    "content": content,
                    "category": "artifact",
                    "tags": ["artifact", conv_id],
                }
            )
        except Exception:
            pass
    return memories


def parse_conversation_summaries(db_path: str) -> list[dict[str, Any]]:
    """Scan the conversation summaries SQLite database."""
    memories = []
    if not os.path.exists(db_path):
        return memories

    try:
        # Connect to SQLite (standard library)
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                """
                SELECT conversation_id, title, preview, step_count, last_modified_time, workspace_uris
                FROM conversation_summaries
                """
            )
            rows = cursor.fetchall()
            for row in rows:
                conv_id, title, preview, step_count, last_modified, workspace_uris = row

                # Skip blank/empty summaries
                if not title and not preview:
                    continue

                title_str = title or f"Conversation {conv_id[:8]}"
                preview_str = preview or "(No preview available)"

                content = (
                    f"# Conversation Summary: {title_str}\n"
                    f"- **Conversation ID:** {conv_id}\n"
                    f"- **Step Count:** {step_count}\n"
                    f"- **Last Modified:** {last_modified}\n"
                    f"- **Workspace URIs:** {workspace_uris}\n\n"
                    f"## Preview:\n"
                    f"{preview_str}"
                )

                key = f"summary/{conv_id}"
                memories.append(
                    {
                        "key": key,
                        "content": content.strip(),
                        "category": "conversation_summary",
                        "tags": ["summary", "conversation", conv_id[:8]],
                    }
                )
        finally:
            conn.close()
    except Exception:
        pass
    return memories


def parse_claude_sessions(claude_dir: str) -> list[dict[str, Any]]:
    """Scan the Claude projects directory for session JSONL logs."""
    memories = []
    # Find all *.jsonl files under projects/
    pattern = os.path.join(claude_dir, "**", "*.jsonl")
    for filepath in glob.glob(pattern, recursive=True):
        try:
            session_id = os.path.splitext(os.path.basename(filepath))[0]
            title = ""
            cwd = ""
            turns: list[dict[str, str]] = []
            timestamp = ""

            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                        obj_type = obj.get("type")

                        if obj_type == "ai-title":
                            title = obj.get("aiTitle", "")

                        if obj.get("cwd") and not cwd:
                            cwd = obj.get("cwd")
                        if obj.get("timestamp") and not timestamp:
                            timestamp = obj.get("timestamp")

                        # Extract user message
                        if obj_type == "user":
                            msg_content = obj.get("message", {}).get("content", "")
                            # If content is a dict/list rather than string (e.g. multi-modal)
                            if isinstance(msg_content, list):
                                text_parts = []
                                for part in msg_content:
                                    if isinstance(part, dict) and part.get("type") == "text":
                                        text_parts.append(part.get("text", ""))
                                msg_content = "\n".join(text_parts)
                            elif isinstance(msg_content, dict):
                                msg_content = json.dumps(msg_content)

                            # Skip local caveat commands to keep memory clean
                            if "<local-command-caveat>" in msg_content:
                                continue
                            if "<command-name>" in msg_content:
                                continue

                            if msg_content:
                                turns.append({"role": "user", "text": msg_content})

                        # Extract assistant response
                        elif obj_type == "assistant":
                            msg = obj.get("message", {})
                            content_list = msg.get("content", [])
                            if isinstance(content_list, list):
                                text_parts = []
                                for part in content_list:
                                    if isinstance(part, dict) and part.get("type") == "text":
                                        text_parts.append(part.get("text", ""))
                                    elif isinstance(part, dict) and part.get("type") == "thinking":
                                        # Skip raw thinking payload
                                        continue
                                assistant_text = "\n".join(text_parts)
                                if assistant_text:
                                    turns.append({"role": "assistant", "text": assistant_text})
                    except Exception:
                        pass

            if not turns:
                continue

            # Format the output session summary
            title_str = title or f"Session {session_id[:8]}"
            date_str = timestamp or "unknown time"
            cwd_str = cwd or "unknown workspace"

            markdown_lines = [
                f"# Claude Session: {title_str}",
                f"- **Session ID:** {session_id}",
                f"- **Timestamp:** {date_str}",
                f"- **Workspace:** {cwd_str}",
                "",
                "## Interaction History:",
            ]

            for turn in turns:
                role = "User" if turn["role"] == "user" else "Claude"
                # Indent lines of text
                text_indented = "\n".join(f"  {line}" for line in turn["text"].splitlines())
                markdown_lines.append(f"- **{role}:**\n{text_indented}")

            content = "\n".join(markdown_lines).strip()
            key = f"claude/{session_id}"

            memories.append(
                {
                    "key": key,
                    "content": content,
                    "category": "claude_session",
                    "tags": ["claude", "session_log", session_id[:8]],
                }
            )
        except Exception:
            pass
    return memories


def _execute_sync(args: SyncExistingDataArgs) -> str:
    # Resolve default paths
    brain_dir = args.brain_dir or os.path.expanduser("~/.gemini/antigravity-cli/brain")
    summaries_db = args.summaries_db or os.path.expanduser(
        "~/.gemini/antigravity-cli/conversation_summaries.db"
    )
    claude_dir = args.claude_dir or os.path.expanduser("~/.claude/projects")

    # Ingest data
    artifacts = parse_brain_artifacts(brain_dir) if os.path.exists(brain_dir) else []
    summaries = parse_conversation_summaries(summaries_db) if os.path.exists(summaries_db) else []
    claude_sessions = parse_claude_sessions(claude_dir) if os.path.exists(claude_dir) else []

    all_memories = artifacts + summaries + claude_sessions

    if args.dry_run:
        return json.dumps(
            {
                "dry_run": True,
                "stats": {
                    "total_found": len(all_memories),
                    "brain_artifacts": len(artifacts),
                    "conversation_summaries": len(summaries),
                    "claude_sessions": len(claude_sessions),
                },
                "preview": [
                    {
                        "key": m["key"],
                        "category": m["category"],
                        "content_length": len(m["content"]),
                        "tags": m["tags"],
                    }
                    for m in all_memories[:10]
                ],
            }
        )

    # Perform DB writes
    now = datetime.now().isoformat()
    imported_count = 0

    with get_db_conn(read_only=False) as conn:
        for m in all_memories:
            try:
                # Calculate embedding vector (optional)
                embedding_val = get_embedding(m["content"])
                tags_str = json.dumps(m["tags"])

                # Check if exists
                cursor = conn.execute("SELECT id FROM memories WHERE key = ?", [m["key"]])
                row = cursor.fetchone()

                if row:
                    # Update
                    conn.execute(
                        """
                        UPDATE memories
                        SET content = ?, category = ?, tags = ?, embedding = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        [m["content"], m["category"], tags_str, embedding_val, now, row[0]],
                    )
                else:
                    # Insert
                    mem_id = str(uuid_uuid_from_key(m["key"]))
                    conn.execute(
                        """
                        INSERT INTO memories (id, key, content, category, tags, embedding, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            mem_id,
                            m["key"],
                            m["content"],
                            m["category"],
                            tags_str,
                            embedding_val,
                            now,
                            now,
                        ],
                    )
                imported_count += 1
            except Exception:
                pass

    return json.dumps(
        {
            "dry_run": False,
            "imported": imported_count,
            "stats": {
                "brain_artifacts": len(artifacts),
                "conversation_summaries": len(summaries),
                "claude_sessions": len(claude_sessions),
            },
        }
    )


def uuid_uuid_from_key(key: str) -> str:
    """Generate a stable UUID from a key name."""
    # Construct a valid UUID v4 shape from md5 hash bytes
    # (Just a simple deterministic UUID generator for stable IDs)
    return str(hashlib.md5(key.encode("utf-8")).hexdigest())


async def sync_existing_data(args: SyncExistingDataArgs) -> str:
    """Scan and synchronize existing memory traces from Antigravity and Claude history.

    This includes user/agent brain artifacts, conversation summaries database,
    and Claude projects session logs, merging them into the long-term memory.

    Args:
        dry_run: Preview the changes without saving (optional).
        brain_dir: Custom path to Antigravity brain directory (optional).
        summaries_db: Custom path to Antigravity summaries SQLite database (optional).
        claude_dir: Custom path to Claude projects directory (optional).
    """
    return await asyncio.to_thread(_execute_sync, args)
