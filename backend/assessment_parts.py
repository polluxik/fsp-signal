"""Shared helpers for public assessment question definitions and private keys."""

from typing import Any


def part(identifier: str, prompt: str, points: int, answer: Any, phase: int = 1,
         options: list | None = None):
    public = {"id": identifier, "prompt": prompt, "points": points, "phase": phase,
              "type": "choice" if options else "number"}
    if options:
        public["options"] = options
    return public, answer


def structured_part(identifier: str, prompt: str, points: int, fields: list[dict], answer: dict,
                    phase: int = 1):
    return {"id": identifier, "prompt": prompt, "points": points, "phase": phase,
            "type": "structured", "fields": fields}, answer
