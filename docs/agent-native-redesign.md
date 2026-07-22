# inkcal Agent-Native 改造方案

> 版本：v1.0 · 2026-07-22
> 目标读者：Jerry（项目作者），以及执行改造的 coding agent
> 适用范围：`~/Coding/inkcal/`，基于 commit `f92be95` 的代码现状

---

## 0. TL;DR

inkcal 目前给 agent 的接口是一套**为人类终端设计的 CLI**（argparse 子命令 + ASCII 表格 + emoji），agent 被迫扮演"自然语言 → argparse 翻译器"。这是交互"僵硬"的根因。

本方案的核心思路：**把 agent 从"软件的用户"升级为"软件的运行时"**——

```
现在：  用户 ↔ agent ↔ CLI（人类接口） ↔ 系统
目标：  用户 ↔ agent ↔ 结构化原语 + 事件流 ↔ 系统
```

`src/db.py` 里其实**已经存在**绝大多数需要的原语（`update_record`、`delete_record`、`move_record`、`get_records_by_date_range`、`summarize_records`……），只是 CLI 没有暴露。所以改造的主体不是新写功能，而是**重新设计暴露层**，工作量比看起来小得多。

---

## 1. 诊断：僵硬感的四层根因

### 1.1 命令是"工作流级"，不是"原语级"

现有 7 个子命令（`run / view / add / search / label / replace / migrate`）每个都是一段预先编排好的剧本。agent 只能触发剧本，不能组合。

**实证**：`cmd_view` 里 `--week` 写死为本周一至今（`monday = today - timedelta(days=today.weekday())`）。用户问"上周蛋白质够吗"，agent 只能循环调 7 次 `view --date`，再自己解析 ASCII 表格心算求和。而 `db.get_records_by_date_range()` 和 `db.summarize_records()` **早就存在**，只是没有命令暴露。

### 1.2 输出给人眼看，不给模型用

- 没有任何 `--json` 模式；所有读命令输出 box-drawing 表格 + emoji。
- `cmd_search` 打印的表格**不包含 asset_id**——导致"搜到红烧肉 → 标注/修改这条记录"这条最自然的路径在 CLI 层面**走不通**（search 拿不到 ID，label 只认 ID）。
- agent 拿到输出后无法可靠推理，只能复读——这是"僵硬感"最直接的来源：回复格式永远长一个样。

### 1.3 能力边界是个任意子集

对比两个入口的能力集：

| 能力 | Web UI | CLI |
|---|---|---|
| 查看记录 | ✅ | ✅ |
| 手动记录 | ✅ | ✅ |
| 标注 correct/wrong | ✅ | ✅ |
| 重新分析（补充细节） | ✅ | ❌ |
| **直接修改热量/宏量** | ❌ | ❌（**两个入口都没有**） |
| 移动记录日期 | ✅ (`/api/move-record`) | ❌ |
| 查看为何照片被跳过 | ❌ | ❌（`classified_non_food` 表无入口） |

用户说"那顿其实是两人份，算一半"，agent 唯一能说的是"请去 web 上操作"——每一次撞墙，"强行接入"的感觉就出现一次。

### 1.4 业务规则写在文档里，agent 被当策略解释器

`SKILL.md` 里的估算规则表、cron 假阳性缓存策略、JSON 修复逻辑——这些本该是代码的东西以散文形式写给 agent 读。软件做不到的事被外包给了 LLM 的服从性：换 agent、换 session，行为就漂移。**文档越厚，说明软件能做的越少。**

### 1.5 自测标准

> 如果 hermes 不可用、你手敲 CLI 的体验，和通过 agent 对话的体验**几乎一样**，说明 agent 没带来任何增量能力，它只是一层翻译皮。当存在"只有 agent 能做、人敲命令做不了"的交互时（模糊指代、跨范围聚合、主动提醒），僵硬感才会消失。

---

## 2. 设计原则

改造遵循五条原则，按优先级排序：

