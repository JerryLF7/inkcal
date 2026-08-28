# inkcal · Agent Layer Handoff

> Status: **Agent 批处理已上线；Vue 双 Tab 重构已完成记录侧骨架与聊天后端，当前待接通 Luna 聊天 Pane**（2026-08-28）
> Date: 2026-08-22 起，最后更新 2026-08-28
> Scope: 记录 Luna 批处理层、跨天聊天层，以及以“记录 + Luna”双 Tab 为核心的前端重构决策和实施状态。

---

## 0. 一句话架构

```
SigLIP2 (本地) ──► 新照片批 ──► [Luna 主循环] ──► Decisions (add/update/skip)
                                ├─ tool: get_recent_meals         ── 读 SQLite
                                ├─ tool: query_food_database      ── 读 SQLite
                                └─ tool: analyze_with_gemini      ── 调 Gemini 专家
                          ▲ 失败/越界 ── 降级到旧「单张直送 Gemini」路径（灰度）
```

Luna 是便宜视觉模型（`gpt-5.6-luna`，经海外 VPS 转发到 opencode go），负责**看图、判断同餐、生成辅助提示词**；
Gemini 保留为「数值评估专家」，由 Luna 以工具方式调用。
Harness 失败时回退旧路径，灰度过渡。

---

## 1. 关键决策（拍板过的）

| 决策点 | 决定 | 备注 |
|---|---|---|
| 同餐判断依据 | **仅看图片内容**，不看时间间隔 | 照片 metadata 仅用于排序 |
| 上线策略 | **先灰度** | harness 失败 → 旧路径兜底。已实装：`AGENT_ENABLED=1` 开关 + `AGENT_BATCH_SIZE=6` 分块 |
| 批处理 session | **一次 `harness.run()` 即一次工作上下文** | 不跨批记忆；`agent_decisions.session_date` 只用于审计与照片处理锚点 |
| 聊天 session | **与批处理完全分离，跨天存活** | 默认打开最新 session；支持手动新建与历史切换；日期是工具查询参数，不是会话属性。当前每个 `chat_sessions` 行即一个会话线程，后续多线程需求再引入 `conversation_id` |
| 聊天上下文 | **滑动窗口，无摘要** | 默认 20 轮，可设置 5–50；`previous_response_id` 是缓存，SQLite 是可重建真相源 |
| 聊天权限 | **高权限但可审计** | edit/reanalyze 走已有留痕路径；delete 只生成确认卡片，用户确认后才执行 |
| 前端产品骨架 | **记录 + Luna 双 Tab，左右滑动或底部 Tab 切换** | 设计原型已交付：`docs/prototypes/two-tab-proto.html` |
| 前端技术栈 | **Vue 3 + Vite 全量重构** | Flask 退为 JSON API；旧 `web/static/index.html` 冻结，面向未来开源与 Capacitor 移动端封装 |
| 模型选择 | Luna = `gpt-5.6-luna`；Gemini = `gemini-3.1-pro-preview`（保留） | 配置见 §4；传输层已改走 Responses API（§13） |
| 未来换 fx 的代价 | 工具层 + 契约层 = 0；只换 loop | 详见 §5 |

---

## 2. 当前代码状态

### Agent 批处理已落地

```
src/agent_contract.py    # 工具 schema + 决策契约 + 系统提示词
src/agent_tools.py       # 3 个纯函数工具（query_food_database / get_recent_meals / analyze_with_gemini）+ MIME 检测
src/agent_harness.py     # Luna 主循环（薄 loop）+ 收敛/超时/截断
```

### 聊天后端已落地，等待前端接线

```
src/chat_agent.py        # Responses API 聊天 loop；链失效时从 SQLite 窗口重建
src/agent_contract.py    # CHAT_TOOL_SCHEMAS + CHAT_SYSTEM_PROMPT
src/agent_tools.py       # 查询/统计/搜索/决策查询/edit/reanalyze/delete-confirm 工具
src/db.py                # chat_sessions / chat_messages / app_settings
web/server.py            # /api/chat/*、/api/settings、/api/decisions
```

