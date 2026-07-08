# inkcal 开发总结

## 项目目的

自动追踪每日饮食热量。手机拍照后照片自动进入 Immich（自建照片库），流水线定时拉取 → 本地 AI 判断是否食物 → 云端 AI 分析具体吃了什么、多少热量 → 记入日志。核心解决两个痛点：

1. 手动记录饮食太麻烦，坚持不下去
2. 食物照片上传到云端分析有隐私顾虑

## 时间线

| 日期 | 阶段 |
|------|------|
| 04-29 上午 | 项目启动，命名 foodlens → inkcal |
| 04-29 深夜 | 第一版分类器用 moondream，效果差，换成 SigLIP2 |
| 04-30 早上 | CLI 成型（run / view / add），配 SKILL.md |
| 04-30 晚上 | Web UI：日历、卡片、灯箱、标注、换图 |
| 04-30 深夜 | pHash 匹配、登录验证 |
| 05-01 | 文档整理、CLI 补全 label/replace 命令 |
| 05-02 | setup.sh、cron 自动化、项目总结 |
| 05-04 | 手动上传（拖拽/粘贴/选文件）+ Immich pHash 匹配 |
| 05-04 | PC 端响应式布局（侧边栏日历 + 双列卡片） |
| 05-04 | FRP 优化（缩略图缩小 20x、请求排序、加载反馈） |
| 05-05 | 网络韧性：AbortController 超时重试、localStorage 缓存优先、手动刷新按钮 |
| 05-12 | JSON → SQLite 迁移：解决数据量增长后的查询效率和并发写入问题 |
| 05-13 | PhotoPrism 多源支持：通过 `SOURCE=immich,photoprism` 同时拉取多个相册 |
| 05-13 | 「选择照片」弹窗：从相册挑选被 SigLIP2 漏检的照片，跳过食物检测直接送 Gemini；按日期分组 + 滚动分页加载 |
| 05-13 | 项目改名：intake → inkcal（统一项目名、CLI、数据库、GitHub 仓库、本地目录）|

## 架构

```
拍照 → Immich(照片库) → SigLIP2(本地CPU,判断是否有食物) → Gemini(云端,热量分析) → SQLite (data/inkcal.db)
                              ↑ 不是食物就跳过                    ↑ 仅食物照片才发出
```

**总代码量：~3900 行**（Python ~2100，前端 ~1750）

## 技术选型与踩坑

### 1. 食物分类器：moondream → SigLIP2

最初用 moondream 小视觉模型做食物判断。问题：
- 推理慢（~2s/张），一天几十张照片等太久
- 准确率一般，经常把非食物判成食物

换成 `prithivMLmods/Food-or-Not-SigLIP2`：
- CPU 推理 ~0.3s/张，快 6 倍
- 专为食物/非食物二分类训练，准确率明显更高
- 支持本地微调，可以持续改进

**教训：** 不要用通用模型做特定分类任务，找专门训练的模型省时省力。

### 2. Gemini prompt 防误识别

SigLIP2 过滤后仍有漏网之鱼（截图、菜单、海报）。在 Gemini system prompt 里加了明确的拒绝列表：

```
拒绝以下内容：截图、UI、社交媒体、包装、海报、菜单、
屏幕上的食物、绘画、游戏画面、打印照片
```

这套 prompt 大幅降低了误报，比调模型阈值更有效。

**教训：** 分类器做不到 100%，多一层 LLM 兜底很有必要。prompt 里直接列出要拒绝的场景比抽象描述管用。

### 3. 替换图片的 pHash 匹配

用户上传替换图片后，最初方案是存到本地 `data/images/`。但用户指出：上传的图一定来自 Immich，应该直接匹配原图，避免重复存储。

实现：
- 用 `imagehash.phash()` 算感知哈希
- 从上传图片的 EXIF 提取拍摄时间，±5 分钟窗口搜索 Immich
- 汉明距离 ≤12 即匹配，≤2 直接确认
- 匹配成功替换 asset_id 和 thumbnail_url，不存本地文件

