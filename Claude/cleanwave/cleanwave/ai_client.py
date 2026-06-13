"""
ai_client.py — Groq / OpenRouter advisory pass for vague/ambiguous files.
AI is NEVER the final word. It returns an importance score that informs
whether a vague file stays in deletion_approval or gets upgraded to KEEP.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional, Callable

import requests

from .models import FileInfo, FileDecision, Destination

# ── Config ───────────────────────────────────────────────────────────────────

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3-8b-instruct:free"

MAX_PREVIEW_CHARS = 400
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".html", ".css",
    ".json", ".xml", ".csv", ".yaml", ".yml", ".sh", ".bat",
    ".c", ".cpp", ".h", ".java", ".rb", ".go", ".rs",
}

# Groq free tier: ~30 req/min. 2.5s between batches keeps us safely under.
_INTER_BATCH_DELAY = 2.5

# Hard cap: if there are more vague files than this, skip AI entirely.
# Sending 5k files to a free-tier API one batch at a time would take hours.
AI_FILE_CAP = 200


def _read_preview(path: Path) -> str:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(MAX_PREVIEW_CHARS)
    except OSError:
        return ""


def _build_batch_prompt(batch: list[tuple[int, FileInfo]]) -> str:
    lines = [
        "You are helping assess files on a user's computer for potential cleanup.",
        "For each file below, estimate how important it likely is to keep.",
        "Respond ONLY with a JSON array in the same order as the files.",
        'Each item: {"index": N, "important": true/false, "reason": "brief reason"}',
        "",
        "Files:",
    ]
    for idx, fi in batch:
        age = (time.time() - fi.mtime) / 86400
        preview = _read_preview(fi.path)
        lines.append(f"\n--- [{idx}] ---")
        lines.append(f"Name: {fi.path.name}")
        lines.append(f"Extension: {fi.ext or 'none'}")
        lines.append(f"Size: {fi.size / 1024:.1f} KB")
        lines.append(f"Age: {age:.0f} days")
        if preview:
            lines.append(f"Preview: {preview[:MAX_PREVIEW_CHARS]}")
    return "\n".join(lines)


def _call_api(prompt: str, api_key: str, provider: str) -> Optional[str]:
    if provider == "groq":
        url, model = GROQ_URL, GROQ_MODEL
    else:
        url, model = OPENROUTER_URL, OPENROUTER_MODEL

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 800,
    }

    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)

            if resp.status_code == 429:
                # Respect Retry-After header if present, else back off hard
                retry_after = resp.headers.get("retry-after")
                wait = float(retry_after) if retry_after else min(60, 4 ** attempt)
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        except requests.exceptions.HTTPError:
            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
        except Exception:
            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)

    return None


def _parse_response(raw: str, expected_indices: list[int]) -> dict[int, bool]:
    """Parse AI JSON response into {index: is_important} map."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw.strip())
        if isinstance(data, list):
            return {item["index"]: bool(item.get("important", False)) for item in data}
    except (json.JSONDecodeError, KeyError):
        pass
    # Fallback: treat all as not important (safe — stays in deletion_approval for human)
    return {i: False for i in expected_indices}


def assess_vague_files(
    items: list[tuple[FileInfo, FileDecision]],
    api_key: str,
    provider: str = "groq",
    batch_size: int = 10,
    on_batch_done: Optional[Callable[[int], None]] = None,
) -> list[tuple[FileInfo, FileDecision]]:
    """
    Takes (FileInfo, FileDecision) pairs where needs_ai=True.
    Returns updated decisions: important files are upgraded to KEEP,
    unimportant ones stay in deletion_approval.
    AI failure is safe — files stay in deletion_approval for human review.

    on_batch_done: optional callable(n_files) called after each batch completes,
    so the caller can advance a progress bar in real time.
    """
    if not items or not api_key:
        return items

    updated = list(items)

    for batch_num, start in enumerate(range(0, len(items), batch_size)):
        chunk = items[start: start + batch_size]
        indexed = [(start + i, fi) for i, (fi, _) in enumerate(chunk)]
        indices = [idx for idx, _ in indexed]

        # Rate-limit: pause between batches (not before the very first one)
        if batch_num > 0:
            time.sleep(_INTER_BATCH_DELAY)

        prompt = _build_batch_prompt(indexed)
        raw = _call_api(prompt, api_key, provider)

        if raw is not None:
            importance_map = _parse_response(raw, indices)

            for local_i, (fi, dec) in enumerate(chunk):
                global_i = start + local_i
                important = importance_map.get(global_i, False)

                if important:
                    updated[global_i] = (fi, FileDecision(
                        destination=Destination.KEEP,
                        category="vague",
                        reason="vague name but AI flagged as likely important — keeping for safety",
                        confidence=0.70,
                        needs_ai=False,
                    ))
                else:
                    updated[global_i] = (fi, FileDecision(
                        destination=Destination.DELETION_APPROVAL,
                        category="vague",
                        reason="generic filename, AI assessed as low importance",
                        confidence=0.65,
                        needs_ai=False,
                    ))

        # Always tick progress, even on API failure
        if on_batch_done is not None:
            on_batch_done(len(chunk))

    return updated