### Vue 前端已落地的部分

```
web/ui/                  # Vue 3 + Vite 源码；构建产物输出到 web/static/app/
web/ui/src/App.vue       # 双 Pane、底部 Tab、左右滑动、日/周/月切换骨架
web/ui/src/components/   # DayView / WeekView / MonthView / MealCard / MealLightbox
```

记录侧已实现最新在顶的无限时间轴、吸顶日期、周图表与时间轴、月历热量目标圆环、Luna 决策角标和 lightbox 审计展开，并已补回“选择照片”入口（相册选择或本地上传）。右侧 Luna Pane 已按交付原型完成静态视觉骨架，但尚未连接已有聊天 API。

### 已完成的 todo

- ✅ T6（跳过，按体感裁决）
- ✅ 手搓 harness 骨架
- ✅ P0-1 复查 diff（2026-08-22：文件无输出通道故障残留，详见 §13）
- ✅ P0-2 端到端 smoke test（假图 skip 路径 + Immich 真图完整工具链路，见 §13.3）
- ✅ 计划外：harness 移植到 OpenAI Responses API（上游 chat/completions 适配器吞图，§13.2）
- ✅ `.env.example` 重建 + 补 LUNA 配置段
- ✅ **session 状态层**（todo 3）：一张 `agent_decisions` 审计表方案（§14.1）
- ✅ **pipeline 接入**（todo 4）：`_run_source` 攒批 → agent 分块处理 → 失败降级 + 埋点
- ✅ **全零→skip 强制映射**（todo 2 收尾）：`enforce_zero_skip()` 契约层硬保证
- ✅ **跨零点窗口**：get_recent_meals 查 [anchor-1天, anchor]
- ✅ **灰度补跑实战**：8/23-25 积压 51 张，agent 路径零降级（§14.3）
- ✅ **web 增量更新**（todo 5）：`/api/data-version` 指纹 + 前端 30s 可见性感知轮询（§15.1）
- ✅ **跨天同款食物误合并缺陷修复**：same_meal 加时间硬约束 + 工具返回加 date 字段（§15.2）

### 还在 todo 列表里

- ⬜ **Luna 聊天 Pane 接线**：恢复最新 session、历史/新建 session、消息流、发送与失败状态、工具调用状态
- ⬜ **聊天交互 artifact**：复用 `MealCard` 展示查询结果；按 `tool_log` 渲染删除确认卡，并接入真实删除动作
- ⬜ **设置入口**：暴露并保存 `chat_window`（5–50，默认 20）
- ⬜ **主动确认队列**：在记录/聊天 UI 中显示后台待处理确认；保持轮询，不上 WebSocket
- ⬜ 收尾验收：文档同步 / 隐私说明 / 成本观测（todo 7）
- ⬜ 灰度观察期：跑 1-2 周看 `harness_fallback` 比例，稳定后考虑清理旧路径

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
LUNA_API_KEY=sk-...
LUNA_BASE_URL=<VPS 转发地址>/zen/go/v1   # GPT 系大陆不可直连：海外 VPS 转发到 opencode go
LUNA_MODEL=gpt-5.6-luna
```

`.env.example` 里的 `https://api.openlux.ai/v1` 只是占位默认值，实际以 `.env` 为准。

`CalorieAnalyzer`（现有 Gemini 客户端）保持不变；harness 单独用 OpenAI SDK 连接 LUNA_* 凭据（**Responses API**，非 chat/completions，原因见 §13.2）。

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

修复记录都在 git log 里了（2026-08-22 已随 `e982dc2` 提交）。**复查已完成**：三个文件无输出通道故障残留；顺带发现并修复了传输层与参数层的问题（详见 §13）。

