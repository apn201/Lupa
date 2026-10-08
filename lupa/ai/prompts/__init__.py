"""Versioned prompts. First line of each file: `version: <task>/<n>`, then `---`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).parent


@lru_cache
def load(task: str) -> tuple[str, str]:
    """(version, system prompt)."""
    text = (HERE / f"{task}.md").read_text(encoding="utf-8")
    head, _, body = text.partition("\n---\n")
    version = head.split(":", 1)[1].strip()
    return version, body.strip()
