# inkcal · Agent 项目交接

> **接手原则**：先读本文，再读即将修改的模块；当本文与代码冲突时，以当前 git HEAD 和代码为准，并在同一工作单元内更新 `AGENTS.md`。不得沿用过期设计，也不得把交接文档维护留给下一位 agent。
>
> **用途**：本文是本仓库唯一的 Agent 规则与交接入口，包含当前真实状态、已拍板约束、运行方式、验证方式与下一步；历史过程已经整合，不需要再从旧交接文档推断当前状态。
>
> **版本定位**：本文反映提交前的当前工作状态；接手时先执行 `git log -1 --oneline` 和 `git status --short`，再以当前 HEAD 与代码为准。
>
> **工作区注意**：`web/ui/node_modules/` 是本地依赖目录、未跟踪，绝不能提交。不要 `git add .` / `git add -A`。`.env` 绝不能提交。

---

## 1. 项目是什么

inkcal 是本地优先的自动饮食热量记录器：用户只需拍食物照片，照片备份到 Immich/PhotoPrism 后，由定时任务处理并写入本地 SQLite。

```text
Immich / PhotoPrism
  -> SigLIP2（本机 CPU 食物过滤，非食物照片不出内网）
  -> Luna（视觉编排：同餐 / 新餐 / 跳过判断，只写照片关系说明）
  -> Gemini（数值专家：热量与 P/C/F，自带全摄入基准任务框架）
  -> data/inkcal.db（SQLite，WAL）
  -> Flask JSON API + Web UI
```

核心价值是“零摩擦”：手机自动备份照片；cron 自动写记录；用户打开页面即可浏览和纠错。

### 绝对边界

- **日期与时区归属原则**：餐食记录的日历归属一律采用**照片拍摄地的当地日历日（Local Wall-clock Date）**，即 Exif 钟表时间与时区决定的当地日期（对应 `photo_time` 的前 10 位 `YYYY-MM-DD` / `substr(photo_time, 1, 10)`）。**禁止在 SQL 中使用 SQLite 内置的 `date(photo_time)`**，因其会隐式将带时区字符串转为 UTC 导致当地凌晨（00:00~08:00 HKT）照片日期倒退一天、从而引发 cron 无限重复处理（2026-09-14 凌晨事故：同一照片被重复处理 23 次）。无 Exif 时区或手动上传未带时区时回退至 HKT（并在 Web 端提供弹窗手动选择日期调整）；同餐时间间隔计算按绝对时刻对比。
- 写数据库必须经 `inkcal` CLI、`src/db.py` 的既有业务路径或已有 Flask API；不要用 SQLite shell 直接改数据。
- `asset_id` 是幂等键。删除 Immich 资产对应记录时要进入 `ignored_assets`，避免 cron 重新入库。
- 同餐组用 `records.merged_into` 表达：`NULL` = 主记录（一餐一卡），非 `NULL` = 附属照片行（指向主记录 asset_id）。两种形态：**状态延续**（同一食物吃前/吃后，Luna 一条 add 覆盖多张照片）从行数值清零，总值只在主行；**独立条目**（同餐不同食物分开拍，Luna 每张照片一条 add + `group_with` 关联）从行携带自己的数值。汇总永远对所有行直接求和（两种形态都正确），餐数只数主行。每张照片必有一行——update 决策覆盖的新照片也要落 0 值从行，否则 `already_processed` 查不到会导致 cron 无限重复处理（2026-08-29 事故：同一照片 6 小时被 update 35 次）。
- **跨批次状态延续（吃前/吃后 update，2026-09-16 规范）**：新照片为已有记录同一食物的新状态（如吃后残局）触发 `update` 时，必须同时将已有记录照片与新照片传入 `analyze_with_gemini`（`asset_ids=[<已有记录 asset_id>, <新照片 asset_id>]`），并在 `prompt_for_gemini` 中说明拍摄顺序与吃前/吃后关系，由 Gemini 联合对比评估实际摄入量；`image_getter` 遇到非当前批次 asset_id 自动从 DB 和照片源回溯原图。禁止单送吃后照片覆盖原记录（防 2026-09-15 事故：单送残局导致 1150 kcal 盒饭被错误覆盖成 450 kcal 残留量）。
- SigLIP2 是隐私门槛；用户从相册明确选择照片或手动上传时，才可绕过食物过滤。`AGENT_ENABLED=1` 时绕过 SigLIP2 的照片仍进入 Luna（skip 契约保留），失败降级直送 Gemini；`AGENT_ENABLED=0` 时直送 Gemini。
- Gemini 只负责估算，不负责同餐关系；Luna 只负责视觉判断/编排，不应自己编造热量。
- Luna 写给 Gemini 的 `prompt_for_gemini` 只准描述照片关系（同餐/顺序/以哪张为准），禁止餐次结论、食物内容预判、纳入/排除决定（2026-08-31 晚餐案例：Luna 排除啤酒导致漏算）。食物内容与纳入范围由 Gemini 依照片自行判断。
- `analyze_with_gemini` 单张照片时不经 Luna 提示词：Gemini 收到 固定 task_frame（全摄入基准等）+ 打包版 `analyze.md` + JSON 锚点，Luna 传入的任何文本被忽略。多张照片时 Luna 才必填 `prompt_for_gemini`（只写照片关系）。
- `analyze_with_gemini` 的份量估算规则由系统固定注入（`agent_tools.py::_gemini_multi_image` 的 task_frame）：全摄入基准（饮品一律计入）、拿不准时计入并降 confidence（宁可多算可纠错，不可漏算无感知）、非真实食物全零。该框架在 Luna 文本之前发送；不要把它合并回 prompt 或删除。
- **Gemini 输出标题化（2026-09-13 起）**：`meal` = 短标题（≤10 字餐型概括，如「中式外卖盒饭」，不堆菜品清单），`meal_detail` = 菜品明细与份量说明。两条 Gemini 路径（`prompts/analyze.md`、`agent_tools` 的 task_frame/format_anchor）与 `reanalyze.md` 都输出这两个字段；落库为 `records.meal_detail` 列，FTS 同时索引两列。**旧记录不回填**（meal 保持整句话、detail 为空，已拍板）。