修复摘要：
- **P0-1**：`_execute_tool` 的截断会 `json.loads(截断字符串)` 必炸 → 重写为 `_bounded_result()`，优先裁剪列表字段，巨型结果降级为合法 JSON 的 error marker
- **P0-2**：`Decision` 改为多决策列表 + `asset_ids` 覆盖字段，`parse_decision_json` 升级为 `parse_decisions_json`
- **P0-3**：硬编码 `image/jpeg` → `detect_image_mime()` 按 magic bytes 检测 jpeg/png/webp/gif/heic

---

## 9. 下一步（按优先级）

### P0：实际能立刻开工的
1. ~~复查 git diff~~ ✅ 完成（2026-08-22，结论见 §13）
2. ~~端到端 smoke test~~ ✅ 完成（假图 skip + Immich 真图工具链路，见 §13.3）
3. ~~session 状态层方案拍板~~ ✅ 完成（一张审计表方案，见 §14.1）

### P1：核心路径完善
4. ~~pipeline 接入 main.py run~~ ✅ 完成（AGENT_ENABLED 灰度开关，§14.2）
5. ~~完成 todo 2 剩余部分~~ ✅ enforce_zero_skip() 契约层硬保证
6. ~~web 增量更新~~ ✅ 完成（data-version 轮询，§15.1）

### P2：收尾
7. **前端 agent 交互**：§16 的产品与交互模型已经拍板；当前实现焦点是 §18 的 Phase 5 聊天 Pane 接线
8. 文档同步 / 隐私说明 / 成本观测（todo 7）
9. 灰度观察期后清理旧路径（新债）

---

## 10. 岔口裁决记录（todo 3 session 状态层，已全部拍板）

原五个岔口的裁决（详细论证见 §14.1）：

| 岔口 | 裁决 |
|---|---|
| 表结构 | **只建一张 `agent_decisions` 审计表**，不建 meal_sessions/session_photos。业务状态在 `records`，skip 决策的落点由审计表补上 |
| 中间态 | **不需要存储**——"Gemini 已返回但 Luna 还在判断"只存在于一次 API 循环内部 |
| 结算时机 | 每张新图增量判断（维持原拍板），决策返回后顺序应用 |
| 跨零点批次 | `get_recent_meals` 查 **[anchor-1天, anchor]**，提示词声明窗口可能含昨天 |
| 孤张超时兜底 | 不需要新机制：harness 内部超时 + 返回 None 即降级旧路径，无跨轮次滞留；降级时埋 `harness_fallback` 事件 |

关键洞察：**session 的生命周期就是一次 harness.run() 调用**。Luna 对"今天吃过什么"的了解完全来自 get_recent_meals 现查 SQLite，没有跨批次记忆体——所以传统 agent 框架需要持久化的 session 状态在这个架构里不存在。现成 agent（fx/pi）的 session 本质是对话日志，不承载业务状态，替代不了 records/agent_decisions。

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

Agent 层全链路上生产 + web 闲置页面可感知后台写入（todo 5 收官）+ 跨天误合并缺陷已修。剩余：前端 agent 交互（§16 有现成提案）、收尾文档、灰度观察。

---

## 13. 2026-08-22 晚间更新：复查结论 + Responses API 移植

### 13.1 疑点结案

| 事项 | 结论 |
|---|---|
| MIME 硬编码疑点（T4 引发） | **不用改**——"缺前缀会炸"成立，"错前缀"从未复现问题；生产 `calorie_analyzer.py` 同样硬编码多年无症状。移植时顺手用上了 `detect_image_mime()`（新代码路径，白拿正确性） |
| LUNA_BASE_URL 失效 | 是填错了。实际拓扑：大陆 → 海外 VPS 转发 → opencode go（上游名 "Console Go"）。无网关聚合层 |

### 13.2 上游三个怪癖（都已在 harness 内消化）