1. **机器可读优先**：一切读操作有结构化输出（JSON）；人类可读格式是 JSON 的渲染，不是唯一形态。
2. **原语可组合**：接口暴露细粒度原语（查/改/聚合/解释），不预设工作流；组合是 agent 的事。
3. **指代可解析**：对话中的"昨天那顿红烧肉""最后一条"必须能不经过 ID 对账直接定位到记录。
4. **决策可追溯**：系统对每张照片做了什么决定（已记录 / 分类器否决 / Gemini 否决 / 用户忽略 / 未处理），必须可查询、可解释。
5. **确定性规则代码化**：SKILL.md 只保留工具清单与分工说明；凡是 if-else 能表达的规则，全部下沉进代码。

---

## 3. 改造项明细

优先级：P0 = 本周就做，立刻消除最疼的撞墙点；P1 = 第二轮，解锁组合能力；P2 = 第三轮，从"不僵硬"到"活"。

---

### P0-1 全量 `--json` 输出

**现状**：所有读命令输出 ASCII 表格；`search` 结果不含 `asset_id`。

**方案**：

- `view / search / label --list / label --status` 全部支持 `--json`。
- JSON 模式直接返回 `db.py` 的 dict 结构（`_record_from_row` 的输出），**必须含完整 `asset_id`**、`confidence`、`user_label`、`reanalysis_history`。
- 人类表格保持不变，默认输出不变，不影响 cron 和现有习惯。

```bash
inkcal view --date 2026-07-20 --json
inkcal search 红烧肉 --json
```

输出形态：

```json
{
  "ok": true,
  "command": "view",
  "range": {"from": "2026-07-20", "to": "2026-07-20"},
  "records": [
    {
      "id": 42,
      "asset_id": "manual-20260720123000000000",
      "meal": "红烧肉",
      "calories": 600, "protein_g": 25, "carbs_g": 30, "fat_g": 20,
      "confidence": "medium",
      "photo_time": "2026-07-20T12:30:00+08:00",
      "user_label": null,
      "reanalysis_history": []
    }
  ],
  "summary": {"meals": 1, "calories": 600, "protein": 25, "carbs": 30, "fat": 20}
}
```

**涉及代码**：`main.py` 的 `cmd_view / cmd_search / cmd_label`；新增一个 `_emit(data, args)` helper（`--json` 时 `json.dumps`，否则走现有表格）。`db.summarize_records()` 直接复用。

**验收**：agent 能用一次 `search --json` 拿到 asset_id 并完成后续 `label`，全程不需要解析任何表格。

---

### P0-2 `inkcal edit`：直接修改记录

**现状**：两个入口都无法修改一条记录的热量/宏量/餐名。`db.update_record()` 已实现但无命令暴露。

**方案**：

```bash
inkcal edit --id 3f9a2c --calories 300 --note "两人份，减半"
inkcal edit --id 3f9a2c --meal "红烧肉（小份）" --protein 30
inkcal edit --id 3f9a2c --date 2026-07-19 --time 21:40   # 改时间，内部走 db.move_record
```

要点：

- 可改字段：`meal / calories / protein / carbs / fat / confidence / date / time`。
- **修改前自动把旧值写入 `reanalysis_history`**（`db.append_reanalysis_history()`，notes 填 `--note` 或 `"manual edit"`），保证可追溯、可回滚——复用现有历史表，零 schema 变更。
- 编辑后 `confidence` 默认为 `high`（人工修正 > 模型估计），除非显式指定。
- 输出修改前后的 diff；`--json` 返回完整新记录。

**涉及代码**：`main.py` 新增 `cmd_edit`（约 60 行，纯调用 `db.update_record` / `db.append_reanalysis_history` / `db.move_record`）。

**验收**：对话"昨晚那顿是两人份，热量减半"→ agent 一条命令完成，且 `reanalysis_history` 里留有旧值。

---

### P0-3 `inkcal explain`：决策可追溯

**现状**：照片被跳过的原因散落在三张表（`records` / `classified_non_food` / `ignored_assets`）和日志里，无任何查询入口。用户问"中午那张照片怎么没记上"，agent 只能猜。