---

## 2. 运行环境与常用命令

项目根目录：`/home/jerry/Coding/inkcal`

```bash
# 所有 Python 运行都用 venv，系统 Python 缺 pillow-heif/imagehash 等依赖
venv/bin/python main.py --help
venv/bin/python web/server.py

# 推荐 Web 启动方式（从项目根目录）
INKCAL_PORT=5800 venv/bin/python web/server.py

# 构建 Vue 前端；产物会写入 web/static/
npm --prefix web/ui run build

# 现有回归与语法检查
PYTHONPATH=. venv/bin/python scripts/test_contract_parse.py
PYTHONPATH=. venv/bin/python scripts/test_merge_groups.py
PYTHONPATH=. venv/bin/python scripts/test_lightbox_smoke.py
PYTHONPATH=. venv/bin/python scripts/test_chat_smoke.py
venv/bin/python -m compileall -q main.py src web/server.py
git diff --check
```

- Web UI：根路由 `/` 直接提供 Vue 前端；`/app/` 重定向到 `/`。原旧版原生 JS UI 已彻底停用并移除。
- Flask 默认仅监听本机；通过 FRP/反向代理访问时，必须保留既有鉴权与可信代理逻辑。
- 若 5800 被占用，用 `fuser -k 5800/tcp`，不要依赖 `pkill -f web/server.py`。

### Vercel 说明

GitHub 推送后，Vercel 可能因发现 `web/ui/package.json` 与 Vite 自动发“可导入项目”通知。这**不代表已部署**，也不应在当前阶段导入：Vue UI 使用相对 `/api/*`，真实 API、SQLite、Immich/PhotoPrism 和模型凭据均在 NUC 的 Flask 服务上；单独部署静态页会失效并破坏 local-first 边界。

---

## 3. 代码地图

### Python 业务层

| 路径 | 职责 |
|---|---|
| `main.py` | CLI 入口：run/view/add/edit/search/stats/delete/label/replace/analyze/reanalyze/explain/events/migrate/merge 等；`_run_agent_batch` 负责 cron 侧 Luna 决策落地（含同餐分组与 update 幂等） |
| `src/db.py` | SQLite schema 与全部数据访问；WAL、FTS、records、审计、chat 表 |
| `src/immich_client.py` / `src/photoprism_client.py` | 照片源客户端与时间解析 |
| `src/food_detector.py` | SigLIP2 本地过滤；可自动加载 `data/finetuned-model/` |
| `src/calorie_analyzer.py` | Gemini/OpenAI-compatible 视觉估算 |
| `src/pipeline_ops.py` | CLI 和 Web 共用的强制分析/重新分析业务路径 |
| `src/resolver.py` | CLI 记录指代解析：`--ref` / `--id` / `--last` / `--meal + --date` |

### Luna 批处理层

| 路径 | 职责 |
|---|---|
| `src/agent_contract.py` | 批处理 Decision 契约、工具 schema、系统提示；同文件还含聊天工具 schema 与提示 |
| `src/agent_tools.py` | MCP-ready 纯函数工具；批处理工具和聊天读/写工具 |
| `src/agent_harness.py` | 批处理的 OpenAI Responses API loop；唯一预期会随未来 fx/MCP 迁移替换的层 |

