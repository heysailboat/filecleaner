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
from typing import Optional

import requests

from .models import FileInfo, FileDecision, Destination

# ── Config ───────────────────────────────────────────────────────────────────

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama3-8b-8192"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3-8b-instruct:free"

MAX_PREVIEW_CHARS = 400
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".html", ".css",
    ".json", ".xml", ".csv", ".yaml", ".yml", ".sh", ".bat",
    ".c", ".cpp", ".h", ".java", ".rb", ".go", ".rs",
}


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

    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            if attempt < 2:
                time.sleep(2 ** attempt)
    return None


def _parse_response(raw: str, expected_indices: list[int]) -> dict[int, bool]:
    """Parse AI JSON response into {index: is_important} map."""
    # Strip markdown fences if present
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
    # Fallback: treat all as not important (conservative)
    return {i: False for i in expected_indices}


def assess_vague_files(
    items: list[tuple[FileInfo, FileDecision]],
    api_key: str,
    provider: str = "groq",
    batch_size: int = 10,
) -> list[tuple[FileInfo, FileDecision]]:
    """
    Takes (FileInfo, FileDecision) pairs where needs_ai=True.
    Returns updated decisions: important files are upgraded to KEEP,
    unimportant ones stay in deletion_approval.
    AI failure is safe — files stay in deletion_approval for human review.
    """
    if not items or not api_key:
        return items

    updated = list(items)

    for start in range(0, len(items), batch_size):
        chunk = items[start: start + batch_size]
        indexed = [(start + i, fi) for i, (fi, _) in enumerate(chunk)]
        indices = [idx for idx, _ in indexed]

        prompt = _build_batch_prompt(indexed)
        raw = _call_api(prompt, api_key, provider)

        if raw is None:
            # AI unavailable — leave as deletion_approval (safe fallback)
            continue

        importance_map = _parse_response(raw, indices)

        for local_i, (fi, dec) in enumerate(chunk):
            global_i = start + local_i
            important = importance_map.get(global_i, False)

            if important:
                updated[global_i] = (fi, FileDecision(
                    destination=Destination.KEEP,
                    category="vague",
                    reason=f"vague name but AI flagged as likely important — keeping for safety",
                    confidence=0.70,
                    needs_ai=False,
                ))
            else:
                # Keep in deletion_approval, update reason
                updated[global_i] = (fi, FileDecision(
                    destination=Destination.DELETION_APPROVAL,
                    category="vague",
                    reason=f"generic filename, AI assessed as low importance",
                    confidence=0.65,
                    needs_ai=False,
                ))

    return updated