1. **chat/completions 吞图**：适配器只翻译纯文本，任何图片内容 → 空壳 400（无错误信息）；流式同样失败；`/responses` 原生路径图片正常 → **移植到 `client.responses.create()`**
2. **参数怪癖**：拒收 `max_tokens` 和 `max_completion_tokens`（Responses 的 `max_output_tokens` 可用）；reasoning token 与答案共享该预算，已提到 8192
3. **luna 通道是 Responses 原生**：响应带 `resp_` ID / `phase: final_answer` / `prompt_cache_retention`

移植要点：
- system prompt 走 `instructions` 参数
- **`previous_response_id` 链式调用**：每轮只传增量，多 MB 原图不在工具往返间重复上传
- 工具 schema 在 harness 层做 chat→flat 转换，契约层保持 MCP-ready 不动
- `function_call_output.output` 字段是必填字符串（不是 `content`）

### 13.3 Smoke test 结果（Gemini 为桩函数）

| 用例 | 结果 |
|---|---|
| 假图（红圈 PNG） | ✅ Luna 正确判非食物 → `skip/rejected`，全零 + reasoning 清晰 |
| Immich 真图（麦当劳套餐 2.2MB JPEG） | ✅ 完整工具链路：`get_recent_meals` → `analyze_with_gemini` → 最终决策；prompt_for_gemini 主动排除菜单/小票/包装；发现 asset 已有记录主动选 `update/same_meal` |

真实 Gemini 链路（`_gemini_multi_image`）留待 pipeline 接入时验证。

### 13.4 提交记录

- `e3cf90d` analyzer: extract prompts to src/prompts/（大改前的独立改动）
- `e982dc2` agent: add Luna harness via Responses API with contract/tools layers

---

## 14. 2026-08-26 更新：session 层落地 + pipeline 接入 + cron 修复

### 14.1 session 状态层：一张审计表方案

讨论结论：**session 的生命周期 = 一次 harness.run() 调用**。没有跨批次记忆体，Luna 对"今天吃过什么"的了解完全来自 get_recent_meals 现查 SQLite。由此原五个岔口消解大半，最终只加一张表：

```sql
agent_decisions(id, session_date, run_id, asset_ids JSON, action, relation,
                target_asset_id, result JSON, reasoning, prompt_for_gemini,
                model_used, created_at)
```

配套：`insert_agent_decision()` / `get_decisions_by_date()` / `inkcal decisions [--date] [--json]`。
设计要点：skip 决策在 records 没有落点，审计表是它们唯一的家；records 不动，web UI 零影响。

### 14.2 pipeline 接入与安全网

`_run_source` 重构为攒批模式：

```
SigLIP 过滤 → 攒 food_batch → AGENT_ENABLED?
  ├─ 是 → 按 AGENT_BATCH_SIZE(默认6) 分块调 harness
  │       ├─ 决策成功 → 应用到 records + 写 agent_decisions + agent_decision 事件
  │       ├─ 决策漏照片 → 未覆盖的逐张走旧路径
  │       └─ harness 返回 None → 全部降级旧路径 + harness_fallback 事件
  └─ 否 → 旧路径逐张直送 Gemini（原行为）
```

其他落地项：
- `enforce_zero_skip()`：全零 / not real food → 强制 skip（契约层硬保证，todo 2 清账）
- 跨零点：get_recent_meals 查 [anchor-1天, anchor]
- skip 决策 → `classified_non_food(decided_by='agent')`，与 Gemini 拒绝同语义（相册选择器仍可见）

### 14.3 灰度补跑实战（8/23-25 积压 51 张）

| 日期 | 积压 | SigLIP 放行 | Agent 结果 |
|---|---|---|---|
| 8/23 | 19 | 1 | skip：毛绒玩具——**SigLIP 误报被 Luna 低成本拦截** |
| 8/24 | 27 | 0 | 无需调用 |
| 8/25 | 5 | 2 | add 煮饺子 720kcal ＋ skip 社交截图 |