批处理 `session` 的意思只是**一次 `harness.run()` 的短命工作上下文**，不是用户聊天会话。它通过 `agent_decisions` 留审计，并在失败时降级旧的单图 Gemini 路径。

### 聊天后端（已写好）

| 路径 / API | 状态与用途 |
|---|---|
| `src/chat_agent.py` | 已实现：Luna 长对话 loop、每轮从 SQLite 重建窗口并累积工具往返（**不发送 `previous_response_id`**）、重试、删除确认卡 |
| `chat_sessions` / `chat_messages` / `app_settings` | 已在 `src/db.py` 的幂等迁移中创建 |
| `GET/POST /api/chat/sessions` | 历史会话列表 / 创建会话 |
| `GET /api/chat/messages?session_id=` | 取某会话消息；不传则最新会话 |
| `POST /api/chat/send` | 同步发消息并得到 `reply`、`tool_log`、`session_id` |
| `GET/PUT /api/settings` | 当前仅 `chat_window`，范围 5–50，默认 20 |

聊天工具已具备：范围查记录、统计、全文搜索、读取 agent 决策、纯文本补录（`add_record`，经 Gemini 文本分析）、编辑记录、重新分析、请求删除确认。

**写权限规则**：`add_record`、`edit_record` 和 `reanalyze_record` 可直接执行，沿已有历史审计；删除工具只返回 `confirm_card`，真正删除必须由 UI 用户确认后调用既有 `DELETE /api/record`，以保留 ignored-assets 副作用。

### Web 与 Vue 前端

| 路径 | 职责 |
|---|---|
| `web/server.py` | Flask API、可选认证、图片代理、手动上传、相册选择、聊天 API；根路由 `/` 提供 Vue UI，`/app/` 重定向到 `/` |
| `web/ui/` | 新 Vue 3 + Vite 源码 |
| `web/static/` | Vue 生产构建产物（`index.html` + `assets/`）；**需要与源码一同提交** |
| `docs/prototypes/two-tab-proto.html` | 已交付、已确认的 UI 原型；不要再重画 |

---

## 4. 已拍板的产品与 UI 约束

### 双 Tab 是最终一级导航

- 全局只有 **记录** 与 **Luna** 两个 Tab。
- 支持底部 Tab 点击和左右滑动。
- 默认落在哪一页尚未最终拍板；不要擅自把任一页设为永久默认。

### PC 布局（≥1024px，已拍板）

- 桌面宽度下不用双 Tab 滑动：三栏结构——**左侧常驻导航栏（约 264px：品牌、「选择照片」、日/周切换、常驻月历、今日/本周快捷键）+ 记录浏览主区 + Luna 右侧栏**（约 400px，默认展开，可折叠，折叠后右缘留唤出把手）。底部 Tab bar 与滑动手势在桌面端禁用。
- **布局实现关键**：`.app` 基础样式是手机端的纵向 flex；桌面端靠 `.app.desktop { flex-direction: row }` 转为横向三栏。给 `.app` 加任何新的直接子元素时必须检查主轴方向，否则会像 nav-rail 初版那样横插在页面顶部、把主区挤到下半屏。
- **月视图在桌面端不作为主区页面**：月历常驻左栏（`MonthView` 的 `compact` 模式，格子固定 34px 高），点日期跳主区日视图；PC 端主区只有日/周两视图，双列卡片。手机端（<1024px）仍保留日/周/月三视图。
- 主区内容在超宽屏下限宽（约 1080px）居中。
- 手机布局（<1024px）行为完全不变；断点判断在 `web/ui/src/App.vue` 的 `matchMedia('(min-width: 1024px)')`。

### 记录 Tab（已实现主要骨架）

