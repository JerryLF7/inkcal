# inkcal · Agent Layer Handoff

> Status: **骨架完成 / 未接入 pipeline**
> Date: 2026-08-22
> Scope: 把 SigLIP2 过滤出的食物照片从「单张直送 Gemini」改为「流入当天 session，由 Luna 做同餐判断与提示词生成，再调 Gemini 专家层评估热量」

---

## 0. 一句话架构

```
SigLIP2 (本地) ──► 新照片批 ──► [Luna 主循环] ──► Decisions (add/update/skip)
                                ├─ tool: get_recent_meals         ── 读 SQLite
                                ├─ tool: query_food_database      ── 读 SQLite
                                └─ tool: analyze_with_gemini      ── 调 Gemini 专家
                          ▲ 失败/越界 ── 降级到旧「单张直送 Gemini」路径（灰度）
```

Luna 是便宜视觉模型（gpt-5.6-luna via openlux），负责**看图、判断同餐、生成辅助提示词**；
Gemini 保留为「数值评估专家」，由 Luna 以工具方式调用。
Harness 失败时回退旧路径，灰度过渡。

---

## 1. 关键决策（拍板过的）

| 决策点 | 决定 | 备注 |
|---|---|---|
| 同餐判断依据 | **仅看图片内容**，不看时间间隔 | 照片 metadata 仅用于排序 |
| 上线策略 | **先灰度** | harness 失败 → 旧路径兜底 |
| 每天一个 session | 是 | session 状态层（todo 3）尚未实现 |
| 前端 agent 交互 | 暂缓 | 形态以后单独聊（todo 6） |
| 模型选择 | Luna = openlux 网关 / `gpt-5.6-luna`；Gemini = `gemini-3.1-pro-preview`（保留） | 配置见 §4 |
| 未来换 fx 的代价 | 工具层 + 契约层 = 0；只换 loop | 详见 §5 |

---

## 2. 当前代码状态

### 已落地（3 个新文件）

```
src/agent_contract.py    # 工具 schema + 决策契约 + 系统提示词
src/agent_tools.py      # 3 个纯函数工具（query_food_database / get_recent_meals / analyze_with_gemini）+ MIME 检测
src/agent_harness.py    # Luna 主循环（薄 loop）+ 收敛/超时/截断
```

### 已完成的 todo

- ✅ T6（跳过，按体感裁决）
- ✅ 手搓 harness 骨架

### 还在 todo 列表里

- ⬜ 堵 Luna 静默失败洞（**注：实际已部分完成**——`agent_tools.analyze_with_gemini` 已返回 ok/result/error 结构，系统提示词已要求 Luna 用 skip 而非 add 处理"全零/not real food"。但**没在主循环层强制把"Gemini 返回全零"映射为 action=skip**，这是 todo 2 的剩余工作）
- ⬜ session 状态层（待讨论）
- ⬜ pipeline 接入 main.py run
- ⬜ web 增量更新
- ⬜ 前端 agent 交互
- ⬜ 收尾验收（文档 / 隐私说明 / 成本观测）

---

## 3. 架构分层（为 fx 迁移而设计）

```
┌─────────────────────────────────────────────────┐
│  src/agent_harness.py   ← 唯一会变的那层          │  ← 换 fx 时整个删掉
│  Luna 主循环 · tool_calls · 收敛/截断/超时        │
└──────────────────┬──────────────────────────────┘
                   │ 调用
┌──────────────────▼──────────────────────────────┐
│  src/agent_contract.py  ← MCP-ready 契约层       │  ← 换 fx 时原样保留
│  TOOL_SCHEMAS · Decision dataclass · SYSTEM_PROMPT│     (变成 MCP server 的工具定义)
│  parse_decisions_json · validate_decision        │
└──────────────────┬──────────────────────────────┘
                   │ 调用
┌──────────────────▼──────────────────────────────┐
│  src/agent_tools.py  ← MCP-ready 纯函数实现       │  ← 换 fx 时原样保留
│  query_food_database / get_recent_meals /         │     (包 MCP server adapter)
│  analyze_with_gemini / detect_image_mime         │
└─────────────────────────────────────────────────┘
```