**方案**：

```bash
inkcal explain --id <asset前缀>          # 单张照片的去向
inkcal explain --date 2026-07-20         # 当日所有照片的状态清单
```

单张输出（五态之一 + 证据）：

```json
{
  "asset_id": "3f9a2c...",
  "status": "classified_non_food",
  "detail": {
    "decided_by": "siglip2_local",
    "classified_at": "2026-07-20 12:05:33",
    "hint": "本地分类器判定非食物。若为漏判，可用 inkcal analyze --id 强制送 Gemini"
  }
}
```

五态定义：

| 状态 | 判定依据 | 含义 |
|---|---|---|
| `recorded` | 在 `records` 表 | 已分析入库，附 record 摘要 |
| `classified_non_food` | 在 `classified_non_food` 表 | 本地分类器否决（可纠正） |
| `gemini_rejected` | 在 `classified_non_food` 且曾被送 Gemini（见下方 schema 补充） | Gemini 判定非真实食物 |
| `ignored` | 在 `ignored_assets` 表 | 用户删除/强忽略 |
| `unprocessed` | 都不在 | 待处理（cron 下一轮会跑） |

**Schema 补充**（一次性迁移）：给 `classified_non_food` 加一列区分否决方——

```sql
ALTER TABLE classified_non_food ADD COLUMN decided_by TEXT NOT NULL DEFAULT 'siglip2';
-- 取值：'siglip2' | 'gemini'
```

`main.py` 里 Gemini 拒绝时写 `decided_by='gemini'`。旧数据默认 `'siglip2'` 即可。

**涉及代码**：`src/db.py`（schema 迁移 + `explain_asset(asset_id) -> dict`）；`main.py` 新增 `cmd_explain`。`--date` 模式需要向 Immich/PhotoPrism 拉当日 asset 列表再逐一对账（复用 `_run_source` 里的 client 逻辑，去掉下载和分析）。

**验收**：用户问"为什么没记上"，agent 能给出确定答案和下一步建议，而不是"可能是分类器没认出来"。

---

### P1-4 统一指代解析层（Record Resolver）

**现状**：`label / replace` 只认 asset_id 前缀；agent 被迫做"list → 找 8 位前缀 → 再执行"的两步对账，ID 这个数据库概念泄漏进了对话。

**方案**：新增 `src/resolver.py`，所有需要定位记录的命令（`edit / label / replace / explain / analyze / delete`）共用它。支持四种指代，按优先级解析：

```bash
inkcal edit --id 3f9a2c ...              # 1. asset_id 前缀（现有行为）
inkcal edit --ref 42 ...                 # 2. records.id 自增序号（最短，JSON 输出里带）
inkcal edit --last ...                   # 3. 最近一条记录
inkcal edit --meal 红烧肉 --date 昨天 ...  # 4. 关键词 + 日期模糊定位
```

解析规则：

- `--meal` 走现有 `db.search_records()`（FTS5 + LIKE fallback），按 `photo_time` 倒序取候选。
- **候选唯一** → 直接执行；**多个候选** → 不执行，返回候选清单让 agent 追问用户：

```json
{
  "ok": false,
  "error": "ambiguous",
  "candidates": [
    {"id": 42, "meal": "红烧肉", "photo_time": "2026-07-20T12:30:00+08:00", "calories": 600},
    {"id": 31, "meal": "红烧肉盖饭", "photo_time": "2026-07-13T19:02:11+08:00", "calories": 720}
  ]
}
```

- 零候选 → 返回 `"error": "not_found"`。
- 日期词（昨天/前天/上周X）由 agent 换算成 `YYYY-MM-DD` 传入，resolver 本身不解析自然语言——**职责分界：语言理解归 agent，确定性解析归代码**。

**涉及代码**：新增 `src/resolver.py`（约 80 行）；`main.py` 各命令的 `--id` 参数替换为统一 `--id/--ref/--last/--meal` 参数组。

**验收**：对话"把昨天红烧肉那条标成有误"→ agent 一次调用完成，全程无 ID 出现。