- 日视图：最新记录在顶部，向下无限加载更早记录；**每日内卡片也按 `photo_time` 倒序**（`DayView.groupRecords` / `WeekView.timeline` 内排序， tie-break 用 `asset_id`）；日期吸顶分隔线（`.date-sep`）左侧显示日期/星期，右侧显示当天**总摄入热量与 P/C/F 宏营养素**（超过每日目标变红；今天也显示作为当日汇总锚点）；顶栏显示当前浏览日期。
- 周视图：柱状图 + 餐食时间轴；可前后切换周，未来周禁用；暴露 `resetToCurrentWeek()` 供左栏「本周」快捷键回当前周。
- 月视图：日期格显示每日热量占目标的圆环（有记录的日期数字加粗提亮），点击跳回日时间轴；不使用额外色点标记（已验证冗余）。
- 顶栏/左栏的 **选择照片** 必须保留两条既有路径：Immich/PhotoPrism 相册未处理照片与本地上传（Vue 端为 `PhotoPicker.vue`）。
- 记录卡使用 `P / C / F` 字母，而非“蛋白/碳水/脂肪”的中文文字提示，以保持旧版表达。
- 卡片缩略图为 **96px**（Immich `size=thumbnail` 250px 足够清晰，不要换更大尺寸）；卡片 padding 12px。
- PC 端日/周时间轴卡片为**双列网格、固定列宽**；主标题（`meal`）超长时折行显示（`MealCard` 的 `meal-name` 为 `white-space: normal` + `word-break: break-word`），不做省略号截断。
- 卡片标题区为**主标题 + 副标题**两级：`meal-name`（15px 粗）+ `meal-detail`（12px 灰，**最多 2 行 `-webkit-line-clamp` 省略**，已拍板；完整明细在 lightbox 全文展示）。旧记录无副标题时不渲染该行。lightbox 主记录明细全文展示（`.lb-meal-detail`），形态 B 分行各带 2 行省略的 `.row-detail`。
- `MealCard` 与 `MealLightbox` 是可复用组件；lightbox 已可展示 AI 决策审计和执行两步删除确认；lightbox 右上角关闭按钮为 SVG 细线 X + 圆形幽灵按钮样式（与 `.chat-plus` 同一视觉语言），不要退回裸文本 `✕`。
- 已决定：**不在时间轴显示 SigLIP2/Luna 判为非食物的 skip 照片**。`/api/skipped` 可以为未来纠错留着，但不是一期 UI。

### Calo Tab（已接通聊天后端与完整交互，2026-09-16）

前端 Tab 与助手形象正式确定为 **Calo**（取自 inkcal / calor，后半截 Cal 的演化），后端系统提示对应更新为「你是 inkcal 的饮食助手 Calo」。
`web/ui/src/components/ChatPane.vue` 完整接通聊天后端：

- 默认恢复最新聊天 session（优先从 `localStorage` 读取用户停留的会话，回退到后端有实际消息的最新 session）；支持历史抽屉选择与惰性手动新建（点 `＋` 时仅清空前端状态，首条消息发送时才真正落库，避免空 session 占位与刷新空白）。
- 渲染普通消息（支持完整 Markdown 解析与排版）、摄入汇总统计卡（`get_intake_stats`）、餐记录 artifact（`MealCard` 结构化展示，可点击直接唤出 `MealLightbox`）、工具执行状态、安全删除确认卡。
- 可通过自然语言查、改、重分析饮食记录；支持纯文本记账（`add_record`：没拍照时通过文字补录零食/加餐，由 Gemini 统一以 `src/prompts/analyze_text.md` 模板进行全摄入基准估算并落库为 `manual-` 记录，并由 Gemini 挑选一个匹配食物的 Emoji 代替无图时的空餐盘展示）；写操作完成后自动触发 `touch()` 联动更新时间轴。
- **意图消歧原则（防重记误增）**：当用户表述指向某具体餐次或包含细节修正（如“今晚的...”、“一共15个”、“其实是玉米猪肉馅”、“没算米饭”）时，Calo 必须先调用 `get_records_in_range` 查询已有记录；若已存在对应记录，严禁调用 `add_record`（避免同一餐重复入库导致热量双倍计算），必须优先调用 `reanalyze_record` 让 Gemini 结合原图与修正说明更新原记录。
- PC 布局与盒模型：全局配置 `box-sizing: border-box`，彻底解决时间轴右侧 padding 撑大导致第二列卡片及吸顶日期汇总被 Calo 侧栏遮挡的问题。
- 删除安全契约：`request_delete_record` 的 `confirm_card` 真实渲染为二次确认卡；只有用户显式点击「确认删除」后才调用既有 `DELETE /api/record`，取消仅关闭卡片。**严禁让模型或前端直接绕过确认删除。**
- 聊天设置：支持通过 `⚙️` 弹窗读写 `/api/settings` 的 `chat_window`（5～50 轮）。
- 工具层数据流：`_record_brief` 与 `_group_brief` 补充 `thumbnail_url` 与 `replacement_image`，使聊天 artifact 能够直接渲染缩略图。
- 回归测试：`scripts/test_chat_smoke.py`。
- 一期不做聊天传图（未来可从 `+` 入口扩展）。

---

## 5. 聊天 session 与缓存模型

聊天 session 和批处理 session 必须严格分离：

```text
批处理 run：短命；用于判断一批新照片；状态审计到 agent_decisions
聊天 session：跨天；用户可手动新建；消息持久化到 chat_sessions/chat_messages
```

