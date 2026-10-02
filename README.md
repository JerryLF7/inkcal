# inkcal

拍一张饮食照片,热量自动记好。

> **还在开发中,功能不完整。** 接口、数据格式和界面都可能随时改,不要拿它当成品用。
> 后端(Python/Flask + Vue 网页)已能日常使用;原生 Android 客户端还很早期,`docs/android-app-spec.md` §14 有逐项进度。已知没做的:周视图、月视图、选择照片、Calo 聊天。

手机把照片备份到 Immich 或 PhotoPrism,inkcal 每 10 分钟去拉一次新照片,判断是不是食物,估算热量和蛋白质、碳水、脂肪,写进本地 SQLite。打开网页就能看,估错了可以改。

我做它是因为手动记饮食坚持不下去,而把食物照片直接传给云端又不放心。所以有一道本地过滤:不是食物的照片不会离开你的内网。

## 处理流程

```
Immich / PhotoPrism
  → SigLIP2      本机 CPU 判断是不是食物,不是就丢弃
  → Luna         可选。判断同餐、新餐还是跳过,只负责编排
  → Gemini       估算热量和宏量营养素
  → SQLite       data/inkcal.db
  → Flask API + Vue 页面
```

Luna 和 Gemini 各管一段:哪几张照片算一餐由 Luna 判断,热量数字只由 Gemini 给,两边不越界。Luna 默认关着(`AGENT_ENABLED=0`),这时食物照片直接送 Gemini,一张一条记录。

## 快速开始

需要 Python 3.11 以上,以及一个 Immich 或 PhotoPrism。

```bash
git clone https://github.com/JerryLF7/inkcal.git
cd inkcal
python3 -m venv venv
venv/bin/pip install -r requirements.txt

cp .env.example .env    # 填上照片源和 Gemini 的地址、密钥
./setup.sh              # 生成 ~/.local/bin/inkcal,并加一条每 10 分钟的 cron
```

所有 Python 命令都用 `venv/bin/python` 跑。系统自带的 Python 缺 `pillow-heif`、`imagehash` 这些依赖,上传和 HEIC 处理会悄悄失败。

第一次用 SigLIP2 会从 HuggingFace 下载模型,之后走本地缓存。

启动网页:

```bash
INKCAL_PORT=5800 venv/bin/python web/server.py
```

默认只监听本机 `127.0.0.1:5800`。长期运行请交给 systemd 用户单元(`systemctl --user restart inkcal-web.service`),不要手动起进程。手动起的进程一旦占住端口,systemd 那份会不停重启,孤儿进程还可能一直握着数据库写锁,让 cron 静默失败。

## 配置

全部写在 `.env` 里,完整清单以 `.env.example` 为准。最常改的几项:

| 变量 | 作用 |
|---|---|
| `SOURCE` | 照片源,`immich`、`photoprism` 或 `immich,photoprism` |
| `IMMICH_URL` `IMMICH_API_KEY` | Immich 地址和密钥 |
| `PHOTOPRISM_URL` `PHOTOPRISM_API_KEY` | 用 PhotoPrism 时才需要 |
| `GEMINI_API_KEY` `GEMINI_BASE_URL` `GEMINI_MODEL` | 热量估算,走 OpenAI 兼容格式 |
| `LUNA_*` `AGENT_ENABLED` | Luna 的接入和开关,默认关闭 |
| `INKCAL_USER` `INKCAL_PASS` | 网页登录。要么都填,要么都空 |
| `INKCAL_SECRET` | 会话签名密钥,必须固定,否则每次重启都要重新登录 |
| `INKCAL_HOST` `INKCAL_PORT` | 监听地址和端口 |
| `INKCAL_HTTPS` | 放在 HTTPS 反向代理后面时设为 1 |

Flask 自带的服务器不适合直接暴露到公网。要从手机或外网访问,请挂 Caddy 或 nginx 之类的反向代理,并打开登录。

## 命令行

```bash
inkcal run                          # 跑一遍流水线(cron 就是调它)
inkcal view --date 2026-09-30       # 看某天;还有 --week、--month、--from/--to
inkcal stats --last 7d --group-by day
inkcal search 咖喱                  # 全文搜索餐名和明细

inkcal add --meal "拿铁" --calories 190 --protein 9 --carbs 15 --fat 10
inkcal edit --last --new-meal "美式" --calories 5
inkcal reanalyze --last --notes "米饭只吃了一半"
inkcal delete --meal 汉堡 --date 2026-09-30
inkcal merge <主记录> <从记录>       # 把两张照片并成同一餐

inkcal analyze --id <asset_id>      # 强制分析被过滤器漏掉的照片
inkcal explain --id <asset_id>      # 这张照片在流水线里去哪了
inkcal decisions --date 2026-09-30  # Luna 当天的决策记录
inkcal burn --date 2026-09-30 --kcal 480 --steps 8200
```