---

### P1-5 `inkcal stats`：任意范围聚合

**现状**：`--week` 写死本周；无跨范围聚合；agent 回答"最近十天""上周""这个月和上个月比"都极其痛苦。

**方案**：

```bash
inkcal stats --from 2026-07-08 --to 2026-07-14
inkcal stats --last 7d          # 便捷写法：7d / 2w / 1m
inkcal stats --from ... --to ... --group-by day   # 按天分解
```

JSON 输出：

```json
{
  "ok": true,
  "range": {"from": "2026-07-08", "to": "2026-07-14"},
  "totals": {"meals": 15, "calories": 12300, "protein": 620, "carbs": 1100, "fat": 430},
  "daily_averages": {"calories": 1757, "protein": 88.6, "carbs": 157.1, "fat": 61.4},
  "days_with_records": 7,
  "by_day": [
    {"date": "2026-07-08", "meals": 2, "calories": 1800, "protein": 90, "carbs": 160, "fat": 62}
  ]
}
```

**涉及代码**：纯组合现有原语——`db.get_records_by_date_range()` + `db.summarize_records()` + 按天分桶。`cmd_stats` 约 50 行。人类格式复用现有 `✅/⚠️` 合计样式。

注意：**聚合数字必须由代码算**（deterministic），不让 agent 对着明细口算——这是消除幻觉的关键边界。

**验收**："上周平均每天摄入多少蛋白"→ agent 一次调用拿到精确数字。

---

### P1-6 `inkcal analyze` / `inkcal reanalyze`：把分析能力从 web 抽回共享层

**现状**："从相册选照片直送 Gemini"和"补充细节重新分析"只在 web 端实现（`/api/analyze-album-photo`、lightbox reanalyze）。CLI 端完全没有，agent 撞墙。

**方案**：

1. 把 `web/server.py` 里这两个端点的核心逻辑**下沉到 `src/`**：新增 `src/pipeline_ops.py`，暴露 `analyze_asset(asset_id)`（跳过分类器直送 Gemini）和 `reanalyze_record(asset_id, notes)`（带补充说明重新估算）。web 端点改为调用它，**行为不变**。
2. CLI 新增：

```bash
inkcal analyze --id <asset前缀>              # 分类器漏判的照片，强制分析
inkcal reanalyze --ref 42 --notes "两人份，另有一碗米饭"
```

- `analyze` 成功后自动 `db.remove_classified_non_food(asset_id)`（保持状态一致，SKILL.md 里这条规则随之代码化）。
- `reanalyze` 沿用现有逻辑：旧值进 `reanalysis_history`，notes 记录用户补充。

**涉及代码**：`web/server.py` 重构（提取函数，端点变薄）；新增 `src/pipeline_ops.py`；`main.py` 两个新命令。

**验收**：web 端回归无变化；agent 可在对话里完成"这张漏了 → 强制分析"和"算少了 → 补充细节重算"两个完整闭环。

---

### P1-7 结构化错误与退出码

**现状**：错误是给人看的中文字符串（`❌ 未找到匹配记录`），退出码几乎全是 0/1。agent 无法区分"没找到"和"有多个"和"外部服务挂了"，恢复策略只能靠猜。

**方案**：

- `--json` 模式下，一切失败返回 `{"ok": false, "error": "<code>", "message": "...", ...}`，机器读 `error`，人读 `message`。
- 错误码枚举：

| code | 含义 | 退出码 | agent 的恢复动作 |
|---|---|---|---|
| `not_found` | 记录/asset 不存在 | 2 | 换指代重试或告知用户 |
| `ambiguous` | 指代命中多条 | 3 | 附 candidates，追问用户 |
| `invalid_args` | 参数错误 | 64 | 自己修正 |
| `external_error` | Immich/Gemini 不可达 | 69 | 告知用户服务状态 |
| `not_food` | Gemini 判定非食物 | 4 | 询问是否强制记录 |

**涉及代码**：`main.py` 统一 `fail(code, message, **extra)` helper；各命令替换现有 `print + sys.exit(1)`。