- 每个目前的 `chat_sessions` 行是一条会话线程；未来真出现并行主题需求后再引入 `conversation_id`。
- **当前 endpoint 不支持 `previous_response_id`**：`LUNA_BASE_URL` 指向的网关接受该参数但**静默忽略**（返回 200、不回填字段、上下文完全不传递）。实测：带 `previous_response_id` 问上一轮内容，`input_tokens=21`（只有当轮那句），答不出；全量重发则正确。因此代码**已停止发送它**，改为每轮重发累积历史（`agent_harness.py` 与 `chat_agent.py`）。
- **工具往返必须回放 `function_call` 项本身，再接 `function_call_output`**。只发 output 会被上游 400 拒绝：`No tool call found for function call output with call_id ...`。没有 `previous_response_id` 时这是硬要求，不是优化（实测 r2 回放→200，r3 只发 output→400）。
- 前缀缓存仍然有效，**且包含图片**：稳定的 `[长 system + 内联图片]` 前缀从第二轮起约 99.9% 命中，历史增长时前缀命中数保持稳定，只按新增尾巴计费。实测 3728 token 中命中 3725（图片占 922 token，全部命中）。硬约束：**前缀须超过约 1024 token**，否则 `cached_tokens=0`（929 token 的前缀实测两遍均为 0）。
- 窗口采用无摘要滑动方式，默认 20 轮，`chat_window` 可调。业务事实必须通过工具查 SQLite，不依赖语言模型记忆。
- **换 endpoint 时必须先验证这两点**（`previous_response_id` 是否真的传递上下文、图片是否进缓存），否则表现为静默失忆或批处理静默降级回 Gemini，不会报错。

---

## 6. 下一步：优先任务（不要重复已完成工作）

### Phase 4.5：同餐组 UI（已实现，2026-09-04）

已实现（设计已与用户确认）：卡片 `×N` 角标 + lightbox 画廊 + **每张照片分行明细**（用户明确要求明细，不是只做组级信息）。要点：

- **桌面端（≥1024px）lightbоx 为左图右栏**（图区自适应 + 右栏固定 400px 独立滚动），`@media` 内只翻转 `.lb-inner` 主轴方向，不给 `.lightbox` 加新直接子元素。手机端维持纵向布局 + 主图左右滑动切换（40px 阈值）+ ←/→/Esc 键盘导航。
- **photos[] 契约扩展**：条目含 `asset_id / thumbnail_url / photo_time / meal / meal_detail / calories / protein_g / carbs_g / fat_g`，**刻意不含 confidence**（组级置信度在主记录上，逐照片无可操作场景）。
- **形态 A 从行显示「已并入整餐估算」**（判据：从行且数值全零），绝不在 UI 上显示 0 kcal——防 8-29 式误读。形态 B 从行带自己的 meal/数值，**行合计 = 组头**（`db.group_meals` 自动累加数值并拼接餐名如「主食 + 饮品/甜点」，2026-09-16 实现）。
- **双删除入口**：行内 ✕ 两步确认（`mode:"photo"`，独立武装态）与「删除整餐」两步确认（`mode:"meal"`）互不干扰。单张移除后**原地刷新**（`DELETE /api/record` photo 分支响应含 `promoted` 字段——删主行时前端按新主行锚点重拉 `/api/records?date=`）；形态 A 删主行晋升 0 值行时 toast 提示需要重估。组不存在时兜底关闭 + touch()。
- AI 决策区块匹配范围扩到**组内全部 asset_id**（含 target_asset_id）。
- 回归：`scripts/test_lightbox_smoke.py`（26 checks，隔离库，覆盖 photos 字段/形态 B 组头累加与餐名拼接/删从行/晋升/整餐删/404）。注意该脚本预置 `INKCAL_USER=""` 空串防 `.env` 被 load_dotenv 注入鉴权变量。
- 未做（刻意）：lightbox 内重分析入口、编辑宏营养素、跨零点组审计聚合。C 类历史数据（同分钟聚类）处理方式仍未讨论。

### Phase 5：接通 Calo 聊天 Pane（已实现，2026-09-16）

