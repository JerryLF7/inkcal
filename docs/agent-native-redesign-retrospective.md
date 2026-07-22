# inkcal Agent-Native 改造回顾

> 日期：2026-07-22
> 基于：[agent-native-redesign.md](./agent-native-redesign.md) v1.0
> 总耗时：~4 小时（含文档同步）

---

## 背景

inkcal 的 CLI 最初是为**人类终端用户**设计的——argparse 子命令、ASCII 表格、emoji 输出。当通过 agent（hermes / Claude）使用时，agent 被迫扮演"自然语言 → argparse 翻译器"角色，每次交互都像是在"强行接入"一个不为自己设计的接口。

核心矛盾：**agent 是软件的运行时，却被当成软件的用户。**

## 改造范围

12 个 commit，新增 ~900 行代码，删除 ~250 行旧代码和文档。CLI 从 7 个子命令扩展到 14 个。

```
1aeba15  docs: add agent-native redesign plan          (设计方案)
c5253de  feat: --json output, structured errors        (M1 P0-1 + P1-7)
c854ac5  feat: edit command                            (M1 P0-2)
15dd448  feat: explain command                         (M1 P0-3)
e4a57b4  docs: mark M1 complete
27c66ac  feat: resolver, stats, delete, detector.score (M2 P1-4 + P1-5)
20eafda  feat: pipeline_ops, analyze, reanalyze        (M2 P1-6)
5ed0d52  docs: mark M2 complete
3ff18e6  feat: pipeline_events outbox                  (M3 P2-8)
f96291c  docs: slim SKILL.md                           (M3 P2-9)
814bcfd  docs: mark M3 complete
bc4c567  docs: sync usage/cli-workflows/README
```

## Milestone 1：消除撞墙（P0 + P1-7）

**问题**：agent 撞到各种能力边界——没有 JSON 输出只能解析表格、出错后只能看中文猜原因、不能直接修改记录。

**做了什么**：

| 项 | 变更 |
|---|---|
| `--json` 全量输出 | view/search/label/add 支持 `--json`，返回 `_record_from_row` 的 dict 结构，含 `id` 和 `asset_id` |
| 结构化错误码 | `fail()` helper + 5 种错误码（not_found=2 / ambiguous=3 / not_food=4 / invalid_args=64 / external_error=69），agent 不再需要解析中文错误消息 |
| `inkcal edit` | 直接修改 meal/热量/宏量/日期/时间，旧值自动写入 `reanalysis_history`，人工修正默认 `confidence=high` |
| `inkcal explain` | `--id` 单张五态追溯（recorded / classified_non_food / gemini_rejected / ignored / unprocessed）+ 建议动作；`--date` 对 Immich 全量对账 |
| 附带修复 | `update_record`/`move_record` 刷新 `updated_at`；`view --from/--to` 范围查询；`label` 缺参数不再崩溃；`classified_non_food.decided_by` 列迁移 |

**关键设计决策**：
- `_record_from_row` 补了 `records.id`（之前只输出 `asset_id`），这成为后续 resolver 的 `--ref` 模式的基础
- `decided_by` 列区分了"分类器否决"和"Gemini 否决"两种情况——explain 的回答因此是确定的而非猜测的

## Milestone 2：解锁组合（P1）

**问题**：agent 仍需要两步对账（search → 找 ID → 执行）、不能聚合查询、不能纠分类器漏判。

**做了什么**：

| 项 | 变更 |
|---|---|
| `src/resolver.py` | 统一指代解析层——`--ref <id>` / `--id <前缀>` / `--last` / `--meal <关键词> [--date]`，歧义时返回 structured candidates |
| `inkcal stats` | `--from/--to` 或 `--last 7d/2w/1m` + `--group-by day` + JSON，聚合数字由代码算而非 agent 口算 |
| `inkcal delete` | 删除 + 自动加入忽略列表，`db.delete_record` 已存在但无命令暴露 |
| `inkcal analyze` | 强制送 Gemini 分析（跳过食品检测），纠分类器漏判 |
| `inkcal reanalyze` | 补充细节重新估算，旧值入 `reanalysis_history` |
| `src/pipeline_ops.py` | 从 web/server.py 下沉核心逻辑，web 端点改为调用共享函数，零行为变化 |
| `food_detector.score()` | softmax 暴露食物类概率，为灰区事件铺路 |

**关键设计决策**：
- Resolver 的 `--meal` 与 edit 的餐名修改冲突，将 edit 的餐名参数改为 `--new-meal`——因为 edit 命令在 M1 才加入（同一天内），无实际兼容性问题
- `pipeline_ops.analyze_asset` 返回 `(record, error)` 元组而非抛异常——让 web 层可以按 error code 返回不同 HTTP 状态码
- 聚合的职责边界：`--last 7d/2w/1m` 的日期计算在代码里（确定性），"昨天""上周三"的自然语言换算仍在 agent（语言理解）

## Milestone 3：从"不僵硬"到"活"（P2）

**问题**：agent 仍然**静默**——每次交互都由用户发起。cron 跑完 pipeline 后，agent 不知道发生了什么。

**做了什么**：

| 项 | 变更 |
|---|---|
| `pipeline_events` 表 | 幂等迁移 + 5 种事件类型：`meal_recorded` / `low_confidence` / `gemini_rejected` / `classifier_unsure` / `run_summary` |
| `inkcal events` | 消费式读取（默认标记 consumed）+ `--peek`（只读不消费）+ `--consumed --limit N`（历史查询） |
| `SKILL.md` 瘦身 | 从 188 行压缩到 90 行——伪阳性缓存策略、Gemini JSON 修复描述等已代码化的规则全部删除，替换为命令速查表 + locator 参考 + 错误码表 |
| 文档同步 | `usage.md` / `cli-workflows.md` / `README.md` 全部更新至 14 个命令 |

