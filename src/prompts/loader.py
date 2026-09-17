"""
Load user-overridable prompt templates for the calorie analyzer.

Resolution order:
  1. ~/.inkcal/prompts/<name>.md   (user override — edit freely, no need to touch code)
  2. <pkg>/prompts/<name>.md       (shipped default — what you see in this repo)
  3. inline _FALLBACK (last-resort string in case the .md files are missing)

Templates may contain str.format() placeholders (e.g. {meal}, {notes}).
The .md body is read raw, not stripped of whitespace — keep your indentation
deliberate if you want it in the final prompt.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from string import Formatter

logger = logging.getLogger(__name__)

_USER_PROMPTS_DIR = Path(os.path.expanduser("~/.inkcal/prompts"))
_PKG_PROMPTS_DIR = Path(__file__).resolve().parent  # this dir


# ── Inline last-resort fallbacks (only used if BOTH .md files vanish) ────────
_FALLBACK_ANALYZE = """You are a nutritionist analyzing a food photo. Return JSON with meal, calories, protein_g, carbs_g, fat_g, confidence. Reject non-real-food with meal="not real food"."""

_FALLBACK_REANALYZE = """You are a nutritionist re-evaluating a food photo.
Previous: {meal}, {calories} kcal
Notes: {notes}
Return JSON with meal, calories, protein_g, carbs_g, fat_g, confidence."""

_FALLBACK_ANALYZE_TEXT = """You are a nutritionist estimating calories from a food description: {description}. Return JSON with meal, meal_detail, calories, protein_g, carbs_g, fat_g, confidence."""


def _load(name: str, fallback: str) -> str:
    """Load prompt text from user dir → package dir → inline fallback."""
    for src, base in (("user", _USER_PROMPTS_DIR), ("pkg", _PKG_PROMPTS_DIR)):
        path = base / f"{name}.md"
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
                logger.info("Loaded prompt '%s' from %s: %s", name, src, path)
                return text
            except OSError as e:
                logger.warning("Could not read prompt %s: %s", path, e)
    logger.warning("No prompt file found for '%s', using inline fallback", name)
    return fallback


def get_analyze_prompt() -> str:
    """Prompt for first-pass calorie analysis."""
    return _load("analyze", _FALLBACK_ANALYZE)


def load_packaged_analyze() -> str:
    """
    Shipped analyze.md ONLY — skips the ~/.inkcal/prompts user override.

    Used by the agent batch path for single-photo analyze_with_gemini calls:
    there the template is part of a layered prompt (task_frame + body +
    format_anchor) that encodes system invariants (all-intake baseline,
    JSON contract), so it must not silently change via a user edit. Users
    who want to tune the loop path can edit task_frame rules in code.
    """
    path = _PKG_PROMPTS_DIR / "analyze.md"
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Could not read packaged prompt %s: %s", path, e)
    return _FALLBACK_ANALYZE


def get_reanalyze_prompt() -> str:
    """Prompt template for reanalyze-with-notes. Contains {meal}/{notes} placeholders."""
    return _load("reanalyze", _FALLBACK_REANALYZE)


def get_analyze_text_prompt() -> str:
    """Prompt template for text-based food calorie estimation. Contains {description} placeholder."""
    return _load("analyze_text", _FALLBACK_ANALYZE_TEXT)


def list_placeholders(template: str) -> list[str]:
    """Return the names of str.format() placeholders in a template (for docs/tests)."""
    return [fname for _, fname, _, _ in Formatter().parse(template) if fname]