已完整实现并接通后端 `ChatAgent`：
- **名称与定位**：前端界面与助手正式命名为 **Calo**（从 inkcal / calor 演化而来），系统提示词（`CHAT_SYSTEM_PROMPT`）同步更新为「你是 inkcal 的饮食助手 Calo」。
- **组件架构**：新建 `web/ui/src/components/ChatPane.vue`，实现手机端第二 Pane 与 PC 端右侧三栏常驻/可折叠交互。
- **会话持久化与切换**：进入时默认恢复最新 session，点击 `◷` 打开历史会话抽屉（`GET /api/chat/sessions`），点击 `＋` 即时新建会话（`POST /api/chat/sessions`）。
- **发送与状态反馈**：非流式 `POST /api/chat/send`，发送中禁用输入并呈现思考脉冲动画；异常时友好 Toast 并保留用户输入以便重试。
- **结构化 Artifact**：`get_records_in_range` 与 `search_meals` 查出的记录、`edit_record` 与 `reanalyze_record` 变更结果均渲染为可复用 `MealCard`，并支持直接点击唤出 `MealLightbox` 展开详情；`get_intake_stats` 结构化呈现摄入总热量与 P/C/F 营养素。
- **两步安全删除**：`request_delete_record` 产生的 `confirm_card` 真实渲染为二次确认卡，仅在用户点击「确认删除」后调用既有 `DELETE /api/record` 并触发 `touch()` 联动更新时间轴，取消仅关闭卡片，绝不让模型或前端越权直接删除。
- **设置入口**：通过顶部 `⚙️` 图标可直接读取并调节 `/api/settings` 的 `chat_window`（5～50 轮）。
- **工具数据流补全**：`_record_brief` 与 `_group_brief` 补充 `thumbnail_url` 与 `replacement_image` 字段，使聊天 artifact 能够直接展示照片缩略图。
- **回归测试**：`scripts/test_chat_smoke.py`。

### 后续任务

- 主动确认队列：`/api/data-version` 已有 `pending: 0` 占位；在设计确认前不要自造 schema。
- Lightbox 内部能力扩展：重分析入口、宏营养素手动编辑。
- SSE：后端当前刻意是非流式，因为 relay SSE 能力未验证。先完成可靠同步模式，再决定流式和降级策略。
- 聊天传图、同餐分组缩略图可视化、时间轴 skip 卡均不在一期。

---

## 7. 数据、安全与常见坑

### 数据表

- `records`：餐记录；`merged_into` 列表达同餐组（NULL=主记录，非空=附属照片行，详见 §1 绝对边界）；`meal` 为短标题、`meal_detail` 为菜品明细（2026-09-13 起，旧记录 detail 为空、不回填）。
- `records_fts`：标题 + 明细两列全文检索（meal / meal_detail）。
- `reanalysis_history`：重分析和手动编辑前的旧值。
- `ignored_assets`：删除后永远跳过的照片。
- `classified_non_food`：SigLIP2/Gemini 非食物判定，含 `decided_by`。
- `agent_decisions`：Luna 批处理的 add/update/skip 决策审计，含 `group_with`（形态 B 入组目标）。
- `pipeline_events`：运行事件。
- `chat_sessions`、`chat_messages`、`app_settings`：聊天层。

### 鉴权与图片

- Web 认证为可选；`INKCAL_USER` 和 `INKCAL_PASS` 必须同时有或同时为空。
- `INKCAL_SECRET` 必须固定，否则 Flask 重启会丢 session。
- 只有请求来自 loopback 时才信任 `X-Forwarded-For` / `X-Real-IP`。
- 图片代理只允许 Immich/PhotoPrism 配置 URL 前缀；本地图片路由有 `Path.is_relative_to()` 防路径穿越。不要弱化。

### 运行与上传

- 一定用 `venv/bin/python` 启动；系统 Python 会造成上传/HEIC/Gemini 相关的隐性失败。
- 手动上传先做 Immich pHash 匹配再分析（幂等键先行）；无 EXIF 时应提供日期修正。
- SQLite 使用 WAL；不要在 server 运行时删除 `.db-wal` / `.db-shm`。
- SIGLIP2 对饮料存在漏检盲点；“选择照片”是正式补救路径，不是冗余功能。

### Agent 批处理关键规则

- 同批照片可按内容分组；对**已有记录**判同餐时，时间/日期是硬约束。
- 手动路径与 cron 路径共用 `AgentHarness` 与契约层；`SYSTEM_PROMPT` 不再假设照片经过 SigLIP2 过滤（手动照片未经预筛，非真实食物由 Luna 判断）。改动 prompt 时保持这一点。
- 前一天记录只能为跨零点连续进食提供上下文；正常时段即使同款食物也必须是新餐，不能跨天 update 合并。
- Gemini 全零、`not real food` 或 `unknown` 必须在契约层强制映射为 skip。
- Gemini 输出可能夹 markdown；工具层已在 prompt 最末尾固定 JSON 格式锚点。不要删。
- Luna 偶尔会输出完整 JSON 后多余 `]}`；`parse_decisions_json()` 已容忍纯括号尾巴，但仍应拒绝真实尾随垃圾。

---

## 8. 运行、服务与安全约定

