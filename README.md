# inkcal

自动食物热量追踪流水线。

**拍照 → Immich/PhotoPrism → SigLIP2 本地过滤 → Gemini 分析热量 → SQLite**

## 架构

```
        ┌──────────┐     ┌──────────────┐     ┌─────────┐
 拍照 → │  Immich  │ ──→ │   SigLIP2    │ ──→ │ Gemini  │
        │PhotoPrism│     │ (本地过滤食物) │     │ (热量分析)│
        └──────────┘     └──────────────┘     └─────────┘
                               │                    │
                          不是食物→跳过           ↓
                                           data/inkcal.db (SQLite)
```

多源支持：通过 `SOURCE=immich,photoprism` 同时从多个照片库拉取。

三步走：
1. **Immich / PhotoPrism** — 拉指定日期的照片列表
2. **SigLIP2**（本地 CPU 推理 ~0.3s/张） — 判断图片里有没有食物，不是食物的直接跳过，**不出内网**
3. **Gemini**（OpenAI 兼容格式） — 分析食物热量、蛋白质、碳水、脂肪，记入 SQLite

## 前置

| 组件 | 要求 |
|------|------|
| [Immich](https://immich.app) 或 [PhotoPrism](https://www.photoprism.app/) | 至少一个运行中的实例 |
| Gemini API key | 或任何 OpenAI 兼容的视觉模型 endpoint |
| Python 3.11+ | |

## 设置

```bash
cd ~/Coding/inkcal
cp .env.example .env
# 编辑 .env 填入照片库地址、API key 和 Gemini key

pip install -r requirements.txt
```

## 自动化

```bash
./setup.sh   # 创建 ~/.local/bin/inkcal + 配置 cron（每 10 分钟自动运行）
```

流水线幂等，重复运行不会产生重复记录。手动管理 cron：`crontab -e`。

## CLI 用法

```bash
# 分析今天的照片
inkcal run

# 分析指定日期
inkcal run --date 2026-05-13

# 手动记录
inkcal add --meal "红烧肉" --calories 600 --protein 25 --carbs 30 --fat 20

# 查看记录
inkcal view                          # 今天
inkcal view --date 2026-05-13        # 指定日期
inkcal view --week                   # 本周
inkcal view --month 2026-05          # 整月
inkcal view --from 2026-07-01 --to 2026-07-14  # 日期范围

# 聚合统计
inkcal stats --last 7d               # 最近一周
inkcal stats --from 2026-07-01 --to 2026-07-14 --group-by day

# 搜索记录（全文搜索）
inkcal search 咖喱

# 直接修改记录（旧值自动留痕）
inkcal edit --ref 42 --calories 300 --note "两人份减半"
inkcal edit --meal 红烧肉 --date 2026-07-21 --protein 30

# 删除记录（自动加入忽略列表）
inkcal delete --last

# 标注正误（用于分类器训练）
inkcal label --list                  # 列出未标注记录
inkcal label --ref 42 --label correct

# 替换图片（pHash 匹配 Immich 原图）
inkcal replace --ref 42 --image ~/path/to/image.jpg

# 照片去向追溯
inkcal explain --id <asset前缀>       # 单张照片的决策路径
inkcal explain --date 2026-07-21      # 当日全量对账

# 强制分析（分类器漏判的照片）
inkcal analyze --id <asset-id> --source immich

# 补充细节重新估算
inkcal reanalyze --ref 42 --notes "少算了一份米饭"

# 拉取流水线事件
inkcal events

# JSON → SQLite 迁移（首次使用）
inkcal migrate
```

所有读命令支持 `--json` 输出结构化数据。写命令支持四种定位方式：`--ref <id>`（记录 ID）、`--id <前缀>`（asset ID）、`--last`（最近一条）、`--meal <关键词> --date <日期>`。

## Web 查看器

```bash
inkcal run --command serve           # 或直接用 python web/server.py
# 默认 http://127.0.0.1:5800（仅本机）
```

如需在手机/其他设备访问，建议在 `.env` 配 `INKCAL_HOST=0.0.0.0` 或前面挂 caddy/nginx 反向代理（生产推荐配 HTTPS + `INKCAL_HTTPS=1`）。**Flask 自带 server 不适合直接暴露公网**。

反向代理/FRP 场景下，登录限速会自动读取 `X-Forwarded-For` / `X-Real-IP`，按真实访客 IP 隔离（仅在本地回环连接时信任该头，防止伪造）。

功能：
- **日历日期选择器**：有记录的日期显示绿点，点击跳转
- **响应式布局**：移动端单列，桌面端侧边栏日历 + 双列卡片
- **卡片缩略图** + 点击灯箱查看大图
- **选择照片**：从 Immich/PhotoPrism 相册挑选被 SigLIP2 漏检的照片，跳过食物检测直接送 Gemini 分析
- **手动上传**：拖拽 / 粘贴 / 选文件 → Gemini 分析 → Immich pHash 匹配 → 自动刷新
- **重新分析**：在 lightbox 中补充细节（如份量、遗漏食材），Gemini 重新估算
- **人工标注**：每张图片可标记「正确/有误」，数据写入 SQLite
- **替换图片**：上传新图自动用 pHash 匹配 Immich 中的原图，替换误识别记录
- **删除记录**：删除后自动加入忽略列表，cron 不再重复处理
- **可选认证**：`.env` 配 `INKCAL_USER` + `INKCAL_PASS`（必须同时设；登录有 IP 限速）。固定 `INKCAL_SECRET` 让 session 跨重启保留。

## 数据存储

SQLite（`data/inkcal.db`），六张表：

- `records` — 主记录（餐食、热量、宏量、时间、标注、替换图片路径）
- `reanalysis_history` — 重新分析历史，外键级联删除
- `ignored_assets` — 已删除/忽略的资产 ID，cron 跳过
- `classified_non_food` — 分类器/Gemini 判定非食物的资产 ID，Web 相册可见
- `pipeline_events` — 流水线事件（agent 主动通知用）
- `records_fts` — 全文搜索索引（FTS5）

WAL 模式支持并发读写，Flask 多线程共享连接。

## 隐私

SigLIP2 在本地 CPU 推理，食物过滤阶段**图片不离开机器**。只有确认是食物的图片才发往 Gemini 云端分析。照片库内网可达，不暴露公网。

## 设计原则

- **隐私优先**：本地分类器过滤后才走云 API
- **幂等**：已处理的 asset_id 不会重复分析
- **Gemini prompt 防误识别**：自动拦截截图、海报、菜单、屏幕等假食物图片