---

### P2-8 Pipeline 事件流（Outbox）

**现状**：cron 每 10–20 分钟盲跑，agent 对"系统刚刚发生了什么"一无所知。交互永远是用户发起的问答——这是"活"与"僵硬"的分水岭。

**方案**：新增 `pipeline_events` 表，pipeline 每次运行把值得知道的事写进去：

```sql
CREATE TABLE IF NOT EXISTS pipeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    run_id TEXT NOT NULL,               -- 一次 inkcal run 的 UUID
    event_type TEXT NOT NULL,           -- 见下
    asset_id TEXT,
    payload TEXT,                       -- JSON 细节
    consumed INTEGER NOT NULL DEFAULT 0 -- agent 读取后置 1
);
```

事件类型：

| event_type | 触发时机 | payload 示例 |
|---|---|---|
| `meal_recorded` | 新记录入库 | `{"meal": "...", "calories": 600}` |
| `low_confidence` | Gemini 返回 confidence=low | `{"meal": "...", "record_id": 42}` |
| `gemini_rejected` | Gemini 判非食物 | `{"asset_id": "..."}` |
| `classifier_unsure` | SigLIP2 分数在阈值灰区（如 0.4–0.6） | `{"score": 0.52}` |
| `run_summary` | 一次 run 结束 | `{"photos": 12, "recorded": 1, "skipped": 11}` |

配套命令：

```bash
inkcal events                # 拉取未消费事件并标记已消费
inkcal events --all --last 3d
```

**agent 侧用法**：hermes 每次会话开始先 `inkcal events`，有料就主动开口——"中午识别了两餐，其中咖喱那顿 confidence 是 low，要不要我看一眼照片？"；没料就不提。这把交互从纯 pull 变成 push+pull，**是"只有 agent 能做"的第一类交互**。

注意灰区检测需要 `food_detector.py` 暴露分数（现在 `is_food()` 只返回 bool；改成 `score()` 返回 float，`is_food` 调它）。

**涉及代码**：`src/db.py`（新表 + `add_event / get_unconsumed_events / mark_consumed`）；`main.py`（pipeline 写事件 + `cmd_events`）；`src/food_detector.py`（暴露 score）。

---

### P2-9 规则下沉与 SKILL.md 瘦身

把 SKILL.md 里"if-else 能表达"的规则逐条代码化，文档只留分工说明：

| 现 SKILL.md 内容 | 去向 |
|---|---|
| cron 假阳性双缓存策略 | 已在代码（本方案 P0-3 补 `decided_by` 列后完全闭环），SKILL.md 删 |
| Gemini JSON 修复逻辑描述 | 已在 `calorie_analyzer.py`，SKILL.md 删（留一行指向代码） |
| "mutation 后用 view 验证" | 改为：`add/edit` 命令**默认输出新记录 JSON**，无需二次验证 |
| 默认日期 HKT、`--confidence` 取值 | 代码已是默认值，删 |
| 热量估算规则表（具体食物→取中位、模糊→追问……） | **保留**，但改写为明确分工：「热量估算需要常识判断，由 agent 负责；系统提供 `inkcal estimate --meal "..."`（可选，调 Gemini 文本估算）作为兜底」 |
| Web 服务生命周期、FRP 部署细节 | 移到 `DEVELOPMENT.md`，SKILL.md 不背运维知识 |

瘦身后的 SKILL.md 目标：**一页以内**，结构 = 何时用 → 命令速查（一屏表格）→ 指代规则 → 错误码 → 估算分工。判断标准：删掉任何一条，agent 行为不应该漂移——因为漂移空间已经被代码消除了。

---

### P2-10（远期）MCP Server 形态

CLI + `--json` 是改造的地板；MCP 是天花板。当 P0/P1 落地后，`src/` 已经有干净的原语层，包一层 MCP server 是一两天的事：

