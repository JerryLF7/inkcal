"""Unified record locator for all write commands.

Supports four modes, resolved in order of specificity:
  --id PREFIX     asset_id prefix match     (existing behaviour)
  --ref N         records.id lookup          (shortest to type)
  --last          most recent record
  --meal K [--date D]  keyword + optional date (FTS5 + LIKE fallback)

Returns Resolution: .record (unique), .candidates (ambiguous), .error (not_found).
The caller is expected to handle ambiguous / not_found gracefully.
"""

from dataclasses import dataclass, field
from src import db


@dataclass
class Resolution:
    record: dict | None = None
    candidates: list[dict] = field(default_factory=list)
    error: str | None = None       # 'not_found' | 'ambiguous'


def _to_primary(rec: dict) -> dict:
    """同餐组从行归并到主记录：写命令只应作用于主记录。"""
    if rec.get("merged_into"):
        root = db.get_record_by_asset_id(rec["merged_into"])
        if root:
            return root
    return rec


def resolve(
    *,
    asset_prefix: str | None = None,
    ref: int | None = None,
    last: bool = False,
    meal: str | None = None,
    date: str | None = None,
) -> Resolution:
    """Locate a single record. Returns Resolution — never raises."""

    if ref is not None:
        row = db.get_record_by_id(ref)
        return Resolution(_to_primary(row) if row else None,
                          error=None if row else "not_found")

    if asset_prefix:
        hits = db.find_records_by_asset_id_prefix(asset_prefix, date)
    elif last:
        all_records = db.get_records_by_date_range("1970-01-01", "2999-12-31")
        hits = all_records[-1:] if all_records else []
    elif meal:
        hits = db.search_records(meal, start_date=date, end_date=date, limit=5)
    else:
        raise ValueError("no locator given — need one of asset_prefix/ref/last/meal")

    # 同餐组归并：从行映射到组主记录并去重（避免同一餐被列成多个候选）
    seen: dict[str, dict] = {}
    for h in hits:
        p = _to_primary(h)
        seen.setdefault(p["asset_id"], p)
    hits = list(seen.values())

    if len(hits) == 1:
        return Resolution(record=hits[0])
    if not hits:
        return Resolution(error="not_found")
    return Resolution(candidates=hits, error="ambiguous")


def resolve_one(
    *,
    asset_prefix: str | None = None,
    ref: int | None = None,
    last: bool = False,
    meal: str | None = None,
    date: str | None = None,
) -> dict:
    """Convenience: resolve and return the single record, or raise a human-readable error.

    Suitable for CLI commands that want to fail-fast with a printed message.
    For programmatic callers, use resolve() and handle Resolution yourself.
    """
    r = resolve(asset_prefix=asset_prefix, ref=ref, last=last,
                meal=meal, date=date)
    if r.record:
        return r.record
    if r.error == "ambiguous":
        candidates = [
            {"id": c.get("id"), "asset_id": c.get("asset_id"),
             "meal": c.get("meal"), "photo_time": c.get("photo_time"),
             "calories": c.get("calories")}
            for c in r.candidates
        ]
        msg = f"匹配到 {len(r.candidates)} 条记录，请缩小范围"
        raise ResolverError("ambiguous", msg, candidates=candidates)
    else:
        msg = f"未找到匹配记录"
        if asset_prefix:
            msg = f"未找到匹配记录: {asset_prefix}"
        elif ref is not None:
            msg = f"未找到 id={ref} 的记录"
        elif meal:
            msg = f"未找到匹配 “{meal}” 的记录"
        raise ResolverError("not_found", msg)


class ResolverError(Exception):
    """Structured lookup failure so callers can distinguish not_found vs ambiguous."""
    def __init__(self, code: str, message: str, candidates: list[dict] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.candidates = candidates or []
