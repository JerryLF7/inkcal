"""Smoke & regression test for daily burn storage, CLI, and API endpoints.

Runs against an isolated temp DB (production data untouched).
"""
import os
import sys
import tempfile
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("INKCAL_SKIP_AGENT", "1")
os.environ["INKCAL_USER"] = ""
os.environ["INKCAL_PASS"] = ""

from src import db  # noqa: E402


def check(desc, cond):
    if not cond:
        print(f"  FAIL: {desc}")
        raise AssertionError(desc)
    print(f"  OK: {desc}")


def main():
    print("── 1. DB layer: isolated DB test ──")
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_db = tmp_dir / "burn_test.db"
    db.init_db(tmp_db)

    # Test initial state
    burn_none = db.get_daily_burn("2026-09-22")
    check("initial get_daily_burn is None", burn_none is None)

    # Test upsert
    b1 = db.upsert_daily_burn("2026-09-22", 719.0, 14871, "heytap-ui")
    check("upsert returns dict", isinstance(b1, dict))
    check("upsert active_kcal match", b1["active_kcal"] == 719.0)
    check("upsert steps match", b1["steps"] == 14871)
    check("upsert source match", b1["source"] == "heytap-ui")

    # Verify get_daily_burn
    b_get = db.get_daily_burn("2026-09-22")
    check("get_daily_burn returns record", b_get is not None)
    check("get_daily_burn active_kcal match", b_get["active_kcal"] == 719.0)

    # Test update (ON CONFLICT DO UPDATE)
    b2 = db.upsert_daily_burn("2026-09-22", 850.5, 16000, "manual")
    check("update active_kcal match", b2["active_kcal"] == 850.5)
    check("update steps match", b2["steps"] == 16000)
    check("update source match", b2["source"] == "manual")

    # Add another day and test range
    db.upsert_daily_burn("2026-09-23", 420.0, 8000, "heytap-ui")
    burn_range = db.get_daily_burn_range("2026-09-21", "2026-09-24")
    check("burn_range has 2 entries", len(burn_range) == 2)
    check("burn_range has 2026-09-22", "2026-09-22" in burn_range)
    check("burn_range has 2026-09-23", "2026-09-23" in burn_range)

    # Check data version updates when burn is modified
    v1 = db.get_data_version()
    db.upsert_daily_burn("2026-09-22", 999.0, 20000, "manual")
    v2 = db.get_data_version()
    check("data_version changed after burn update", v1 != v2)

    print("\n── 2. CLI layer: main.py burn ──")
    env = os.environ.copy()
    env["INKCAL_DB"] = str(tmp_db)

    # CLI query via --json
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "burn", "--date", "2026-09-22", "--json"],
        capture_output=True, text=True, env=env, check=True
    )
    cli_out = json.loads(r.stdout.strip())
    check("cli query ok", cli_out.get("ok") is True)
    check("cli query kcal match", cli_out["burn"]["active_kcal"] == 999.0)

    # CLI upsert via --json
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "burn",
         "--date", "2026-09-24", "--kcal", "530", "--steps", "11000",
         "--source", "heytap-ui", "--json"],
        capture_output=True, text=True, env=env, check=True
    )
    cli_upsert = json.loads(r.stdout.strip())
    check("cli upsert ok", cli_upsert.get("ok") is True)
    check("cli upsert kcal match", cli_upsert["burn"]["active_kcal"] == 530.0)

    # Verify write took effect in DB
    b_cli = db.get_daily_burn("2026-09-24")
    check("db has CLI write", b_cli is not None and b_cli["active_kcal"] == 530.0)

    print("\n── 3. Web API layer: Flask test client ──")
    from web import server
    server.app.config["TESTING"] = True
    client = server.app.test_client()

    # GET /api/burn
    resp = client.get("/api/burn?date=2026-09-22")
    check("GET /api/burn 200", resp.status_code == 200)
    data = resp.get_json()
    check("GET /api/burn data match", data["burn"]["active_kcal"] == 999.0)

    # PUT /api/burn
    resp = client.put("/api/burn", json={
        "date": "2026-09-25",
        "active_kcal": 666.0,
        "steps": 13500,
        "source": "heytap-ui",
    })
    check("PUT /api/burn 200", resp.status_code == 200)
    data = resp.get_json()
    check("PUT /api/burn returned ok", data.get("ok") is True)
    check("PUT /api/burn active_kcal match", data["burn"]["active_kcal"] == 666.0)

    # Invalid input
    resp = client.put("/api/burn", json={"date": "invalid-date"})
    check("PUT /api/burn invalid date 400", resp.status_code == 400)
    resp = client.put("/api/burn", json={"date": "2026-09-25", "active_kcal": "not-a-number"})
    check("PUT /api/burn invalid active_kcal 400", resp.status_code == 400)

    # GET /api/records includes burn
    resp = client.get("/api/records?date=2026-09-25")
    check("GET /api/records 200", resp.status_code == 200)
    records_data = resp.get_json()
    check("GET /api/records has burn key", "burn" in records_data)
    check("GET /api/records burn active_kcal match", records_data["burn"]["active_kcal"] == 666.0)

    # GET /api/week includes burns
    resp = client.get("/api/week?start=2026-09-21")
    check("GET /api/week 200", resp.status_code == 200)
    week_data = resp.get_json()
    check("GET /api/week has burns key", "burns" in week_data)
    check("GET /api/week by_day has burn key", "burn" in week_data["by_day"]["2026-09-22"])
    check("GET /api/week by_day 2026-09-22 burn match",
          week_data["by_day"]["2026-09-22"]["burn"]["active_kcal"] == 999.0)

    print("\nALL 25 CHECKS PASSED.")


if __name__ == "__main__":
    main()
