# inkcal

> **拍完就记好** —— 本地优先、隐私友好的自动饮食热量记录器。

手机拍照自动同步到 [Immich](https://immich.app/) 或 [PhotoPrism](https://www.photoprism.app/)，定时任务拉取新照片：先在**本机 CPU** 用 SigLIP2 过滤掉非食物照片（绝不出内网），再交由视觉模型完成同餐合并与热量 / 宏量营养素估算，最终落盘到本地 SQLite。打开网页或原生 Android App 即可浏览摄入、查看热量缺口、纠错或与饮食助手 **Calo** 对话。

---

## 核心特性

- **零摩擦自动记账**：无需打开 App 拍照或手动填表，日常随手拍食物即可由 `cron` 自动入库；同一张照片通过 `asset_id` 保证幂等，删除后自动进入忽略列表不再重复同步。
- **隐私门槛留在本地**：非食物照片在本地 CPU 上即被 `Food-or-Not-SigLIP2` 拦截，不会上传到任何外部模型接口；仅当用户主动从相册挑图或手动上传补漏时才绕过本地过滤。
- **同餐多图智能归组**：支持将同一餐的多张照片自动归入同一张卡片（`×N`），区分「吃前 / 吃后状态延续（联合对比实吃量）」与「同餐分拍不同菜品（独立条目累加）」，重分析自动按整组照片联合重估。
- **热量缺口与多维视图**：日 / 周 / 月三视图联动——结合个人体征算出的基础代谢（BMR）与每日活动消耗（Burn），直观展示 TDEE、当日及累计热量缺口、周双层柱状图与月度进度环。
- **Calo 对话助手**：用自然语言查记录、算统计、纯文本补录（无图自动配 Emoji）、修改或重新分析；遵循安全删除契约，删除只能生成二次确认卡，必须由用户点击确认后才执行。
- **Web + 原生 Android 双端**：Vue 3 响应式网页（桌面端三栏布局 + 移动端三 Tab）与原生 Android 客户端（Kotlin + Jetpack Compose + Material 3），两端共享同一套 Flask JSON API。

---

## 工作原理

```text
Immich / PhotoPrism（相册自动备份）
  │
  ▼
SigLIP2（本机 CPU 食物过滤，非食物不出内网）
  │
  ▼
Luna（可选 · AGENT_ENABLED=1：视觉编排，仅判断新餐 / 同餐 / 跳过）
  │
  ▼
Gemini（数值专家：估算短标题、菜品明细、热量与 P / C / F）
  │
  ▼
SQLite（data/inkcal.db，WAL 模式 + FTS5 全文检索）
  │
  ▼
Flask JSON API
  ├── Web UI（web/，Vue 3 + Vite）
  └── Android App（android/，Kotlin + Jetpack Compose）
```

**职责严格解耦**：Luna 只管多图之间的餐次关系，不编造热量；Gemini 只管根据照片估算营养数值，不决定同餐归属。默认 `AGENT_ENABLED=0`，食物照片直送 Gemini（单张成条）；开启 `AGENT_ENABLED=1` 后启用同餐归组，批处理异常时自动降级回单图直发路径。

---

## 客户端

### Web 端（Vue 3）

- **记录**：日视图无限滚动时间轴（吸顶日期汇总与缺口标签）、周视图双层摄入/消耗柱状图、月视图二值缺口圆环日历；卡片点开可看大图画廊、逐张明细、AI 决策审计，并支持组级重新分析、单张移除与整餐删除。
- **Calo**：桌面端常驻右侧栏，移动端独立 Tab；支持多会话切换、工具调用步骤折叠、结果产物卡片分流与删除确认卡。
- **选择照片补漏**：支持从相册按天浏览全量照片（已入库自动置灰标注，支持一次多选 ≤ 10 张）或本地上传（自动读 EXIF 定日期，无 EXIF 可手动修正）。
- **设置**：维护身高 / 体重 / 出生日期 / 性别（用于计算 BMR）以及 Calo 上下文窗口长度。

### 原生 Android 客户端（`android/`）

基于 Kotlin + Jetpack Compose + Material 3 独立构建，仅调用 Flask API，不套壳 WebView：

- **功能完整覆盖**：日 / 周 / 月三视图（含冷启动缓存、下拉刷新与左右滑切周/月）、独立详情页（`MealDetailActivity`，由 Android 系统原生接管跨 Activity 预测性返回）、长按快捷菜单、全量相册多选与系统照片选择器上传、Calo 聊天、设置页与前台 30 秒自动同步。
- **获取与更新**：
  - 直接从 [GitHub Releases](https://github.com/JerryLF7/inkcal/releases/latest) 下载最新 APK；
  - 推荐使用 [Obtainium](https://github.com/ImranR98/Obtainium) 订阅本仓库自动跟进版本更新。
  - 首次启动填入自建服务地址（局域网 `IP:端口` 或反代域名）并按需登录即可。

> Android 客户端详细规格、API 契约与演进记录见 [`docs/android-app-spec.md`](docs/android-app-spec.md)。

---

## 快速部署

### 1. 环境准备

- Python 3.11+
- 已部署的 Immich 或 PhotoPrism 实例
- OpenAI 兼容格式的视觉模型 API（用于 Gemini 热量估算；启用同餐编排时另需 Luna 接口）

```bash
git clone https://github.com/JerryLF7/inkcal.git
cd inkcal

python3 -m venv venv
venv/bin/pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，填入照片源与模型凭据
```

> 所有 Python 命令请统一使用 `venv/bin/python`，避免系统 Python 缺少图像处理依赖导致隐性失败。首次运行 SigLIP2 时会自动从 HuggingFace 拉取权重并缓存到本地。

### 2. 配置定时流水线

```bash
./setup.sh
```

脚本会创建 `~/.local/bin/inkcal` 包装器（自动激活 `venv`），并幂等添加每 10 分钟执行一次 `inkcal run` 的 `crontab` 任务。

### 3. 启动 Web 服务

本地调试：

```bash
INKCAL_PORT=5800 venv/bin/python web/server.py
```

生产环境请交给 `systemd` 用户服务托管（如 `systemctl --user restart inkcal-web.service`），不要长期手动前台启动，以免与托管进程争抢端口或持住 SQLite 写锁。

服务默认仅监听 `127.0.0.1:5800`。如需通过公网或手机访问，请在前面放置 Caddy / Nginx 等 HTTPS 反向代理，并务必开启登录鉴权（设置 `INKCAL_USER`、`INKCAL_PASS`、`INKCAL_SECRET` 与 `INKCAL_HTTPS=1`）。

### 常用环境变量

完整说明见 [`.env.example`](.env.example)：

| 变量 | 说明 |
|---|---|
| `SOURCE` | 启用的照片源：`immich`、`photoprism` 或 `immich,photoprism` |
| `IMMICH_URL` / `IMMICH_API_KEY` | Immich 服务地址与 API Key |
| `PHOTOPRISM_URL` / `PHOTOPRISM_API_KEY` | PhotoPrism 服务地址与 App Password（按需） |
| `GEMINI_API_KEY` / `GEMINI_BASE_URL` / `GEMINI_MODEL` | 热量估算模型配置（OpenAI 兼容格式） |
| `GEMINI_REASONING_EFFORT` | 推理强度（`none`/`minimal`/`low`/`medium`/`high`，默认 `high`，改后实时生效无需重启） |
| `FOOD_THRESHOLD` | SigLIP2 本地食物过滤阈值（`0~1` 小数，默认 `0.35`，改后实时生效） |
| `AGENT_ENABLED` / `LUNA_*` | 是否开启 Luna 批处理同餐编排（默认 `0` 关闭）及接口配置 |
| `INKCAL_USER` / `INKCAL_PASS` | Web/API 登录账号密码（必须同时设置或同时留空，自带防爆破限速） |
| `INKCAL_SECRET` | Flask 会话签名密钥，务必设为固定随机串（变动会导致登录态失效） |
| `INKCAL_HOST` / `INKCAL_PORT` / `INKCAL_HTTPS` | 服务绑定地址、端口及是否位于 HTTPS 反代之后 |

---

## 命令行（CLI）

安装完 wrapper 后可直接使用 `inkcal`（等价于 `venv/bin/python main.py`）：

```bash
# 流水线与排障
inkcal run                                  # 立即处理今日新照片（支持 --date YYYY-MM-DD）
inkcal explain --date 2026-11-23            # 查看当天每张照片在流水线中的去向
inkcal explain --id <asset_id>              # 追踪单张照片状态
inkcal decisions --date 2026-11-23          # 查看 Luna 当天决策审计
inkcal analyze --id <asset_id>              # 绕过本地过滤强制分析某张照片

# 查询与统计（均支持 --json）
inkcal view --date 2026-11-23               # 查看单日；另支持 --week / --month YYYY-MM / --from --to
inkcal stats --last 7d --group-by day       # 区间汇总（支持 7d / 2w / 1m）
inkcal search 咖喱                          # FTS5 全文检索餐名与明细

# 录入、纠错与分组
inkcal add --meal "冰美式" --calories 15 --protein 0 --carbs 3 --fat 0
inkcal edit --last --new-meal "拿铁" --calories 180
inkcal reanalyze --last --notes "米饭只吃了一半"
inkcal merge <主asset_id> <从asset_id>      # 并入同餐（默认清零从行；加 --keep 保留独立数值）
inkcal delete --meal 汉堡 --date 2026-11-23 # 删除整餐并忽略资产（加 --photo 仅移单张）
inkcal burn --date 2026-11-23 --kcal 480 --steps 8200
```

修改、重分析与删除类命令支持四种记录定位方式：`--ref <记录ID>`、`--id <asset_id前缀>`、`--last`、`--meal <关键词> [--date <日期>]`；关键词命中多条时会列出候选提示改用精确 `--ref`。

---

## 核心设计约束

- **拍摄地当地日历日**：餐食归属严格以照片拍摄地钟表日期为准（`photo_time` 前 10 位 `YYYY-MM-DD`），不向 UTC 折算，防止跨零点 / 凌晨照片倒退到前一天。
- **幂等与防复生**：所有照片以 `asset_id` 去重；通过 CLI / Web / App 删除记录时，关联资产会自动写入 `ignored_assets`，后续定时任务不会再次入库。
- **数据写入边界**：请始终通过 `inkcal` CLI、`src/db.py` 或 Flask API 修改数据，不要用 SQLite shell 直接篡改表，也不要在服务运行时手动删除 `data/` 下的 `.db-wal` / `.db-shm` 文件。

---

## 本地开发与测试

### 仓库结构

```text
main.py           CLI 入口与批处理决策落地
src/              核心业务（db、照片源客户端、SigLIP2、Gemini、Luna harness、Calo 聊天）
src/prompts/      提示词模板（analyze.md / reanalyze.md / analyze_text.md）
web/server.py     Flask JSON API 与静态资源托管
web/ui/           Vue 3 + Vite 前端源码
web/static/       Vue 生产构建产物（随仓库提交，Flask 直接提供）
android/          原生 Android 客户端（独立 Gradle 工程）
scripts/          隔离库回归测试与每日消耗同步脚本
docs/             Android 客户端规格书、事故复盘、照片库 API 参考与 UI 原型
```

### 前端构建

```bash
npm --prefix web/ui install
npm --prefix web/ui run build    # 构建产物输出到 web/static/
```

### Android 构建与单测

```bash
cd android
./gradlew :app:testDebugUnitTest
./gradlew :app:assembleRelease
```

### 后端回归测试

所有日常回归均使用隔离临时数据库，不触碰生产 `data/inkcal.db`：

```bash
PYTHONPATH=. venv/bin/python scripts/test_reasoning_effort.py
PYTHONPATH=. venv/bin/python scripts/test_food_threshold.py
PYTHONPATH=. venv/bin/python scripts/test_contract_parse.py
PYTHONPATH=. venv/bin/python scripts/test_merge_groups.py
PYTHONPATH=. venv/bin/python scripts/test_lightbox_smoke.py
PYTHONPATH=. venv/bin/python scripts/test_legacy_path.py
PYTHONPATH=. venv/bin/python scripts/test_chat_smoke.py
PYTHONPATH=. venv/bin/python scripts/test_group_reanalyze.py
PYTHONPATH=. venv/bin/python scripts/test_daily_burn.py
```

---

## 延伸文档

- [`AGENTS.md`](AGENTS.md) —— 工程约束、架构决策、运行排障与历史事故护栏（修改代码前请先阅读）
- [`docs/android-app-spec.md`](docs/android-app-spec.md) —— Android 原生客户端功能规格、API 契约与版本演进
- [`docs/references/`](docs/references/) —— PhotoPrism 与 Synology Photos API 调研记录