- 日历日以照片 Exif 拍摄地当地日历日（`substr(photo_time, 1, 10)`）为准；无 Exif 时区回退至 `Asia/Hong_Kong`（UTC+8）。禁止在 SQLite 中使用 `date(photo_time)`。
- 幂等由 `asset_id` 保障；`already_processed()` 按日期检查。手动记录使用 `manual-<timestamp>` 作为 asset ID。
- 数据库是 `data/inkcal.db`，包含 records、重分析历史、忽略资产、非食物、Agent 审计、事件和聊天表；所有 schema 以 `src/db.py` 为准。
- 不直接用 SQLite shell 修改业务数据。优先走 CLI、`src/db.py` 既有业务函数或 Flask API；变更后用 `inkcal view`、`inkcal label --status` 或对应 API 验证。
- 环境变量放根目录 `.env`；关键值为 `IMMICH_URL`、`IMMICH_API_KEY`、`GEMINI_API_KEY`、`INKCAL_SECRET`、`INKCAL_USER` 和 `INKCAL_PASS`。后两者必须同时设置或同时为空。
- 项目曾从 `intake` 改名为 `inkcal`。发现旧脚本或配置引用时，统一使用 `INKCAL_*`、`inkcal` 与 `data/inkcal.db`。

### Flask 服务与安全约定

- 默认端口 `5800`，可用 `INKCAL_PORT` 覆盖；从项目根目录用 `INKCAL_PORT=5800 venv/bin/python web/server.py` 启动。
- `INKCAL_USER` 与 `INKCAL_PASS` 都设置时要求登录；登录 session 是 HTTP-only、SameSite=Lax、30 天；`INKCAL_HTTPS=1` 时 cookie 必须 Secure。`INKCAL_SECRET` 未固定会导致服务重启后丢登录。
- 登录限速为每 IP 5 次 / 300 秒。只有 `request.remote_addr` 是 `127.0.0.1` 或 `::1` 时才能信任 `X-Forwarded-For` / `X-Real-IP`；不要扩大可信代理范围。
- `/api/image` 只代理以 `IMMICH_URL` 或 `PHOTOPRISM_URL` 开头的 URL；Immich 使用 API key。`/api/local-image` 的 `Path.is_relative_to()` 路径穿越保护不可移除。
- Flask 自带 server 不应裸露公网；手机/外部访问应经反向代理与 HTTPS。FRP 场景保留真实 IP 逻辑。

### 图片来源、上传与展示约定

- 相册选择器查询所有启用源的未处理照片，按日期分页（7 天/页）；用户明确选择图片后不再跑 SigLIP2。`GET /api/album-photos` 与 `POST /api/analyze-album-photo` 是正式补漏路径。选择器支持**多选（≤10 张）**：批量 shape `{items: [...]}` 在 `AGENT_ENABLED=1` 时整批进一次 Luna harness（同餐状态延续合并为一组），harness 失败逐张降级；单条 shape 保持旧响应契约不变。
- 记录读取 API（`/api/records`、`/api/today`、`/api/week`）返回**分组后**的数据：`records` 只含主记录，主记录带 `photos` 数组（组内全部照片，按拍摄时间排序，含 asset_id/thumbnail_url/photo_time/meal/calories）；`summary` 基于原始行求和（形态 A 从行 0 值、形态 B 从行自带数值，都正确）。聊天工具（get_records_in_range/search_meals）同样按组聚合。
- 删除：`DELETE /api/record` 默认 `mode="meal"`（整餐级联：组内所有行删除 + 全部 asset_id 进 ignored_assets）；`mode="photo"` 仅移除单张照片，删主行时最早从行自动晋升。CLI `inkcal delete` 同理（`--photo` 仅删单张）。`inkcal merge <主> <从>` 把已有记录并入同餐组（默认从行清零=状态延续，`--keep` 保留数值=独立条目）。
- 同餐组多图评估（已实现）：同批多图或跨批次状态延续（吃前/吃后残局更新）时，均通过 `analyze_with_gemini`（回溯原图 + 联合对比）对全组照片进行综合摄入评估；形态 B（独立条目）由 `group_meals` 自动在组头累加各照片数值并拼接餐名与明细。
- `AGENT_ENABLED=1` 时手动路径（相册选择、本地上传、`inkcal analyze`）统一经 `src/pipeline_ops.py::analyze_assets_via_agent` 进 Luna harness：跳过 SigLIP2 但保留 Luna skip 契约（skip → `classified_non_food`，decided_by=agent），决策审计写入 `agent_decisions`；`update` 决策在手动路径降级为 `add`（手动照片无已有记录可并入）。harness 失败或决策未覆盖时逐张降级原直发路径。
- 手动上传先做 Immich pHash 匹配（幂等键先行，已处理返回 409），再走 Luna 或 Gemini；非食物返回 422。无 EXIF 时需允许后续日期修正，经 `/api/move-record` 重新尝试匹配。
- EXIF 时间必须用 Immich 的 `asset.exifInfo.dateTimeOriginal` 和 `timeZone`，不要下载缩略图再读 EXIF；缩略图可能没有 EXIF。`UTC+8` 与 IANA 时区均要兼容，未知时区回退 HKT。
- 卡片缩略图优先 Immich `size=thumbnail`，不要回退大 `preview`；慢网下保留超时、重试、请求取消/去重和缓存防御。旧原生 UI 的 localStorage 方案可作参考，新 Vue 实现不应无意倒退。