**教训：** 利用已有数据（Immich 照片库 + EXIF 时间戳）可以大幅缩小搜索范围，避免 O(n) 遍历和重复存储。

### 4. 标注数据持久化

标注数据写入 SQLite `records` 表的 `user_label` 字段：

```sql
UPDATE records SET user_label = 'correct' WHERE asset_id = '...';
```

好处：
- 原子操作，并发安全
- 按日期/按前缀查询高效（有索引）
- 与记录数据在同一行，无需跨文件关联

**教训：** 简单场景下 JSON 文件 + 约定字段够用，但当数据量增长后（跨日期查询、并发写入、复杂聚合），尽早迁移到 SQLite 可以避免后期技术债。`sqlite3` 是标准库，零额外依赖。

### 5. JSON → SQLite 迁移

**背景：** 随着记录积累，JSON 文件的几个问题变得不可忽视：
- **跨日期查询慢**：`get_available_dates()` 需要遍历所有 `.json` 文件
- **并发写入不安全**：cron 和 web 同时写入同一文件可能损坏数据
- **无法做复杂聚合**：按日期范围统计、JOIN 查询等需要手动实现

**方案：**
- 使用 Python 标准库 `sqlite3`，零额外依赖
- Schema：三张表 `records` / `reanalysis_history` / `ignored_assets`
- WAL 模式 + `check_same_thread=False` 支持 Flask 多线程
- 所有查询函数返回的 dict 与旧 JSON 格式完全一致，前端零改动

**关键决策：**
1. **连接管理**：模块级懒加载连接。CLI 每次操作后自然退出即关闭；Flask 进程长期持有。
2. **日期派生**：`date` 列从 `photo_time` 解析（取 `YYYY-MM-DD`），写入时自动计算，不依赖外部传入。
3. **is_manual 计算列**：根据 `asset_id.startswith('manual-')` 自动设置。
4. **reanalysis_history 透明嵌入**：`get_records_by_date()` 批量 JOIN 历史表，`_record_from_row()` 自动组装为列表，调用方无感知。

**迁移命令：**
```bash
inkcal migrate        # 首次迁移
inkcal migrate --force # 强制重新迁移（会清空现有 DB）
```

**教训：** 标准库 `sqlite3` 的门槛足够低，不必为了"简单"而坚持 JSON。当数据操作涉及遍历、并发、或跨文件关联时，尽早迁移到 SQLite 可以避免后期技术债。

### 5. 多源相册支持（Immich + PhotoPrism）

**背景：** 用户同时使用多个照片管理服务（Immich 手机备份 + PhotoPrism 相机导入），需要统一汇总食物照片。

**方案：**
- `SOURCE=immich,photoprism` 环境变量控制启用哪些来源，逗号分隔
- `_resolve_sources()` 统一解析逻辑，`main.py` 和 `server.py` 共用
- 每个 source 独立运行完整 pipeline（`get_date_assets` → 食物检测 → Gemini），错误互不影响
- `asset_id` 字段同时容纳 Immich UUID 和 PhotoPrism UID，格式不同天然不会冲突
- `already_processed()` 按日期过滤，多源之间不会重复处理同一张照片

**PhotoPrism 与 Immich 的关键差异：**
| 维度 | PhotoPrism | Immich |
|------|-----------|--------|
| 认证 | `Authorization: Bearer` | `x-api-key` |
| 搜索 | `GET /api/v1/photos?q=after:...` | `POST /api/search/metadata` |
| 缩略图 key | 文件 SHA1 `hash` | `asset_id` |
| 缩略图 URL | `/api/v1/t/{hash}/{token}/{size}` | `/api/assets/{id}/thumbnail` |
| pHash 搜索 | ❌ 无此 API | ✅ 有搜索+pHash 匹配 |

**教训：** 多源支持的核心是统一接口层。`PhotoPrismClient` 的 `get_date_assets()` / `download_thumbnail()` / `download_original()` 签名与 `ImmichClient` 对齐，pipeline 和 web 端都能无缝切换。

### 6. 「选择照片」弹窗 — 补漏设计

**背景：** SigLIP2 对饮品（奶茶、咖啡、瓶装饮料）漏检率高。用户不想手动上传，希望直接从相册里选漏掉的照片。