```
inkcal_log_meal(meal, calories, macros?, date?, time?, confidence)
inkcal_get_records(range) / inkcal_stats(range, group_by?)
inkcal_update_record(ref, fields, note?)      # resolver 内建
inkcal_explain_asset(asset_id)
inkcal_reanalyze(ref, notes)
inkcal_get_events() / inkcal_label(ref, label)
```

届时 hermes / Claude 直连 MCP，跳过 shell 和文本解析，错误语义用 MCP 原生 error 表达。**建议路径**：先 CLI 原语化（P0–P1），验证设计稳定后再包 MCP，避免同时改两层。

---

## 4. 改造后 CLI 全景

```
数据写入
  inkcal add --meal M --calories N [--protein --carbs --fat --date --time --confidence] [--json]
  inkcal edit (--id P | --ref N | --last | --meal K [--date D]) [--meal --calories ... --date --time] [--note S] [--json]
  inkcal delete (--id P | --ref N | --last | --meal K) [--json]
  inkcal analyze --id P                       # 强制送 Gemini（纠分类器漏判）
  inkcal reanalyze (定位参数) --notes S        # 补充细节重新估算

数据读取
  inkcal view [--date D | --from F --to T] [--json]
  inkcal stats [--from F --to T | --last 7d] [--group-by day] [--json]
  inkcal search KEYWORD [--from --to] [--json]   # 输出含 asset_id / id

记录定位（所有写命令共用 resolver）
  --id <asset前缀> | --ref <records.id> | --last | --meal <关键词> [--date D]
  唯一 → 执行；多候选 → error=ambiguous + candidates；零 → error=not_found

标注与维护
  inkcal label (定位参数) --label correct|wrong
  inkcal label --list [--date] [--json] / --status [--json]
  inkcal replace (定位参数) --image PATH

流水线可观测
  inkcal explain (--id P | --date D) [--json]   # 五态 + decided_by + 建议动作
  inkcal events [--all --last 3d] [--json]       # outbox，消费式读取
  inkcal run [--date D]                          # 不变，额外写 pipeline_events
```

---

## 5. 对话场景 Before / After

| 场景 | 现在 | 改造后 |
|---|---|---|
| "昨晚那顿是两人份，热量减半" | ❌ 无 edit 命令，agent 请你去 web | `edit --meal 红烧肉 --date 2026-07-21 --calories 300 --note "两人份"`，旧值自动入历史 |
| "把昨天红烧肉那条标成有误" | search 拿不到 ID → 绕 `label --list` 两步对账 | `label --meal 红烧肉 --date ... --label wrong`，歧义时返回候选追问 |
| "上周平均每天多少蛋白" | 循环 7 次 `view --date` + 解析 ASCII 口算 | `stats --from --to` 一次调用，代码算好精确值 |
| "中午那张照片怎么没记上" | 无入口，agent 只能猜 | `explain --date` → `classified_non_food / decided_by=siglip2`，并附"可 `analyze --id` 强制分析" |
| "这张漏判了，给我算上" | 仅 web 相册挑选 | `analyze --id` 直送 Gemini，自动移出 `classified_non_food` |
| （打开会话） | 静默，等你问 | agent 先 `events` → "中午咖喱那顿 confidence 偏低，要看看吗？" |

---

## 6. 实施计划

### Milestone 1：消除撞墙（P0，预计 1–2 天）✅ 已完成 2026-07-22

- [x] P0-1 `--json`（view / search / label --list / label --status，search 输出补 asset_id 与 id）→ `c5253de`
- [x] P0-2 `inkcal edit`（含自动写 reanalysis_history）→ `c854ac5`
- [x] P0-3 `inkcal explain` + `classified_non_food.decided_by` 列迁移 → `15dd448`
- [x] P1-7 结构化错误（提前到本阶段，与 --json 同体落地）→ `c5253de`

附带修复：`update_record`/`move_record` 刷新 `updated_at`、`label` 缺参数不再崩溃、`view --from/--to` 范围查询、`INKCAL_DB` 环境变量支持。

交付标准：第 5 节场景表前四行全部走通。✅

### Milestone 2：解锁组合（P1，预计 2–3 天）

