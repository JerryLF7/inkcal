# inkcal · Agent Layer Handoff

> Status: **已接入 pipeline 生产运行（AGENT_ENABLED=1 灰度）**（2026-08-26 更新×2：web 增量轮询上线；跨天同款食物误合并缺陷已修——见 §15）
> Date: 2026-08-22 · 08-26 三次更新
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

Luna 是便宜视觉模型（`gpt-5.6-luna`，经海外 VPS 转发到 opencode go），负责**看图、判断同餐、生成辅助提示词**；
Gemini 保留为「数值评估专家」，由 Luna 以工具方式调用。
Harness 失败时回退旧路径，灰度过渡。

---

## 1. 关键决策（拍板过的）

| 决策点 | 决定 | 备注 |
|---|---|---|
| 同餐判断依据 | **仅看图片内容**，不看时间间隔 | 照片 metadata 仅用于排序 |
| 上线策略 | **先灰度** | harness 失败 → 旧路径兜底。已实装：`AGENT_ENABLED=1` 开关 + `AGENT_BATCH_SIZE=6` 分块 |
| 每天一个 session | 是 | **已落地为"session = 一次 harness.run()"**——无长命 session，状态全在 SQLite（§14.1） |
| 前端 agent 交互 | 暂缓 | 形态以后单独聊（todo 6） |
| 模型选择 | Luna = `gpt-5.6-luna`；Gemini = `gemini-3.1-pro-preview`（保留） | 配置见 §4；传输层已改走 Responses API（§13） |
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

- ⬜ 前端 agent 交互（todo 6）——**分层提案与待拍板问题见 §16，下个 session 从这里继续**
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
7. **前端 agent 交互（todo 6）← 下个 session 的主题，提案见 §16**
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

## 16. todo 6 前端 agent 交互——待讨论提案（下个 session 从这里开始）

### 可用数据（agent_decisions 表）
reasoning / asset_ids 分组 / action+relation / prompt_for_gemini / result

### 现状缺口
1. 用户不知道记录是 agent 记的、凭什么记的
2. **skip 的照片完全隐身**（Luna 拒绝的东西无法被发现，误判无纠错入口）
3. update 合并发生后用户不知道"这餐为什么变了"

### 分层提案（已抛出，未拍板）
| 层 | 内容 | 备注 |
|---|---|---|
| 一 | 餐卡 🤖 角标 + lightbox"AI 决策"区块（reasoning 全文 + relation） | 需要 `GET /api/decisions?date=` 端点（CLI 已有对应实现可搬） |
| 二 | 同餐分组可视化："由 N 张合并判定"+ 参与照片缩略图 | UI 复杂度最高、日常价值最低 |
| 三 | skip 透明化：day view 底部折叠条"已过滤 N 张非食物"+ 每条"误判？"按钮走 album picker 强制分析 | 纠错回路，机制现成 |

### 待拍板问题
1. **做到第几层？** 助手建议一期做 1+3，二层缓
2. **移动端交互优先级？** 手机为主的话弹层/折叠条按底部抽屉设计而非 hover