工具是 `on_call(args, deps) -> dict` 的纯函数——无 loop 依赖、无传输依赖，**测试和未来 fx 复用都是零成本**。

---

## 4. 配置变更（已落到 `.env` 和 `.env.example`）

```
LUNA_API_KEY=sk-...        # 同一个 openlux 网关，与 Gemini 同源即可
LUNA_BASE_URL=https://api.openlux.ai/v1
LUNA_MODEL=gpt-5.6-luna
```

`CalorieAnalyzer`（现有 Gemini 客户端）保持不变；harness 单独用 OpenAI SDK 连接 LUNA_* 凭据。

---

## 5. 未来迁移到 fx：评估结论

**fx 的 session 机制**：`~/.fx/sessions/` 本地明文 JSON，`fx session last --json` 可机读，可跨机器拷贝。

**对你这套架构的含义**：
- ✅ **业务状态在 SQLite 里**，不依赖 fx 的 session 文件——换 fx 时数据一行不用动
- ⚠️ fx 的**自动 context compaction**（每 8 轮保留最近 4 轮原文）会改变 Luna 看到的上下文。你目前用按需拉起（每次处理一批），compaction 触发概率低；但如果未来加多轮对话，需要重新评估
- 📦 fx 的迁移动作：包 MCP server（~100-200 行）+ 删 harness + 回归测试，约 1-2 天

**结论**：现在这版手搓 harness 是 fx 迁移的**前置奠基**——每一个工具都是 fx 的资产，不是负债。

---

## 6. 决策契约（harness 与 Luna 之间的"宪法"）

### 输入（Luna 收到）
- 一批新照片的 `asset_id` + `photo_time` + 内联图片（base64，按真实 MIME 编码）
- 系统提示词 + 3 个工具 schema（openai function calling 格式）

### 输出（Luna 必须返回的 JSON）
```json
{
  "decisions": [
    {
      "asset_ids": ["<本决策覆盖的新照片 asset_id 列表>"],
      "action": "add | update | skip",
      "target_asset_id": "<已有记录的 asset_id，仅 update 需要>",
      "relation": "new_meal | same_meal | rejected",
      "result": {
        "meal": "...",
        "calories": <数字>, "protein_g": <数字>, "carbs_g": <数字>, "fat_g": <数字>,
        "confidence": "high | medium | low"
      },
      "reasoning": "<判断依据，人工审计>",
      "prompt_for_gemini": "<你传给 Gemini 的辅助提示词>"
    }
  ]
}
```

### 关键规则（写在 SYSTEM_PROMPT 里）
1. 同餐判断**只看图片内容**，不看拍摄时间间隔
2. 一批照片可以产生**多个决策**（同餐的 update + 新餐的 add）
3. 每张新照片必须且只能出现在一个决策的 `asset_ids` 里
4. 一个决策的 `asset_ids` 可以是多张（同餐的多张一起送 Gemini）
5. Gemini 返回全零 / "not real food" 时 → `action=skip`（**这是 todo 2 还要在主循环层强化的兜底**）
6. `reasoning` 字段会被人工审计，必须写清楚逻辑链

---

## 7. 实测验证记录（早期讨论沉淀）

| 测试 | 结果 | 用途 |
|---|---|---|
| T1 openlux 网关接受 `gpt-5.6-luna` | ✅ | 确认模型名可用 |
| T2 单图热量识别 | Luna 1050 vs Gemini 980 vs 人工 850 | Luna 高估 30-45%（不算严重） |
| T3 视觉对比 | 两模型都识别准，Luna medium、Gemini high | 锁定"Gemini 保留为数值专家" |
| T4 data URL 格式严格性 | Luna 缺前缀 → 静默返 0；Gemini 宽容 | **触发了 detect_image_mime 实现** |
| T5a 纯 tool use | ✅ 单轮参数正确、收敛干净 | — |
| T5b 视觉 + 多步 tool use | ✅ 两轮工具链 + 综合结论 + 主动去重判断 | 架构可行性核心证据 |
| T6 三张同餐（你最终按体感裁决通过） | — | — |

