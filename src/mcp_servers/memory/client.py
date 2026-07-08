from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("mcp-memory.client")


def get_embedding(text: str) -> list[float] | None:
    """Retrieve embedding vector for the given text using Gemini or OpenAI API keys if available.

    Returns None if no API keys are set or if the request fails.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if gemini_key:
        try:
            # Gemini text-embedding-004
            url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={gemini_key}"
            payload = {"content": {"parts": [{"text": text}]}}
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("embedding", {}).get("values")
                else:
                    logger.warning(
                        "Gemini embedding API returned status %d: %s",
                        resp.status_code,
                        resp.text,
                    )
        except Exception as e:
            logger.error("Failed to fetch Gemini embedding: %s", e)

    elif openai_key:
        try:
            # OpenAI text-embedding-3-small
            url = "https://api.openai.com/v1/embeddings"
            headers = {
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json",
            }
            payload = {"input": text, "model": "text-embedding-3-small"}
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("data", [{}])[0].get("embedding")
                else:
                    logger.warning(
                        "OpenAI embedding API returned status %d: %s",
                        resp.status_code,
                        resp.text,
                    )
        except Exception as e:
            logger.error("Failed to fetch OpenAI embedding: %s", e)

    return None