- [ ] P1-4 `src/resolver.py` + 全部写命令接入
- [ ] P1-5 `inkcal stats`
- [ ] P1-6 `src/pipeline_ops.py` 抽取 + `analyze` / `reanalyze` CLI
- [ ] `food_detector.score()` 暴露（为灰区事件铺路）

交付标准：SKILL.md 里的两步对账全部消失；web 端回归无行为变化。

### Milestone 3：从"不僵硬"到"活"（P2，预计 2–3 天）

- [ ] P2-8 `pipeline_events` 表 + pipeline 写事件 + `inkcal events`
- [ ] P2-9 SKILL.md 瘦身至一页；运维内容迁 DEVELOPMENT.md
- [ ] （可选）`inkcal estimate --meal` 文本估算兜底
- [ ] （远期）P2-10 MCP server 封装

交付标准：hermes 会话开场能主动报告未消费事件；SKILL.md 删掉任何一条 agent 行为不漂移。

### 兼容性说明

- 所有改动**向后兼容**：不改表现有列（仅 `classified_non_food` 加列，有默认值）；cron 的 `inkcal run` 行为不变；web UI 行为不变（P1-6 是重构非重写）。
- 每个 Milestone 独立可交付、可回滚。

---

## 7. 验收 Checklist（"只有 agent 能做"测试）

改造是否成功，不看代码看交互。以下每条在 hermes 里实测：

- [ ] 全程无 ID：连续 5 轮对话（记 → 查 → 改 → 标 → 追问原因），双方都不需要提到任何 asset_id
- [ ] 模糊指代：说"前天晚上那顿"，agent 一次定位成功；说"红烧肉"，有两条时 agent 列出候选让你选而不是瞎猜
- [ ] 聚合可信：问"上周蛋白日均"，回答的数字与 `stats --json` 输出逐位一致（agent 不口算）
- [ ] 可解释：随便挑一张没入库的照片，agent 能说出它在五态中的哪一态、谁决定的、怎么补救
- [ ] 主动性：新跑一次 pipeline 后开会话，agent 在未被问的情况下报告了 `low_confidence` / `gemini_rejected` 事件
- [ ] 规则不漂移：新开一个 session / 换一台机器，估算置信度、缓存、日期边界行为完全一致（因为都在代码里）

六条全过 → 僵硬感消失。只过前四条 → 从"僵硬"变成"顺手"，但还没到"活"。

---

## 8. 附录：关键代码草案

### 8.1 `src/db.py`：schema 迁移（P0-3 / P2-8）

```python
def _migrate_schema(conn: sqlite3.Connection):
    """Idempotent column/table additions for existing databases."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(classified_non_food)")}
    if "decided_by" not in cols:
        conn.execute(
            "ALTER TABLE classified_non_food "
            "ADD COLUMN decided_by TEXT NOT NULL DEFAULT 'siglip2'"
        )
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pipeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            asset_id TEXT,
            payload TEXT,
            consumed INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_events_consumed ON pipeline_events(consumed);
    """)
    conn.commit()
```

在 `_create_schema()` 末尾调用。

### 8.2 `src/resolver.py`：指代解析（P1-4）

```python
from dataclasses import dataclass
from src import db

@dataclass
class Resolution:
    record: dict | None          # 唯一命中
    candidates: list[dict]       # 多候选
    error: str | None            # 'not_found' | 'ambiguous'

def resolve(*, asset_prefix=None, ref=None, last=False,
            meal=None, date=None) -> Resolution:
    if ref is not None:
        row = db.get_record_by_id(ref)          # 需新增：按 records.id 查
        return Resolution(row, [], None if row else "not_found")
    if asset_prefix:
        hits = db.find_records_by_asset_id_prefix(asset_prefix, date)
    elif last:
        hits = db.get_records_by_date_range("1970-01-01", "2999-12-31")[-1:]
    elif meal:
        hits = db.search_records(meal, start_date=date, end_date=date, limit=5)
    else:
        raise ValueError("no locator given")
    if len(hits) == 1:
        return Resolution(hits[0], [], None)
    if not hits:
        return Resolution(None, [], "not_found")
    return Resolution(None, hits, "ambiguous")
```