- **harness_fallback = 0 次**
- 多决策契约首次实战（一批 → add+skip）；reasoning 明确引用了 get_recent_meals 的比对结果
- 用户手动录入的记录未被重复处理（幂等正常）
- 生产已切 `AGENT_ENABLED=1`

### 14.4 计划外：cron 三天静默故障的根因与修复

8/22 18:45 机器重启后 cron 每 10 分钟照常触发但全部卡死：重启丢失了到 huggingface.co 的路由，transformers 加载检测器时的联网更新检查无限重试。8/23-25 事件表归零、51 张积压（部分照片经 web 手动路径入库，造成"有记录无事件"的假象）。

修复：`src/food_detector.py` 模块加载时强制 `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1`——模型缓存本地齐全，从此 pipeline 不依赖 HF 可达性。

### 14.5 提交记录

- `efd7458` agent: integrate Luna batch path into pipeline with decision audit
- `42008c2` detector: force HuggingFace offline mode

---

## 15. 2026-08-26 更新×2：web 轮询 + 跨天误合并修复

### 15.1 web 增量更新（todo 5 收官）

缺口：day/week/dates 都有"导航时自愈"，但页面闲置时感知不到 cron 的后台写入。

方案：数据版本指纹 + 30s 可见性感知轮询
- `db.get_data_version()`：`记录数:max(created_at):max(updated_at):max(reanalyzed_at)`，增/删/改/重评都会变（秒级精度足够——中间态无需观测）
- `GET /api/data-version`（自动受现有登录保护）
- 前端每 30s 轮询（`document.visibilityState !== 'visible'` 时跳过）；版本变化 → 重载当前 day/week 视图 + 强刷日历圆点

提交：`af31867`

### 15.2 跨天同款食物误合并缺陷（owner 复审 reasoning 时发现）

**现象**：8/25 饺子批次的 reasoning 拿 8/24 的炒面做对比依据——跨零点窗口 `[anchor-1天, anchor]` 让隔天记录进入了上下文，但提示词没教 Luna 如何对待它们；且原规则"同餐只看图片、不看时间"被错误泛化到跨天场景。

**风险推演**：连续两天中午吃同款食物 → Luna 判 same_meal/update → 今天的饭被合并进昨天的记录。

**修复**：
1. 系统提示词：把"不看时间"的管辖权收回到**批内分组**；对已有记录判 same_meal 时时间是硬约束——昨日记录只服务跨零点连续进食，正常时段跨天同款一律 add
2. 工具描述删除"与日期无关"的误导表述
3. `get_recent_meals` 每条记录新增显式 `date` 字段

**回归验证**：真实饺子照片 + 伪造"昨天中午饺子"记录 + 真实 Luna 调用 → `add/new_meal` ✅，reasoning 主动引用规则原文。提交：`6814299`

---

## 16. 前端重构：已确认的产品与交互模型

原型已交付于 [two-tab-proto.html](./prototypes/two-tab-proto.html)。它是视觉与信息架构的设计依据，不应被当作下一轮需要重画的需求。

### 16.1 产品定位

前端不再只是 records 的展示器，而是用户对 Luna 的**浏览界面、监督界面与双向交互界面**。记录浏览与 Agent 对话是平级能力：不能把 Luna 降级为记录页上的一个弹层，也不把时间轴降级为聊天的附属页面。

### 16.2 全局导航

- 全局只有 `记录` 与 `Luna` 两个 Tab。
- 手机端同时支持底部 Tab 点击与水平滑动切换；底部 Tab 常驻，避免占用记录页的顶部信息密度。
- 默认首页尚未拍板；实现时不得假设必然落在记录或 Luna。

### 16.3 记录 Tab

| 视图 | 职责与交互 |
|---|---|
| 日 | 最新记录在顶部；向下无限加载更早日期；日期分隔线与吸顶日期头维持时间定位；餐卡点开进入图片与详情 lightbox |
| 周 | 保留热量柱状图 + 按日期组织的餐食时间轴；用于快速扫一周摄入，而非取代日浏览 |
| 月 | 日历即快速跳转器；日期只显示热量占每日目标的进度圆环，不显示总热量数字；点日期切回日时间轴并定位 |