**方案：**
- Web UI 的「上传」改为「选择照片」，点击弹出相册缩略图弹窗
- 弹窗显示**所有日期**的未处理照片，按日期分组，**滚动到底自动加载**更早的 7 天
- 点击缩略图 → 后端下载原图 → **跳过食物检测直接送 Gemini** → 保存记录
- 弹窗底部保留「从本地上传」按钮，兜底不在相册里的图片

**为什么跳过食物检测？**
- 用户主动从相册里选了一张照片 = 已经确认是食物
- 此功能的唯一目的就是补 SigLIP2 的漏，再跑一次食物检测毫无意义
- 简化流程：下载原图 → Gemini → 保存，三步完成

**后端分页设计：**
- `GET /api/album-photos?cursor=YYYY-MM-DD&days=7`
- 从 cursor 日期往回查 7 天，每天对每个源调用 `get_date_assets()`
- 过滤已处理（`db.get_processed_asset_ids(date_str)`）和已忽略的
- 返回按日期分组的列表，`next_cursor` 供下一页使用

**Race-condition 防护：**
- 用户打开弹窗后、cron 可能在后台处理掉同一批照片
- `POST /api/analyze-album-photo` 在 Gemini 之前再次检查 `db.get_record_by_asset_id()`，已存在则返回 409

**教训：**
1. 用户主动确认的操作不需要 AI 二次确认，直接放行更流畅
2. 无限滚动比一次性加载所有日期更实用 — 相册照片可能跨越数月，分页避免长时间白屏
3. 每个日期独立查询相册 API 虽然调用次数多，但局域网延迟低，弹窗可以容忍 1-2s 的加载时间

### 7. Flask session 丢失

登录后过一会又要重新登录。原因：`app.secret_key` 用 `secrets.token_hex(32)` 每次重启随机生成，导致旧 session cookie 签名失效。

修复：在 `.env` 里加 `INKCAL_SECRET` 固定值。

**教训：** Flask session 依赖 secret_key 签名，每次重启换 key 会让所有已登录用户掉线。开发和文档里容易忽略这个细节。

## 各模块实现思路

### main.py — CLI 入口

6 个子命令，全部通过 argparse 注册。核心设计：

- **多源 pipeline**：`cmd_run()` 创建 detector + analyzer 各一次，遍历所有启用的 source（Immich/PhotoPrism），每个 source 独立跑 `_run_source()`。错误隔离：一个 source 失败不影响其他 source。
- **幂等性**：`already_processed()` 从 SQLite 查询当日已有 `asset_id`，流水线只处理新照片。cron 每 10 分钟跑一次不会重复。
- **时区**：全部 Asia/Hong_Kong (UTC+8)，日期边界按 HKT 计算。
- **手动记录**：生成 `manual-时间戳` 作为 asset_id，与 Immich/PhotoPrism 记录同 schema 存储。

### src/immich_client.py — Immich API 封装（~140行）

- 基于 `httpx.Client`，同步请求，30s 超时
- 分页遍历：自动翻页直到返回空列表
- pHash 匹配：下载缩略图 → 算哈希 → 汉明距离比较，distance≤2 提前退出
- EXIF 提取：静态方法，用 PIL 读 `DateTimeOriginal`（标签 36867）
- `format_photo_time()` 处理 Immich 的 `UTC+8` 和 IANA 时区名（如 `Asia/Shanghai`）

### src/photoprism_client.py — PhotoPrism API 封装（~160行）

- 基于 `httpx.Client`，请求头 `Authorization: Bearer <app_password>`
- Token 管理：从搜索响应 `X-Preview-Token` 提取缩略图 token，自动缓存
- `TakenAtLocal` 解析：trailing `Z` 是格式占位符，真实时区来自 `TimeZone` 字段（IANA 名）
- 缩略图 URL：`/api/v1/t/{hash}/{token}/{size}`，cookie-free，无需额外 auth header
- 与 `ImmichClient` 接口对齐：`get_date_assets()` / `download_thumbnail()` / `download_original()` / `close()`