读命令都支持 `--json`。改、删、重估这类命令用四种方式指定记录:`--ref <记录 ID>`、`--id <asset_id 前缀>`、`--last`、`--meal <关键词> --date <日期>`。关键词匹配到多条时会列出候选,让你换成精确的 `--ref` 再执行。

## 网页

底部有三个 Tab(桌面端 Calo 固定在右侧)。

记录页按日、周、月看餐食。每餐一张卡片,点开能看大图、逐张照片的明细和 AI 的决策过程,也可以在这里重新分析或删除。

Calo 是对话助手。你可以问"昨天午餐吃了什么",或者说"记一下下午吃了包薯片",它会去查库、估算、写入。它不能自己删记录,只能弹出确认卡,由你点了才删。

设置页填身高、体重、出生日期和性别,用来算基础代谢(BMR),也能调 Calo 记住多少轮对话。

日视图和周视图会显示热量缺口:总消耗 = 基础代谢 + 当天活动消耗,缺口 = 总消耗 − 摄入。没填体征时按固定 2500 kcal 兜底。

「选择照片」按钮(桌面在左侧栏,手机在顶栏)用来补漏。SigLIP2 对透明杯饮料、咖啡、奶茶偶尔判不准,你可以从相册里手动挑,或者本地上传,这些照片会跳过食物过滤。

## Android 客户端

`android/` 是原生客户端(Kotlin + Jetpack Compose),只调 Flask API,不共享 Python 或 Vue 代码。

**还没做完**,目前可用的是记录页日视图和餐卡详情(查看、重新分析、删除);周视图、月视图、选择照片、Calo 聊天都还没实现,设置页只有体征参数和服务器两项。

安装包从 [Releases](https://github.com/JerryLF7/inkcal/releases/latest) 下载,也可以把本仓库地址加进 [Obtainium](https://github.com/ImranR98/Obtainium) 自动跟进更新。首次启动填服务器地址(局域网 `IP:端口`,或反代域名)再登录。

自己构建需要 Android SDK;构建、签名和发布方式写在 `AGENTS.md` 里。

## 几个容易踩到的点

日期按照片拍摄地的当地日历日算,不按 UTC,所以凌晨拍的照片不会被算到前一天。

每张照片靠 `asset_id` 去重。删掉一条记录后,那张照片会进忽略列表,cron 不会再把它捡回来。

同一餐的多张照片挂在一条主记录下(`records.merged_into`),页面上只显示一张卡片,右上角有 `×N`。

改数据请走命令行或网页,不要直接开 SQLite 改。服务在跑的时候也别删 `data/` 下的 `.db-wal` 和 `.db-shm`。

更细的规则和踩过的坑在 `AGENTS.md`。

## 开发

```bash
npm --prefix web/ui install
npm --prefix web/ui run build       # 产物写到 web/static/,需要一并提交
```

前端是 Vue 3 + Vite,源码在 `web/ui/src/`。`web/static/` 是构建产物,生产环境直接用它,所以改了前端要重新构建并提交。

回归测试(都用隔离的临时数据库,不碰真实数据):

```bash
PYTHONPATH=. venv/bin/python scripts/test_food_threshold.py
PYTHONPATH=. venv/bin/python scripts/test_contract_parse.py
PYTHONPATH=. venv/bin/python scripts/test_merge_groups.py
PYTHONPATH=. venv/bin/python scripts/test_lightbox_smoke.py
PYTHONPATH=. venv/bin/python scripts/test_legacy_path.py
PYTHONPATH=. venv/bin/python scripts/test_chat_smoke.py
PYTHONPATH=. venv/bin/python scripts/test_group_reanalyze.py
PYTHONPATH=. venv/bin/python scripts/test_daily_burn.py
```

`test_cross_batch_update.py` 会真的调用 Luna 和 Gemini,需要网关可用,跑一次大约一分半钟,不适合放进日常回归。

代码布局:

```
main.py            命令行入口
src/               业务逻辑:数据库、照片源、食物检测、热量估算、Luna 批处理、聊天
src/prompts/       提示词模板(.md)
web/server.py      Flask API
web/ui/            Vue 前端源码
web/static/        前端构建产物
android/           原生 Android 客户端(独立 Gradle 根)
scripts/           回归测试和热量消耗同步脚本
docs/              界面原型、照片库 API 备忘、Android 客户端实现文档
```

## 相关文档

- `AGENTS.md`:项目的交接说明,包含已拍板的规则、事故复盘和下一步。改代码前先读它。
- `docs/android-app-spec.md`:Android 客户端的实现规格与进度。
- `docs/references/`:PhotoPrism 和 Synology Photos 的 API 备忘。