日/周/月通过记录页顶栏右侧分段控件切换。现有的 `MealCard`、图片 lightbox、上传/相册能力与日期数据模型是可复用材料；旧版单页布局、以日历为主导航和旧 tab 结构不再是设计约束。

Agent 决策透明度保留在记录原位：已实现餐卡 🤖 标识和 lightbox 的“AI 决策”折叠区。**不在时间轴展示被 SigLIP2 或 Luna 判为非食物的 skip 照片**；`/api/skipped` 可保留为未来纠错接口，但不驱动一期记录 UI。聊天传图与同餐分组缩略图可视化也不属于一期。

### 16.4 Luna Tab

- 顶栏显示 Luna，并提供“历史 session”与“新建 session”图标入口。
- 进入时恢复最近 session；新建只创建新的对话上下文，不影响批处理 run 或 records。
- 对话消息可包含普通文本、餐记录 artifact、统计/解释结果、工具执行状态与删除确认卡。
- 输入栏旁保留 `+` 入口，为未来相册/本地上传或聊天传图预留；一期聊天只处理文本。
- 用户可自然语言查询饮食、比较摄入、要求修改或重新分析；不是只读问答。
- 删除必须以确认卡片完成，不由模型直接删库。确认后的 HTTP 动作复用现有 `DELETE /api/record`，确保忽略列表等副作用一致。

### 16.5 会话、缓存与主动性

批处理 run 和聊天 session 是不同概念：前者是短命照片决策上下文，后者是用户可跨天延续或手动新建的对话流。聊天每轮通过 `previous_response_id` 追加增量，利用上游 prompt cache；链过期、上游重启或转发失败时，按 `chat_window` 从 SQLite 重放最近消息并建立新链。

聊天窗口默认 20 轮、可调 5–50；不做摘要压缩。工具查询的业务事实始终从 SQLite 现查，因此窗口滑动只会软化语言上下文，不会令历史饮食事实不可访问。

主动确认不引入 WebSocket：沿用 `/api/data-version` 轮询，在响应中附带 pending 数量；聊天输出将优先尝试 SSE，若转发层不支持则退化为非流式响应并展示工具执行进度。

---

## 17. 2026-08-27 更新：午餐实测暴露两个缺陷（已修复）+ 缓存实测

### 17.1 缺陷 A：Luna 决策 JSON 多余尾括号（契约层）

**现象**：用 8/26 两张午餐真图（11:35/11:48 同一份外卖盒饭前后状态）重跑 harness，loop 12 步全部报 "invalid JSON"，降级旧路径。
**根因**：抓原文发现 JSON **完整有效**，但 Luna 在较长决策上稳定追加多余尾部 `]}`（如 `..."}]}]}`）。`parse_decisions_json` 只容忍"缺尾"（补 `}`），不容忍"多尾"。
**修复**：`raw_decode` 解析首个完整 JSON 值，残余经纯括号字符校验后忽略；真垃圾（如尾随 SQL）仍拒绝。回归测试 `scripts/test_contract_parse.py`（含 642 字符真实捕获用例）。

### 17.2 缺陷 B：Gemini 被长指令带成 markdown 散文（工具层）

**现象**：同上实测，3 次运行中 2 次 Gemini 返回 markdown 分析报告而非契约 JSON，解析失败退化为 unknown/全零。
**根因**：`_gemini_multi_image` 把 Luna 的 `prompt_for_gemini` 原样单发，全文无格式约束；`response_format=json_object` 在该网关上约束不住。长指令（"对比前后状态估算实际食用量…"）诱导散文输出。
**修复**：prompt 末尾追加硬性格式锚点（字段契约 + 只返回 JSON），贴近生成位置。

