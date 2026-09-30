"""Prompt templates shipped as src/prompts/<name>.md.

Templates may contain str.format() placeholders (e.g. {meal}, {notes}).
Read raw, not stripped — keep indentation deliberate.
"""
from pathlib import Path

_DIR = Path(__file__).resolve().parent


def _load(name: str) -> str:
    return (_DIR / f"{name}.md").read_text(encoding="utf-8")


def get_analyze_prompt() -> str:
    return _load("analyze")


def get_reanalyze_prompt() -> str:
    """Contains {meal}/{calories}/{notes} placeholders."""
    return _load("reanalyze")


def get_analyze_text_prompt() -> str:
    """Contains a {description} placeholder."""
    return _load("analyze_text")