**关键设计决策**：
- Events 的 `consumed` 字段 + 消费式读取：agent 每次会话开头 `inkcal events --json`，有料就主动开口，没料就静默——不会重复报告
- `classifier_unsure` 事件的灰区阈值（0.4–0.6）是拍的——需要在积累标签数据后回归校准
- `SKILL.md` 不再背运维知识（Web 生命周期、FRP 部署）——这些在 `DEVELOPMENT.md` 和 `CLAUDE.md` 里
- Events 表不做自动清理——每天 < 100 行，年增 ~36K 行，SQLite 足以应对

## Before / After

### 场景对比

| 场景 | 改造前 | 改造后 |
|---|---|---|
| "昨晚那顿是两人份，热量减半" | ❌ 无 edit 命令，只能请用户去 web | `edit --meal 红烧肉 --date 2026-07-21 --calories 300 --note "两人份"` |
| "把昨天红烧肉标成有误" | search 拿不到 ID → 绕 `label --list` 两步对账 | `label --meal 红烧肉 --date ... --label wrong`，歧义时返回候选 |
| "上周平均每天多少蛋白" | 循环 7 次 `view --date` + 解析 ASCII 口算 | `stats --from/--to` 一次调用，代码算好精确值 |
| "中午那张照片怎么没记上" | 无入口，agent 只能猜 | `explain --date` → 状态 + decided_by + 补救建议 |
| "这张漏判了，给我算上" | 仅 web 相册挑选 | `analyze --id` 直送 Gemini |
| "少算了米饭，重算" | 仅 web 灯箱重新分析 | `reanalyze --ref 42 --notes "少算了一份米饭"` |
| （打开会话） | 静默，等用户问 | agent 先 `events` → "中午识别了两餐，咖喱那顿 confidence 偏低，要看看吗？" |

### 架构变化

```
改造前：
  用户 ↔ agent ↔ CLI（人类接口）↔ 系统
  agent 被迫解析 ASCII 表格、中文错误、猜原因

改造后：
  用户 ↔ agent ↔ 结构化原语 + 事件流 ↔ 系统
  agent 直接拿到 JSON、错误码、候选清单、事件通知
```

### CLI 全景（改造后）

```
数据写入 (6)
  add / edit / delete / analyze / reanalyze / replace

数据读取 (3)
  view / stats / search

标注与维护 (1)
  label

可观测性 (2)
  explain / events

流水线 (1)
  run

系统 (1)
  migrate
```

## 验收状态

改造方案第 7 节的验收 checklist：

- [x] **全程无 ID**：连续多轮对话不需要提到 asset_id（resolver 的 `--meal`/`--last` 模式消除）
- [x] **模糊指代**：`--meal 红烧肉` 一次定位，有歧义时返回候选让用户选
- [x] **聚合可信**：`stats --json` 的数字与 agent 回复逐位一致（agent 不口算）
- [x] **可解释**：`explain` 给出确定状态 + 谁决定的 + 怎么补救
- [x] **主动性**：`events` 消费式读取，agent 能主动报告而未消费事件不会重复
- [x] **规则不漂移**：SKILL.md 瘦身后，伪阳性缓存、JSON 修复等规则均在代码中，换 agent/session 行为一致

## 远期（未实施）

两个设计项有意暂缓：

1. **`inkcal estimate --meal`**（文本估算兜底）：在 CLI 和 agent 都能正常估算的现状下，额外调 Gemini 文本接口带来的延迟 > 收益。等有"agent 反复估不准某类食物"的反馈后再加。

2. **MCP Server 封装**：CLI + `--json` 已经是 agent 可用的 stable interface。MCP 是锦上添花——跳过 shell 和文本解析，错误语义用 MCP 原生 error 表达。建议等 CLI 原语层稳定使用 1-2 周后再包，避免同时改两层。

## 经验教训

1. **原语 > 工作流**：db.py 里大多数能力早已存在（`update_record`、`summarize_records`、`delete_record`），只是 CLI 没暴露。改造的主体不是写新功能，而是重新设计暴露层——这比预想的快得多。

2. **机器可读优先**：`--json` 不是"给人看的表格加了个 JSON 版本"，而是**唯一的真相源**。人类可读格式应该只是 JSON 的渲染，不是并列的两种形态。这个原则从一开始就定对了。

3. **职责边界是稳定性来源**：resolver 不解析自然语言日期（"昨天""上周三"），代码只收 `YYYY-MM-DD`。语言理解归 agent，确定性解析归代码。这条边界让系统"既聪明又可测"。

4. **Web 逻辑下沉无痛**：pipeline_ops 的抽取过程中，web 端点零行为变化——同样的函数、同样的参数、同样的返回值。前提是函数接口设计时就想好了两个调用方的需求。

5. **文档越厚说明软件能做的越少**：原 SKILL.md 里有 ~80 行伪阳性缓存策略描述、~40 行 Gemini JSON 修复逻辑——这些都是 if-else 能表达的规则，不该以散文形式写给 agent 读。代码化后 SKILL.md 从 188 行压缩到 90 行，删掉的每一条都是之前软件做不到、靠 agent 服从性弥补的东西。
