"""PhotoPrism API client — fetch photos, download thumbnails/originals.

Auth: App Password as Bearer token.
Thumbnail API: cookie-free, token-in-URL format /api/v1/t/{hash}/{token}/{size}.
Time fields: TakenAtLocal + TimeZone (IANA name like "Europe/Madrid").
"""

from datetime import datetime, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

HKT = timezone(timedelta(hours=8))


def _parse_photo_time(taken_at_local: str, tz_name: str | None) -> str:
    """Parse PhotoPrism TakenAtLocal into HKT ISO string.

    PhotoPrism returns TakenAtLocal like "2012-08-27T14:40:25Z" where the
    trailing Z is part of the format, NOT an actual UTC indicator. The real
    timezone comes from the separate TimeZone field (IANA name).
    """
    # Strip the trailing Z and parse as naive datetime
    dt_str = taken_at_local.replace("Z", "")
    dt = datetime.fromisoformat(dt_str)

    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
            dt = dt.replace(tzinfo=tz)
            return dt.astimezone(HKT).isoformat()
        except (ZoneInfoNotFoundError, ValueError):
            pass

    # Fallback: treat as HKT
    return dt.replace(tzinfo=HKT).isoformat()


class PhotoPrismClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        self._client = httpx.Client(
            base_url=self.base_url, headers=self.headers, timeout=30
        )
        self._preview_token: str | None = None

    def _update_tokens(self, response: httpx.Response) -> None:
        """Extract preview/download tokens from response headers."""
        self._preview_token = response.headers.get(
            "X-Preview-Token", self._preview_token
        )

    def search_photos(
        self,
        after: str | None = None,
        before: str | None = None,
        count: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Search photos with optional date range filter.

        after/before: YYYY-MM-DD strings for the q parameter.
        """
        q_parts: list[str] = ["type:image"]
        if after:
            q_parts.append(f"after:{after}")
        if before:
            q_parts.append(f"before:{before}")

        params = {
            "count": count,
            "offset": offset,
            "order": "newest",
            "merged": "true",
            "q": " ".join(q_parts),
        }
        r = self._client.get("/api/v1/photos", params=params)
        r.raise_for_status()
        self._update_tokens(r)
        return r.json()

    def get_date_assets(self, date: datetime) -> list[dict[str, Any]]:
        """Get all images taken on a given date (Asia/Hong_Kong timezone).

        Returns list of asset dicts with keys:
          id (UID), photo_time, hash, filename, width, height, mime
        """
        hkt = date.astimezone(HKT)
        date_str = hkt.strftime("%Y-%m-%d")

        all_assets: list[dict[str, Any]] = []
        offset = 0
        count = 100

        while True:
            photos = self.search_photos(
                after=date_str, before=date_str, count=count, offset=offset
            )
            if not photos:
                break

            for photo in photos:
                # Extract primary file
                files = photo.get("Files", [])
                primary = next(
                    (f for f in files if f.get("Primary")),
                    files[0] if files else None,
                )
                if not primary:
                    continue

                all_assets.append(
                    {
                        "id": photo["UID"],
                        "photo_time": _parse_photo_time(
                            photo.get("TakenAtLocal", ""),
                            photo.get("TimeZone"),
                        ),
                        "hash": primary.get("Hash"),
                        "filename": primary.get("Name"),
                        "width": primary.get("Width"),
                        "height": primary.get("Height"),
                        "mime": primary.get("Mime"),
                        "raw": photo,
                    }
                )

            if len(photos) < count:
                break
            offset += count

        return all_assets

    def get_thumbnail_url(self, file_hash: str, size: str = "tile_500") -> str:
        """Construct a thumbnail URL for the given file hash."""
        token = self._preview_token or "public"
        return f"{self.base_url}/api/v1/t/{file_hash}/{token}/{size}"

    def download_thumbnail(self, file_hash: str, size: str = "fit_720") -> bytes:
        """Download thumbnail image bytes for a file hash."""
        url = self.get_thumbnail_url(file_hash, size)
        r = self._client.get(url)
        r.raise_for_status()
        return r.content

    def download_original(self, uid: str) -> bytes:
        """Download original image bytes for a photo UID."""
        r = self._client.get(f"/api/v1/photos/{uid}/dl")
        r.raise_for_status()
        return r.content

    def close(self):
        self._client.close()