### 8.3 `main.py`：`cmd_edit` 骨架（P0-2）

```python
def cmd_edit(args):
    db.init_db()
    res = resolver.resolve(asset_prefix=args.id, ref=args.ref,
                           last=args.last, meal=args.meal, date=args.date)
    if res.error:
        fail(res.error, "未唯一定位记录", candidates=res.candidates)

    old = res.record
    updates = {k: v for k, v in {
        "meal": args.new_meal, "calories": args.calories,
        "protein_g": args.protein, "carbs_g": args.carbs, "fat_g": args.fat,
    }.items() if v is not None}

    # 日期/时间变更走 move_record，保留 time-of-day
    if args.new_date:
        db.move_record(old["asset_id"], args.new_date, updates or None)
        updates = {}

    if updates:
        # 旧值留痕，可回滚
        db.append_reanalysis_history(old["asset_id"], {
            **{k: old[k] for k in
               ("meal", "calories", "protein_g", "carbs_g", "fat_g", "confidence")},
            "notes": args.note or "manual edit",
        })
        updates.setdefault("confidence", "high")   # 人工修正 > 模型估计
        db.update_record(old["asset_id"], updates)

    emit_record(db.get_record_by_asset_id(old["asset_id"]), args)
```

### 8.4 `main.py`：统一错误出口（P1-7）

```python
EXIT = {"not_found": 2, "ambiguous": 3, "not_food": 4,
        "invalid_args": 64, "external_error": 69}

def fail(code: str, message: str, **extra):
    if getattr(_args, "json", False):
        print(json.dumps({"ok": False, "error": code,
                          "message": message, **extra}, ensure_ascii=False))
    else:
        print(f"❌ {message}")
    sys.exit(EXIT.get(code, 1))
```

### 8.5 pipeline 写事件（P2-8，`main.py::_run_source` 片段）

```python
run_id = uuid4().hex  # cmd_run 入口生成，传入 _run_source

score = detector.score(thumb)                       # food_detector 新增
if not detector.is_food_score(score):
    db.add_classified_non_food(aid, decided_by="siglip2")
    if 0.4 <= score <= 0.6:                          # 灰区 → 值得人工看
        db.add_event(run_id, "classifier_unsure", aid, {"score": score})
    continue

result = analyzer.analyze(original)
if result.get("meal") in ("not real food", "unknown"):
    db.add_classified_non_food(aid, decided_by="gemini")
    db.add_event(run_id, "gemini_rejected", aid, None)
    continue

rec = append_log(...)
db.add_event(run_id, "meal_recorded", aid,
             {"meal": rec["meal"], "calories": rec["calories"]})
if rec["confidence"] == "low":
    db.add_event(run_id, "low_confidence", aid, {"record_id": rec["id"]})
```

---

## 9. 风险与取舍

1. **`analyze --id` 绕过隐私过滤器**：这是设计使然（用户显式选择 = 授权），与 web 端"选择照片"语义一致；文档里写明即可。
2. **灰区阈值（0.4–0.6）是拍的**：先上线收集 `classifier_unsure` 事件，用 `label` 数据回归校准，再调。
3. **events 表无限增长**：加一条 nightly 清理（`DELETE FROM pipeline_events WHERE consumed=1 AND created_at < datetime('now','-30 day')`），或接受它很小（每天 < 100 行）。
4. **MCP 别急着做**：P0–P1 的 CLI 原语化是 MCP 的地基，也是 hermes 现在就能用的形态；两层同时改风险翻倍。
5. **不要把自然语言日期解析做进代码**（"昨天""上周三"）：语言理解是 agent 的职责，代码只收 `YYYY-MM-DD`。这条边界守住了，系统才既聪明又可测。

---

*文档完。建议把 Milestone 1 直接开一个 GitHub issue 或交给 coding agent 执行，P0 四项彼此独立，可并行。*
