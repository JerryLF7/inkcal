"""
Immich API client — fetch today's assets for food tracking.
"""

from datetime import datetime, timezone, timedelta
from typing import Any

import httpx


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

    def download_thumbnail(self, asset_id: str) -> bytes:
        """Download thumbnail image bytes for an asset."""
        r = self._client.get(f"/api/assets/{asset_id}/thumbnail?size=preview")
        r.raise_for_status()
        return r.content

    def close(self):
        self._client.close()
