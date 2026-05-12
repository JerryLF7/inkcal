"""
Immich API client — fetch assets, match by perceptual hash.
"""

import io
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
import imagehash
from PIL import Image


HKT = timezone(timedelta(hours=8))


def _parse_utc_offset(tz_str: str) -> timezone:
    """Parse Immich timeZone like 'UTC+8' or 'UTC-5.5' into timezone."""
    if tz_str.startswith("UTC"):
        offset = tz_str[3:]  # '+8' or '-5.5'
        sign = 1 if offset[0] == '+' else -1
        hours = float(offset[1:])
        total_minutes = int(hours * 60)
        return timezone(timedelta(minutes=sign * total_minutes))
    # Try ±HH:MM format
    m = re.match(r"^([+-])(\d{2}):(\d{2})$", tz_str)
    if m:
        sign = 1 if m.group(1) == '+' else -1
        hours, minutes = int(m.group(2)), int(m.group(3))
        return timezone(timedelta(hours=sign * hours, minutes=sign * minutes))
    raise ValueError(f"Unknown timezone format: {tz_str!r}")


def format_photo_time(date_time_original: str, timezone_str: str | None) -> str:
    """Construct photo_time ISO string from Immich exifInfo fields.
    timezone_str: Immich-provided offset like 'UTC+8'.
    """
    dt = datetime.fromisoformat(date_time_original.replace("Z", "+00:00"))
    if timezone_str:
        try:
            tz = _parse_utc_offset(timezone_str)
            return dt.astimezone(tz).isoformat()
        except ValueError:
            pass
    if dt.utcoffset() is None:
        return dt.replace(tzinfo=HKT).isoformat()
    return dt.astimezone(HKT).isoformat()


class ImmichClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "x-api-key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._client = httpx.Client(base_url=self.base_url, headers=self.headers, timeout=30)

    def search_assets(
        self,
        taken_after: str | None = None,
        taken_before: str | None = None,
        page: int = 1,
        size: int = 100,
    ) -> list[dict[str, Any]]:
        """Search assets by date range. Returns list of asset dicts."""
        body: dict[str, Any] = {
            "page": page,
            "size": size,
            "type": "IMAGE",
            "withPeople": False,
            "withExif": True,
        }
        if taken_after:
            body["takenAfter"] = taken_after
        if taken_before:
            body["takenBefore"] = taken_before

        r = self._client.post("/api/search/metadata", json=body)
        r.raise_for_status()
        data = r.json()
        return data.get("assets", {}).get("items", [])

    def get_date_assets(self, date: datetime) -> list[dict[str, Any]]:
        """Get all images taken on a given date (Asia/Hong_Kong timezone)."""
        hkt = date.astimezone(timezone(timedelta(hours=8)))
        start = hkt.replace(hour=0, minute=0, second=0, microsecond=0)
        end = hkt.replace(hour=23, minute=59, second=59, microsecond=999999)
        return self._fetch_assets_in_range(start.isoformat(), end.isoformat())

    def get_today_assets(self) -> list[dict[str, Any]]:
        """Get all images taken today (Asia/Hong_Kong timezone)."""
        return self.get_date_assets(datetime.now(timezone(timedelta(hours=8))))

    def _fetch_assets_in_range(self, after: str, before: str) -> list[dict[str, Any]]:
        all_assets = []
        page = 1
        while True:
            batch = self.search_assets(taken_after=after, taken_before=before, page=page)
            if not batch:
                break
            all_assets.extend(batch)
            page += 1
        return all_assets

    def get_thumbnail_url(self, asset_id: str) -> str:
        """Get the URL to download a thumbnail for an asset."""
        return f"{self.base_url}/api/assets/{asset_id}/thumbnail?size=preview"

    def get_original_url(self, asset_id: str) -> str:
        """Get the URL to download the original image for an asset."""
        return f"{self.base_url}/api/assets/{asset_id}/original"

    def download_thumbnail(self, asset_id: str) -> bytes:
        """Download thumbnail image bytes for an asset."""
        r = self._client.get(f"/api/assets/{asset_id}/thumbnail?size=preview")
        r.raise_for_status()
        return r.content

    def download_original(self, asset_id: str) -> bytes:
        """Download original image bytes for an asset."""
        r = self._client.get(f"/api/assets/{asset_id}/original")
        r.raise_for_status()
        return r.content

    def match_by_phash(self, date_str: str, image_bytes: bytes,
                       time_window: str | None = None, threshold: int = 15
                       ) -> dict | None:
        """Find a photo in Immich whose pHash matches the given image bytes.

        If time_window is provided (ISO timestamp), search ±5 min around it.
        Otherwise search the full date.
        Returns {id, thumbnail_url, photo_time} or None.
        """
        try:
            if time_window:
                ts = datetime.fromisoformat(time_window)
                start = (ts - timedelta(minutes=5)).isoformat()
                end = (ts + timedelta(minutes=5)).isoformat()
                size = 50
            else:
                start = f"{date_str}T00:00:00+08:00"
                end = f"{date_str}T23:59:59+08:00"
                size = 500

            assets = self.search_assets(taken_after=start, taken_before=end, size=size)
        except Exception as e:
            import sys
            print(f"  [pHash] search failed: {e}", file=sys.stderr, flush=True)
            return None

        import sys
        print(f"  [pHash] date={date_str} time_window={time_window} assets_found={len(assets)}", file=sys.stderr, flush=True)

        target_hash = imagehash.phash(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
        best_match = None
        best_dist = threshold + 1

        for asset in assets:
            try:
                rid = asset["id"]
                thumb = self.download_thumbnail(rid)
                dist = imagehash.phash(Image.open(io.BytesIO(thumb)).convert("RGB")) - target_hash
                if dist < best_dist:
                    best_dist = dist
                    exif = asset.get("exifInfo", {})
                    raw_pt = exif.get("dateTimeOriginal", "")
                    exif_tz = exif.get("timeZone")
                    best_match = {
                        "id": rid,
                        "thumbnail_url": self.get_original_url(rid),
                        "photo_time": format_photo_time(raw_pt, exif_tz),
                    }
                    if dist <= 2:
                        break
            except Exception:
                continue

        print(f"  [pHash] best_dist={best_dist} threshold={threshold} matched={best_match is not None}", file=sys.stderr, flush=True)
        return best_match if best_match and best_dist <= threshold else None

    @staticmethod
    def extract_exif_time(image_bytes: bytes) -> str | None:
        """Extract DateTimeOriginal + OffsetTimeOriginal from EXIF.
        Returns ISO string with timezone if offset is present, else naive string.
        """
        try:
            img = Image.open(io.BytesIO(image_bytes))
            exif = img._getexif() or {}
            dt_str = exif.get(36867) or exif.get(306)
            if dt_str:
                dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
                offset_str = exif.get(0x9011)  # OffsetTimeOriginal
                if offset_str:
                    sign = 1 if offset_str[0] == '+' else -1
                    hours, minutes = int(offset_str[1:3]), int(offset_str[4:6])
                    tz = timezone(timedelta(hours=sign * hours, minutes=sign * minutes))
                    dt = dt.replace(tzinfo=tz)
                return dt.isoformat()
        except Exception:
            pass
        return None

    def close(self):
        self._client.close()
