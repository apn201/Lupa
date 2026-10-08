"""What every model answer must pass before anything uses it.

1. It parses as JSON and validates against its pydantic model.
2. Every code it names is in that task's fixed vocabulary.
3. Every number it puts in a field appears in the data it was given
   (the virta/guardrails rule). A field that invents a figure sinks the answer.

Any failure returns None, and the caller falls back to "AI unavailable".
"""

from __future__ import annotations

import logging
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger("lupa.ai.guard")

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
M = TypeVar("M", bound=BaseModel)


def known_numbers(data: Any) -> set[str]:
    """Every number in the data the model saw, in the forms it might be written."""
    found: set[str] = set()

    def add(value: float) -> None:
        for digits in (0, 1, 2):
            found.add(f"{round(value, digits):g}")
        found.add(str(int(value)))

    def walk(node: Any) -> None:
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, float)):
            add(float(node))
        elif isinstance(node, str):
            for n in NUMBER.findall(node):
                add(float(n.replace(",", ".")))
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(k)
                walk(v)
        elif isinstance(node, (list, tuple, set)):
            for v in node:
                walk(v)

    walk(data)
    return found


def ungrounded(value: Any, grounded: set[str], small_ok: int = 12) -> list[str]:
    """Numbers in `value` absent from `grounded`. Small whole counts are allowed."""
    missing: list[str] = []
    for n in NUMBER.findall(str(value)):
        v = float(n.replace(",", "."))
        if v <= small_ok and v == int(v):
            continue
        if f"{v:g}" not in grounded and n not in grounded:
            missing.append(n)
    return missing


def check(task: str, data: dict | None, model: type[M], *, vocab: set[str] | None = None,
          code_fields: tuple[str, ...] = ("reason_codes",), number_fields: tuple[str, ...] = (),
          context: Any = None) -> M | None:
    if data is None:
        return None
    try:
        parsed = model.model_validate(data)
    except ValidationError as exc:
        log.warning("guard %s: invalid shape: %s", task, exc.errors()[:2])
        return None
    if vocab is not None:
        for f in code_fields:
            codes = getattr(parsed, f, None)
            codes = codes if isinstance(codes, list) else [codes]
            bad = [c for c in codes if c is not None and c not in vocab]
            if bad:
                log.warning("guard %s: codes outside vocabulary: %s", task, bad)
                return None
    if number_fields:
        grounded = known_numbers(context)
        for f in number_fields:
            value = getattr(parsed, f, None)
            if value is None:
                continue
            missing = ungrounded(value, grounded)
            if missing:
                log.warning("guard %s: %s holds ungrounded numbers %s", task, f, missing)
                return None
    return parsed
