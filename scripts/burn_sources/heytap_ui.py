#!/usr/bin/env python3
"""heytap_ui: 从运行在 redroid 中的 OPPO 健康无头实例抓取每日步数与活动消耗并入库 inkcal
用法:
  python3 scripts/burn_sources/heytap_ui.py              # 默认抓取今天
  python3 scripts/burn_sources/heytap_ui.py --yesterday  # 凌晨抓取昨日收口终值
  python3 scripts/burn_sources/heytap_ui.py --date 2026-09-23 # 抓取指定历史日期(支持回溯)
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from datetime import datetime, date, timedelta
import xml.etree.ElementTree as ET

SERIAL = "your-server-host:5555"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def adb(*args, timeout=30):
    return subprocess.run(["adb", "-s", SERIAL, *args],
                          capture_output=True, text=True, timeout=timeout)


def ensure_home():
    subprocess.run(["adb", "connect", SERIAL], capture_output=True, timeout=10)
    for _ in range(3):
        adb("shell", "am", "start", "-n", "com.heytap.health/.oobe.LaunchActivity")
        time.sleep(4)
        # 下拉刷新促使欢太云同步
        adb("shell", "input", "swipe", "540", "600", "540", "1400", "300")
        time.sleep(3)
        w = adb("shell", "dumpsys", "window")
        if "com.heytap.health.main.MainActivity" in (w.stdout or ""):
            return True
        time.sleep(2)
    return False


def dump_xml():
    for _ in range(5):
        adb("shell", "uiautomator", "dump", "/sdcard/hp.xml")
        r = adb("shell", "cat", "/sdcard/hp.xml")
        if (r.stdout or "").lstrip().startswith("<?xml"):
            return r.stdout
        time.sleep(2)
    return None


def num_after(root, label, cap):
    texts = [(n.get("text") or "") for n in root.iter("node")]
    for i, t in enumerate(texts):
        if t == label:
            for t2 in texts[i + 1:i + 6]:
                if t2.isdigit() and int(t2) < cap:
                    return int(t2)
    return None


def pull_today():
    xml = dump_xml()
    if not xml:
        return None, None
    root = ET.fromstring(xml)
    steps = num_after(root, "步数", 200000)
    kcal = num_after(root, "活动消耗", 10000)
    return steps, kcal


def parse_detail_page(root):
    """解析每日活动详情页(DailyActivityDetailActivity)的步数和消耗"""
    steps = None
    kcal = None

    for n in root.iter("node"):
        txt = (n.get("text") or "").strip()
        cid = n.get("resource-id") or ""
        # 1. 优先从 tv_daily_detail_step 读真实总步数: "7866 / 6000步"
        if cid == "com.heytap.health:id/tv_daily_detail_step" and "/" in txt:
            try:
                steps = int(txt.split("/")[0].strip())
            except ValueError:
                pass
        # 2. 从详情环形图下方取活动消耗数值 (右上方卡片)
        # bounds 格式: [774,418][876,489] 紧跟在活动消耗下方
        b = n.get("bounds") or ""
        if txt.isdigit() and b.startswith("["):
            try:
                x1 = int(b.split("]")[0].split(",")[0].replace("[", ""))
                y1 = int(b.split("]")[0].split(",")[1])
                # 右上方活动消耗数字区域
                if 700 <= x1 <= 850 and 380 <= y1 <= 500:
                    kcal = int(txt)
            except Exception:
                pass

    if steps is None:
        steps = num_after(root, "步数", 200000)
    if kcal is None:
        kcal = num_after(root, "活动消耗", 10000)
    return steps, kcal


def pull_history(days_back: int):
    """进入每日活动详情页，点击前一天按钮回溯并读取数据"""
    # 确保进入二级详情页
    for _ in range(3):
        adb("shell", "input", "tap", "846", "448")
        time.sleep(2.5)
        w = adb("shell", "dumpsys", "window")
        if "DailyActivityDetailActivity" in (w.stdout or ""):
            break

    # 循环点击前一天按钮 iv_last (90, 270)
    for _ in range(days_back):
        adb("shell", "input", "tap", "90", "270")
        time.sleep(1.8)

    xml = dump_xml()
    # 按返回键回到主页
    adb("shell", "input", "keyevent", "4")

    if not xml:
        return None, None
    root = ET.fromstring(xml)
    return parse_detail_page(root)


def sync_to_inkcal(out: dict):
    py = sys.executable if (REPO_ROOT / "venv").exists() else f"{REPO_ROOT}/venv/bin/python"
    main_py = str(REPO_ROOT / "main.py")
    try:
        subprocess.run(
            [py, main_py, "burn",
             "--date", out["date"],
             "--kcal", str(out["active_kcal"]),
             "--steps", str(out["steps"]),
             "--source", out["source"],
             "--json"],
            capture_output=True, check=True
        )
    except Exception as e:
        print(f"WARN: sync to inkcal failed: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Pull HeyTap health data")
    parser.add_argument("--date", help="Target date (YYYY-MM-DD), defaults to today")
    parser.add_argument("--yesterday", action="store_true", help="Pull yesterday's finalized data")
    args = parser.parse_args()

    today_dt = date.today()
    if args.yesterday:
        target_dt = today_dt - timedelta(days=1)
        target_date_str = target_dt.strftime("%Y-%m-%d")
    elif args.date:
        target_date_str = args.date
        target_dt = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    else:
        target_dt = today_dt
        target_date_str = today_dt.strftime("%Y-%m-%d")

    if target_dt > today_dt:
        sys.exit("ERR: 不能获取未来日期的数据")

    days_back = (today_dt - target_dt).days

    if not ensure_home():
        sys.exit("ERR: 首页拉不起来")

    if days_back == 0:
        steps, kcal = pull_today()
    else:
        steps, kcal = pull_history(days_back)

    if steps is None or kcal is None:
        sys.exit(f"ERR: 解析失败 steps={steps} kcal={kcal}")

    out = {
        "date": target_date_str,
        "steps": steps,
        "active_kcal": kcal,
        "source": "heytap-ui",
    }
    print(json.dumps(out, ensure_ascii=False))
    sync_to_inkcal(out)


if __name__ == "__main__":
    main()