### 运行时已知坑

1. 仅使用 venv Python；系统 Python 缺 `pillow-heif`、`imagehash`、Gemini 相关依赖，上传可能表面成功、实际失败。
2. 用 `fuser -k <port>/tcp` 释放端口；`pkill -f web/server.py` 可能留下绑定。
3. `inkcal run` 有 flock 互斥锁（`data/inkcal-run.lock`）：Luna harness 一轮可跑 ~11 分钟，超过 cron 10 分钟间隔时重叠 run 会直接退出，防止重复入库与孤儿审计决策。若锁残留（进程被 kill -9），手动删除 lockfile 即可。
4. SigLIP2 对透明杯饮料、咖啡、奶茶等有漏检；“选择照片”是预期补救，不要删。
5. Gemini 会把截图、菜单、海报、包装等判成 `not real food`；这必须跳过，不能建记录。
6. SQLite 使用 WAL、`check_same_thread=False`；服务运行时不得删除 `.db-wal` / `.db-shm`。
6b. **变更 FTS 虚拟表结构（重建 `records_fts`、改触发器）必须先停 Flask server 再迁移**。2026-09-13 在 server 运行中重建 FTS5 虚拟表，导致跨表写入触发器损坏（UPDATE 触发 FTS 写入报 `database disk image is malformed`，表本身 quick_check 却 OK，热修无效）。最终走「干净导出业务表 → 全新 init_db → 导入 → 重建 FTS」无损恢复。加列（`ALTER TABLE ADD COLUMN`）类迁移可在线做，重建虚拟表/触发器不行。
7. `inkcal migrate` 检测到已有数据库会拒绝；`--force` 会清空再迁移，只能在确有意图时使用。
8. `~/Coding/food-classifier/` 是独立的 SigLIP2 微调项目，模型产物写入本项目 `data/finetuned-model/` 并由检测器自动加载。
9. **Luna 网关静默忽略 `previous_response_id`**（详见 §5）。症状是聊天"失忆"或批处理悄悄降级回 Gemini，**不报错**。换 endpoint 后必须实测：带 `previous_response_id` 问上一轮内容 + 确认图片进缓存，再看 `agent_decisions` 是否有新行。模型 id 也用连字符形式（`gpt-5-6-luna`），点号形式会被上游拒为 `unknown provider for model`。

---

## 9. 提交规范与完成检查

- 只按文件名 `git add`；**绝不** `git add .` / `git add -A`。
- 不提交 `.env`、`data/`、`web/ui/node_modules/`。
- Vue 源码变更后必须运行构建并同时提交 `web/static/` 产物（`index.html` 与 `assets/`），否则生产页面不会更新。
- **每次完成代码、配置、产品决策或实施状态的修改后，都必须在同一工作单元内更新本 `AGENTS.md`。** 状态、当前优先级、已完成/未完成项、接口或运行方式发生变化时必须同步；若确认无需更新，也应在交付前明确复核其内容仍与当前 HEAD 一致。不要把交接文档更新留给下一位 agent。
- 提交信息使用简短祈使句；追加：

```text
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

最小检查集：

```bash
git diff --check
PYTHONPATH=. venv/bin/python scripts/test_contract_parse.py
npm --prefix web/ui run build
venv/bin/python -m compileall -q main.py src web/server.py
```

涉及 Web 路由时，使用 Flask `test_client()`（在已认证 session 中）确认 `/`、`/app/` 重定向、相关 `/api/*` 返回预期；不要把项目 API key 或登录密码打印进日志/聊天。

---

## 10. 深入资料索引

- [`docs/prototypes/two-tab-proto.html`](./docs/prototypes/two-tab-proto.html)：已确认 UI 原型。
- [`DEVELOPMENT.md`](./DEVELOPMENT.md)：项目早期技术沿革与事故复盘，需要背景时再查。
- [`references/pipeline-web.md`](./references/pipeline-web.md)：照片管线、部署与环境变量。
- [`references/cli-workflows.md`](./references/cli-workflows.md)：CLI/NL 记录工作流。
