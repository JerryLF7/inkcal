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

print("\nall passed (fully isolated chat smoke tests)")