**已知边界**：Luna 视觉识别可靠，但**跨图份量推理 / 精细热量估算**是弱项——这是为什么把数值评估完全交给 Gemini 而非 Luna 自评。

---

## 8. 实测中暴露并修复的 P0 问题

修复记录都在 git log 里了（最近几次提交），但**自检时务必复查**——本会话遇到罕见的输出通道故障（"引号后特定字母被截断"），虽然在 base64 绕过后已通过所有验证，**建议你跑一下 `git diff src/agent_*.py` 看看是否有视觉异常**。

修复摘要：
- **P0-1**：`_execute_tool` 的截断会 `json.loads(截断字符串)` 必炸 → 重写为 `_bounded_result()`，优先裁剪列表字段，巨型结果降级为合法 JSON 的 error marker
- **P0-2**：`Decision` 改为多决策列表 + `asset_ids` 覆盖字段，`parse_decision_json` 升级为 `parse_decisions_json`
- **P0-3**：硬编码 `image/jpeg` → `detect_image_mime()` 按 magic bytes 检测 jpeg/png/webp/gif/heic

---

## 9. 下一步（按优先级）

### P0：实际能立刻开工的
1. **复查 git diff**（5 分钟）——验证三个新文件没被输出通道故障污染
2. **端到端 smoke test**：从 Immich 拉 1 张真图，构造 assets + image_getter，跑一次 `AgentHarness.run()`，确认真实环境跑通
3. **session 状态层（todo 3）**：与项目 owner 拍板方案（详见 §10）

### P1：核心路径完善
4. **pipeline 接入 main.py run（todo 4）**：SigLIP2 过滤后改走 harness，而不是 `result = analyzer.analyze(original)`
5. **完成 todo 2 剩余部分**：主循环层强制"Luna 用 skip 处理 Gemini 全零/格式错误返回"
6. **web 增量更新（todo 5）**：复用现有 cache 失效机制

### P2：收尾
7. 前端 agent 交互（todo 6，形态待定）
8. 文档/Hermes 并存/成本观测（todo 7）

---

## 10. 待讨论的关键岔口（todo 3 session 状态层）

落地 harness 到 pipeline 前，需要先决定：

- **session 表结构**：新建 `meal_sessions` + `session_photos` 两张表？还是复用 `records` 扩展字段？
- **"待结算的中间态"怎么记**：Gemini 已经返回了热量但 Luna 还在判断同餐时，临时记录在哪？
- **结算时机**：当前构想是"每张新图进来就增量判断"（你后来确认的方案），无需等全餐结束。这让 session 状态相对简单——主要是**记录每张照片归属哪个决策**，而不是"等齐了三张再结算"
- **跨零点批次**：昨天 23:55 + 今天 00:05 的照片是否合并 session？现有 `get_recent_meals` 按锚定最新照片的日期取，可能丢昨天的中间态
- **孤张超时兜底**：一张照片进了 session 后 LUNA 失败/超时，怎么标记？是否设超时后自动按单张结算？

---

## 11. 关键文件指针

- `src/agent_contract.py` — 契约层（可零改动迁 fx）
- `src/agent_tools.py` — 工具实现（可零改动迁 fx）
- `src/agent_harness.py` — loop（换 fx 时删）
- `src/calorie_analyzer.py` — 现有 Gemini 客户端（被工具层包装调用）
- `src/db.py` — SQLite 数据层（被工具层调用）
- `main.py` 第 164-260 行 — `_run_source` 是 pipeline 接入点（todo 4）
- `docs/agent-native-redesign.md` — 原 Agent-Native 改造方案（互补文档，本计划对齐其 P2 阶段）
- `.env` / `.env.example` — 新增 `LUNA_*` 配置项

---

## 12. 一句话

手搓 harness 已落地且经过严格验证（多决策契约、MIME 检测、安全截断都已修），**业务状态留在 SQLite** 是为将来无痛迁移 fx 埋的伏笔。下一步主要是复查 diff + 跑通 smoke test + 与项目 owner 拍板 session 状态层方案。