### 17.3 修复后验证（同批午餐照片）

3 步收敛：get_recent_meals → 两图同送 Gemini（720kcal，按"实际吃掉的部分"估算）→ `update/same_meal` 合并进 11:35 记录。对比：旧路径把同顿记成 450+970=1420kcal 两条独立记录——**同餐合并的核心价值第一次完整跑通**。

### 17.4 prompt cache 实测（聊天功能的成本前提）

- 小前缀（~1400 tok 系统提示+工具）：第 2/3 轮命中 98.3%/98.4%（`scripts/test_luna_cache.py`）
- 真实负载（两张 2MB 原图 + 工具往返）：`in=31050 cached=31047`，**99.99%**
- 结论：`previous_response_id` 链式 + prompt cache 在当前转发通道实测可用，对话场景的 token 成本问题关闭

---

## 18. 2026-08-27–28 拍板与实施状态：前端重构 + Agent 双向交互

讨论结论与当前代码状态：

| 决策点 | 结论 |
|---|---|
| 前端定位 | 从“展示”转为“人对 agent 的监督台 + 双向对话”（纠错、主动推送、饮食问答） |
| 前端技术栈 | **全量重构：Vue 3 + Vite**，Flask 退为纯 API 层；考虑开源发布与后续 Capacitor 移动端封装。旧 `index.html` 冻结，新 UI 只进新前端 |
| 对话 vs 批处理 session | **分离**。批处理 run 不动；对话 session 跨天，日期降级为工具参数（锚点=消息发出时刻） |
| session 组织 | 单流 + 手动新建/历史 session 图标，默认开最新；当前每个 `chat_sessions` 行是一个会话线程，未来并行话题确有需求时再增加 `conversation_id` |
| 上下文窗口 | 滑动窗口无摘要，默认 20 轮，设置页可调（5-50）；有工具在，“失忆”是软性的，事实永远现查 SQLite |
| 聊天权限 | **高权限**（非只读）：写工具全走现有审计路径（edit 留痕 / reanalyze 写历史）；delete 等破坏性动作出确认卡片，点了才执行 |
| 推送通道 | 不上 WebSocket：data-version 轮询携带 pending 确认数；聊天流式走 SSE（转发层不支持则降级非流式+工具进度事件） |
| 一期不做 | 聊天传图、同餐分组可视化、时间轴展示 skip 照片 |

实施进度：

| Phase | 状态 | 交付 |
|---|---|---|
| 0：批处理稳定性与缓存验证 | ✅ | JSON 尾括号容错、Gemini JSON 格式锚点、真实午餐双图验证、prompt cache 实测 |
| 1：监督 API | ✅ | `/api/decisions`、`/api/skipped`、`/api/data-version` |
| 2：聊天后端 | ✅ | 聊天表、聊天工具、`ChatAgent`、`/api/chat/*`、`/api/settings`、断链 SQLite 重建 |
| 3：Vue 骨架与记录浏览 | ✅ | 双 Pane / 底部 Tab / 手势、Luna 静态原型骨架、日无限时间轴、周/月视图、相册/本地上传入口、构建产物发布 |
| 4：记录侧监督 UI | ✅（一期范围） | 🤖 角标 + lightbox AI 决策折叠；skip UI 按已拍板范围不做 |
| 5：Luna 聊天面板 | ⬜ | 当前右 Pane 是占位；需连接 session、消息、发送、artifact、确认卡与设置 |
| 6：迁移切换与回归 | ⬜ | 旧静态 UI 冻结；待新 UI 的聊天主路径完成后切换并回归上传、认证、图片代理等能力 |
| 7：主动确认队列 | ⬜ | pending 计数、确认卡、轮询/SSE 降级策略 |

测试脚本资产：`scripts/test_luna_cache.py`（缓存复测）、`scripts/test_luna_lunch.py`（真实双图链路）、`scripts/test_contract_parse.py`（契约回归）。
