# intake 开发总结

## 项目目的

自动追踪每日饮食热量。手机拍照后照片自动进入 Immich（自建照片库），流水线定时拉取 → 本地 AI 判断是否食物 → 云端 AI 分析具体吃了什么、多少热量 → 记入日志。核心解决两个痛点：

1. 手动记录饮食太麻烦，坚持不下去
2. 食物照片上传到云端分析有隐私顾虑

## 时间线

| 日期 | 阶段 |
|------|------|
| 04-29 上午 | 项目启动，命名 foodlens → intake |
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

## 架构

```
拍照 → Immich(照片库) → SigLIP2(本地CPU,判断是否有食物) → Gemini(云端,热量分析) → data/日期.json
                              ↑ 不是食物就跳过                    ↑ 仅食物照片才发出
```

**总代码量：~2600 行**（Python ~1190，前端 ~1410）

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

标注数据直接写回 `data/YYYY-MM-DD.json`：

```json
{
  "user_label": "correct",
  "replacement_image": null
}
```

好处：
- 不需要额外数据库或文件
- 程序重启不丢数据
- JSON 格式人类可读，出问题直接编辑

**教训：** 简单场景下，JSON 文件 + 约定字段比数据库更实用。未来数据量大了再迁移也容易（结构扁平、一对一映射）。

### 5. Flask session 丢失

登录后过一会又要重新登录。原因：`app.secret_key` 用 `secrets.token_hex(32)` 每次重启随机生成，导致旧 session cookie 签名失效。

修复：在 `.env` 里加 `INTAKE_SECRET` 固定值。

**教训：** Flask session 依赖 secret_key 签名，每次重启换 key 会让所有已登录用户掉线。开发和文档里容易忽略这个细节。

## 各模块实现思路

### main.py — CLI 入口（483行）

7 个子命令，全部通过 argparse 注册。核心设计：

- **幂等性**：`already_processed()` 从当日 JSON 提取已有 `asset_id`，流水线只处理新照片。cron 每 20 分钟跑一次不会重复。
- **时区**：全部 Asia/Hong_Kong (UTC+8)，日期边界按 HKT 计算。
- **手动记录**：生成 `manual-时间戳` 作为 asset_id，与 Immich 记录同格式存储。

### src/immich_client.py — Immich API 封装（143行）

- 基于 `httpx.Client`，同步请求，30s 超时
- 分页遍历：自动翻页直到返回空列表
- pHash 匹配：下载缩略图 → 算哈希 → 汉明距离比较，distance≤2 提前退出
- EXIF 提取：静态方法，用 PIL 读 `DateTimeOriginal`（标签 36867）

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

### web/server.py + index.html — Web 界面（460 + 1038行）

- Flask 提供 REST API + 静态文件
- 前端纯原生 JS，无框架，暗色主题，响应式布局（移动端 480px + 桌面端双栏）
- 桌面端：左侧 280px 侧边栏（日历始终可见）+ 右侧双列卡片网格
- 日历用 CSS Grid 手写，有记录的日期显示绿点（仅计算非空记录）
- 灯箱：点击卡片 → 全屏大图（preview 尺寸）
- 手动上传：拖拽/粘贴/选文件 → Gemini 分析 → Immich pHash 匹配 → 自动刷新
- 卡片缩略图用 `size=thumbnail` (7KB) 加速；图片加载失败自动重试
- 请求序号（`_loadSeq`）防止快速切换日期时旧响应覆盖新数据
- 图片代理：`/api/image?url=` 转发 Immich 请求，附加 API key，避免前端暴露凭据
- 认证：Flask session + before_request 钩子，未登录重定向到 /login
- **localStorage 缓存优先**：所有日期统一 cache-first，缓存命中立即渲染，后台 fetch 静默更新。周视图按周一日缓存，日期列表 5 分钟 TTL。上传/替换图片后自动失效对应缓存。隐私模式下降级为纯网络请求
- **网络韧性**：`apiFetch()` 封装 AbortController 10s 超时 + 1 次自动重试。跨请求 abort（`_abortController`）取消旧导航的进行中请求。`_fetchId` 去重防止重试污染新视图
- **手动刷新**：日期标签旁的 ↻ 按钮清除当前日缓存后强制重新拉取，请求期间旋转动画

### setup.sh — 一键部署（27行）

- 创建 `~/.local/bin/intake` 符号链接
- 配置 crontab 每 20 分钟运行
- 幂等：重复执行不会重复添加

## 设计原则

1. **隐私优先**：分类器本地运行，图片不出内网；只有确认是食物的才发云端
2. **幂等**：所有操作可重复执行不产生副作用
3. **渐进增强**：基础功能靠 CLI，Web UI 是锦上添花
4. **持续改进**：标注积累数据，供独立训练项目使用以持续提升分类准确率
5. **简单存储**：JSON 文件而非数据库，人类可读、易调试、易迁移
