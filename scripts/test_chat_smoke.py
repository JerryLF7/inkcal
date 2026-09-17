#!/usr/bin/env python3
"""Smoke test for Phase 5 Calo chat feature and chat API endpoints.

Runs against an isolated temp DB (production data untouched).
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 必须在导入任何模块之前设置隔离环境与临时数据库路径
tmp_dir = Path(tempfile.mkdtemp())
tmp_db = tmp_dir / "smoke_chat.db"
os.environ["INKCAL_DB"] = str(tmp_db)
os.environ["INKCAL_USER"] = ""
os.environ["INKCAL_PASS"] = ""

from src import db  # noqa: E402

# 初始化隔离数据库
db.init_db(tmp_db)

from web.server import app  # noqa: E402

client = app.test_client()

# 1. 验证首页静态服务
r = client.get("/")
assert r.status_code == 200, f"GET / failed: {r.status_code}"
assert b"inkcal" in r.data
assert b"index-" in r.data
print("  ok  GET / 正常返回 Vue 生产 HTML")

# 2. 验证 sessions API（新库应为空）
r = client.get("/api/chat/sessions")
assert r.status_code == 200
sessions = r.get_json()["sessions"]
assert isinstance(sessions, list)
assert len(sessions) == 0, f"期望新隔离库 sessions 为空，实际有 {len(sessions)} 个"
print("  ok  GET /api/chat/sessions 隔离库初始为空")

# 3. 验证创建 session
r = client.post("/api/chat/sessions")
assert r.status_code == 200
new_sid = r.get_json()["session_id"]
assert isinstance(new_sid, int)
assert new_sid == 1, f"期望隔离库首个 session_id 为 1，实际为 {new_sid}"
print(f"  ok  POST /api/chat/sessions 在隔离库成功创建 session_id={new_sid}")

# 4. 验证获取新 session 消息为空
r = client.get(f"/api/chat/messages?session_id={new_sid}")
assert r.status_code == 200
msgs = r.get_json()["messages"]
assert msgs == []
print("  ok  新 session 消息列表初始为空")

# 5. 验证添加并读取结构化 tool_log
db.add_chat_message(new_sid, "user", "今天吃什么")
db.add_chat_message(
    new_sid,
    "assistant",
    "今天摄入了约 650 kcal",
    tool_log=[{
        "name": "get_records_in_range",
        "args": {"start": "2026-09-16", "end": "2026-09-16"},
        "result": {
            "ok": True,
            "count": 1,
            "records": [{
                "id": 99999,
                "asset_id": "test-chat-smoke-asset",
                "photo_time": "2026-09-16 12:00:00+08:00",
                "meal": "卤牛肉饭",
                "meal_detail": "卤牛肉配米饭与青菜",
                "calories": 650,
                "protein_g": 35,
                "carbs_g": 80,
                "fat_g": 15,
                "confidence": "high",
                "thumbnail_url": "http://example.com/thumb.jpg",
                "replacement_image": None,
                "photos": [],
            }],
        },
    }],
)

r = client.get(f"/api/chat/messages?session_id={new_sid}")
assert r.status_code == 200
loaded_msgs = r.get_json()["messages"]
assert len(loaded_msgs) == 2
assert loaded_msgs[0]["content"] == "今天吃什么"
assert loaded_msgs[1]["tool_log"][0]["name"] == "get_records_in_range"
record_data = loaded_msgs[1]["tool_log"][0]["result"]["records"][0]
assert record_data["thumbnail_url"] == "http://example.com/thumb.jpg"
print("  ok  chat 消息持久化与 tool_log / thumbnail_url 正确回显")

# 6. 验证 settings API (chat_window 5~50 限制与读写)
r = client.get("/api/settings")
assert r.status_code == 200
cur_w = r.get_json()["chat_window"]

r = client.put("/api/settings", json={"chat_window": 18})
assert r.status_code == 200
assert r.get_json()["chat_window"] == 18

# 边界测试：超限截断到 5~50
r = client.put("/api/settings", json={"chat_window": 100})
assert r.status_code == 200
assert r.get_json()["chat_window"] == 50

r = client.put("/api/settings", json={"chat_window": 2})
assert r.status_code == 200
assert r.get_json()["chat_window"] == 5

print("  ok  /api/settings chat_window 读写与边界约束正常")

# 7. 验证 analyze_text 提示词模板与 add_record 工具
from src.prompts.loader import get_analyze_text_prompt, list_placeholders
from src.agent_tools import call_chat_tool
from unittest.mock import MagicMock, patch

text_prompt = get_analyze_text_prompt()
assert "description" in list_placeholders(text_prompt), "提示词必须包含 {description} 占位符"
assert "not real food" in text_prompt, "提示词必须包含非真实食物过滤规则"
assert "all-intake baseline" in text_prompt, "提示词必须包含全摄入基准"
print("  ok  get_analyze_text_prompt() 模板与占位符完整")

# 7.1 测试正常食物通过 add_record 添加
fake_analysis = {
    "meal": "休闲零食",
    "meal_detail": "乐事原味薯片约40g",
    "calories": 220,
    "protein_g": 2.5,
    "carbs_g": 21.0,
    "fat_g": 14.0,
    "confidence": "high",
}

mock_analyzer = MagicMock()
mock_analyzer.analyze_text.return_value = fake_analysis

with patch("src.calorie_analyzer.CalorieAnalyzer", return_value=mock_analyzer):
    res = call_chat_tool("add_record", {
        "description": "吃了一包乐事薯片",
        "date": "2026-09-16",
        "time": "15:30",
    }, deps={"pipeline_config": {"gemini_key": "dummy_key"}})

    assert res["ok"] is True, f"add_record 失败: {res}"
    rec = res["record"]
    assert rec["meal"] == "休闲零食"
    assert rec["calories"] == 220
    assert rec["photo_time"] == "2026-09-16T15:30:00+08:00"
    assert rec["asset_id"].startswith("manual-")

    # 查库验证持久化与日期归属
    db_rec = db.get_record_by_asset_id(rec["asset_id"])
    assert db_rec is not None
    assert db_rec["source_type"] == "manual"
    assert db_rec["calories"] == 220
    assert db_rec["photo_time"].startswith("2026-09-16")
    print("  ok  add_record 成功调用 Gemini 分析并落库 manual- 记录")

# 7.2 测试用户显式指定热量覆盖
mock_analyzer.analyze_text.return_value = {
    "meal": "现磨咖啡",
    "meal_detail": "热拿铁大杯",
    "calories": 180,
    "protein_g": 8,
    "carbs_g": 12,
    "fat_g": 9,
    "confidence": "high",
}

with patch("src.calorie_analyzer.CalorieAnalyzer", return_value=mock_analyzer):
    res = call_chat_tool("add_record", {
        "description": "喝了一杯拿铁，包装写着150大卡",
        "date": "2026-09-16",
        "time": "16:00",
        "user_calories": 150,
    }, deps={"pipeline_config": {"gemini_key": "dummy_key"}})

    assert res["ok"] is True
    # 验证 analyze_text 被传入了 user_calories
    mock_analyzer.analyze_text.assert_called_with("喝了一杯拿铁，包装写着150大卡", user_calories=150.0)
    print("  ok  add_record 支持 user_calories 显式热量指定")

# 7.3 测试非食物拒判
mock_analyzer.analyze_text.return_value = {
    "meal": "not real food",
    "meal_detail": "",
    "calories": 0,
    "protein_g": 0,
    "carbs_g": 0,
    "fat_g": 0,
    "confidence": "low",
}

with patch("src.calorie_analyzer.CalorieAnalyzer", return_value=mock_analyzer):
    res = call_chat_tool("add_record", {
        "description": "吃了一颗螺丝钉",
        "date": "2026-09-16",
    }, deps={"pipeline_config": {"gemini_key": "dummy_key"}})

    assert res["ok"] is False
    assert "未能识别" in res["error"]
    print("  ok  add_record 非食物描述正确拦截不落库")

# 8. 验证会话恢复与防空 session 劫持
empty_sid = db.create_chat_session()
# 虽然 empty_sid 比 1 大，但由于它没有消息，get_latest_chat_session_id 优先返回有消息的 session 1
assert db.get_latest_chat_session_id() == new_sid, "空 session 不应抢占最新会话锚点"
print("  ok  get_latest_chat_session_id 优先返回有消息的会话")

# 查询不存在的 session_id，后端自动回退到最新有效会话
r = client.get("/api/chat/messages?session_id=99999")
assert r.status_code == 200
data = r.get_json()
assert data["session_id"] == new_sid, "无效 session_id 应自动回退到最新有效会话"
assert len(data["messages"]) > 0
print("  ok  GET /api/chat/messages 对无效 session_id 平滑回退到有效会话")

print("\nall passed (fully isolated chat smoke tests)")