### src/food_detector.py — 食物检测（60行）

- 延迟加载 torch/transformers（只在实际调用时 import，加快 CLI 启动）
- 模型路径优先级：本地微调模型 > HuggingFace 基础模型
- `is_food()` 返回 bool，异常时返回 False（宁可漏过不可崩溃）

### src/calorie_analyzer.py — 热量分析（121行）

- OpenAI 兼容格式调 Gemini Vision API
- 图片 base64 编码 → data URL → `user` 消息中的 `image_url`
- 指数退避重试（2s/4s/8s/16s/32s，最多 5 次）
- `response_format={"type": "json_object"}` 强制返回结构化 JSON
- 解析失败返回零值，不阻塞流水线

### src/db.py — SQLite 数据层

- 零额外依赖，Python 标准库 `sqlite3`
- WAL 模式 (`PRAGMA journal_mode=WAL`) 支持并发读写
- `check_same_thread=False` 供 Flask 多线程共享连接
- 三个表：`records`（主记录）、`reanalysis_history`（重新分析历史，外键级联删除）、`ignored_assets`（忽略列表）
- `get_records_by_date()` 自动 JOIN `reanalysis_history` 并嵌入为列表，对外透明保持旧 JSON 格式
- `move_record()` 自动更新 `date` 和 `photo_time` 的日期部分，保留时间-of-day
- `get_processed_asset_ids(date_str)` — 返回某日已记录的 asset_id 集合，供 `_run_source()` 和 `/api/album-photos` 过滤已处理照片

### web/server.py + index.html — Web 界面（893 + 1754行）

- Flask 提供 REST API + 静态文件
- 前端纯原生 JS，无框架，暗色主题，响应式布局（移动端 480px + 桌面端双栏）
- 桌面端：左侧 280px 侧边栏（日历始终可见）+ 右侧双列卡片网格
- 日历用 CSS Grid 手写，有记录的日期显示绿点（仅计算非空记录）
- 灯箱：点击卡片 → 全屏大图（preview 尺寸）
- **选择照片弹窗**：从相册（Immich/PhotoPrism）挑选未处理照片，按日期分组，滚动分页加载。点击缩略图直接送 Gemini（跳过食物检测）。本地上传作为兜底
- 手动上传：拖拽/粘贴/选文件 → Gemini 分析 → Immich pHash 匹配 → 自动刷新
- 卡片缩略图用 `size=thumbnail` (7KB) 加速；图片加载失败自动重试
- 请求序号（`_loadSeq`）防止快速切换日期时旧响应覆盖新数据
- 图片代理：`/api/image?url=` 转发 Immich/PhotoPrism 请求，附加 API key（Immich only），避免前端暴露凭据
- 认证：Flask session + before_request 钩子，未登录重定向到 /login
- **localStorage 缓存优先**：所有日期统一 cache-first，缓存命中立即渲染，后台 fetch 静默更新。周视图按周一日缓存，日期列表 5 分钟 TTL。上传/替换图片后自动失效对应缓存。隐私模式下降级为纯网络请求
- **网络韧性**：`apiFetch()` 封装 AbortController 10s 超时 + 1 次自动重试。跨请求 abort（`_abortController`）取消旧导航的进行中请求。`_fetchId` 去重防止重试污染新视图
- **手动刷新**：日期标签旁的 ↻ 按钮清除当前日缓存后强制重新拉取，请求期间旋转动画

### setup.sh — 一键部署

- 创建 `~/.local/bin/inkcal` bash wrapper 脚本（调用 venv Python）
- 配置 crontab 每 10 分钟运行
- 幂等：重复执行不会重复添加

## 设计原则

1. **隐私优先**：分类器本地运行，图片不出内网；只有确认是食物的才发云端
2. **幂等**：所有操作可重复执行不产生副作用
3. **渐进增强**：基础功能靠 CLI，Web UI 是锦上添花
4. **持续改进**：标注积累数据，供独立训练项目使用以持续提升分类准确率
5. **简单存储**：SQLite（标准库 `sqlite3`，零依赖），满足查询效率和并发安全；原 JSON 文件作为人类可读备份保留
