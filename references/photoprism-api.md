# PhotoPrism API 对接文档

> 本文档面向 inkcal 项目，描述如何通过 PhotoPrism REST API 读取照片元数据并下载缩略图/原始文件。
>
> 目标 PhotoPrism 版本：最新稳定版（基于 develop 分支 swagger.json）

---

## 目录

1. [官方文档与参考资源](#1-官方文档与参考资源)
2. [认证机制](#2-认证机制)
3. [核心 API 详解](#3-核心-api-详解)
4. [照片下载（缩略图与原始文件）](#4-照片下载缩略图与原始文件)
5. [inkcal 集成方案](#5-inkcal-集成方案)
6. [环境变量与配置](#6-环境变量与配置)
7. [错误处理](#7-错误处理)
8. [参考源码链接](#8-参考源码链接)

---

## 1. 官方文档与参考资源

- **官方 API 文档**
  - `https://docs.photoprism.app/developer-guide/api/`
  - 涵盖：REST API 概览、认证方式、Swagger 文档链接

- **Swagger 交互式文档**
  - `https://docs.photoprism.dev/`（在线）
  - 本地实例：`https://<your-instance>/api/v1/docs`
  - 机器可读 spec：`https://<your-instance>/api/v1/swagger.json`

- **API 源码包（Go）**
  - `https://github.com/photoprism/photoprism/tree/develop/internal/api`
  - `https://pkg.go.dev/github.com/photoprism/photoprism/internal/api`

- **Thumbnail API 文档**
  - `https://docs.photoprism.app/developer-guide/api/thumbnails/`

- **Search API 文档**
  - `https://docs.photoprism.app/developer-guide/api/search/`

- **Client Authentication 文档**
  - `https://docs.photoprism.app/developer-guide/api/client-authentication/`

---

## 2. 认证机制

PhotoPrism 支持多种认证方式，按推荐程度排序：

### 2.1 App Password（推荐用于 inkcal）

用户在 Web UI 生成，或管理员通过 CLI 创建：

```bash
photoprism auth add -n "inkcal-sync" -s "photos albums" admin
```

响应示例：

```
|-----------------------------|---------------------|
| App Password                | Authorization Scope |
|-----------------------------|---------------------|
| HY8fxO-8hvNqB-43UV4q-1AZ0vu | photos albums       |
|-----------------------------|---------------------|
```

**使用方式**：直接作为 Bearer Token 放入请求头

```http
Authorization: Bearer HY8fxO-8hvNqB-43UV4q-1AZ0vu
```

App Password 无需先创建 session，可直接调用 API。也可用于换取短期 session token：

```http
POST /api/v1/session
Content-Type: application/json

{
  "username": "admin",
  "password": "HY8fxO-8hvNqB-43UV4q-1AZ0vu"
}
```

### 2.2 Session Token

通过登录接口获取短期 token：

```http
POST /api/v1/session
Content-Type: application/json

{
  "username": "admin",
  "password": "your-password"
}
```

响应包含 session ID，后续请求使用：

```http
Authorization: Bearer <session-token>
```

### 2.3 OAuth2 Client Credentials

适用于服务间集成：

```bash
photoprism clients add -n "inkcal-service" -s "photos"
```

获取 `client_id` + `client_secret`，然后通过标准 OAuth2 flow 换取 access token：

```http
POST /api/v1/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=csce0w2joodmirvi&client_secret=5VKkBeZLDvojjpE9XzCMXShnrxmxHWvN
```

### 2.4 公开模式（Public Mode）

若实例启用了公开模式，缩略图 API 可使用 `public` 作为 token 占位符：

```
/api/v1/t/<hash>/public/tile_500
```

---

## 3. 核心 API 详解

### 3.1 搜索照片

```http
GET /api/v1/photos
Authorization: Bearer <token>
```

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `count` | int | 是 | 返回最大文件数（如 100） |
| `offset` | int | 否 | 分页偏移量 |
| `order` | string | 否 | 排序：added, updated, edited, newest, oldest, name, title, random |
| `merged` | bool | 否 | 合并同一照片的多文件（如 Live Photo） |
| `primary` | bool | 否 | 仅返回主文件（缩略图） |
| `q` | string | 否 | 搜索查询，支持过滤语法（见下方） |
| `s` | string | 否 | 限定到指定相册 UID |
| `path` | string | 否 | 按路径过滤 |
| `video` | bool | 否 | 仅返回视频 |

**搜索过滤语法（q 参数）**：

| 过滤器 | 示例 | 说明 |
|--------|------|------|
| `type:` | `type:live` | 媒体类型：image, video, live, raw |
| `year:` | `year:2024` | 拍摄年份 |
| `month:` | `month:5` | 拍摄月份 |
| `day:` | `day:12` | 拍摄日期 |
| `after:` | `after:2024-01-01` | 拍摄日期之后 |
| `before:` | `before:2024-12-31` | 拍摄日期之前 |
| `favorite:` | `favorite:true` | 收藏状态 |
| `country:` | `country:cn` | 国家代码 |
| `color:` | `color:red` | 主色调 |
| `name:` | `name:"IMG_"` | 文件名匹配 |
| `original:` | `original:"heic"` | 原始格式 |
| `stack:` | `stack:true` | 堆叠状态 |
| `quality:` | `quality:4` | 质量等级 0-5 |

可组合使用：`q=type:image year:2024 favorite:true`

**响应头**：

| 头字段 | 说明 |
|--------|------|
| `X-Count` | 实际返回文件数 |
| `X-Limit` | 请求的最大数 |
| `X-Offset` | 当前偏移 |
| `X-Download-Token` | 下载原始文件所需 token |
| `X-Preview-Token` | 缩略图 API 所需 token |

**响应体示例**：

```json
[
  {
    "ID": "11-21",
    "UID": "pse1yzastu36irsj",
    "Type": "image",
    "TakenAt": "2012-08-27T12:40:25Z",
    "TakenAtLocal": "2012-08-27T14:40:25Z",
    "TimeZone": "Europe/Madrid",
    "Path": "2012",
    "Name": "20120827-144025-Bodegas-Ysios-Winery-Laguardia-Spain",
    "Title": "Bodegas Ysios Winery / Laguardia / Spain",
    "Description": "",
    "Year": 2012,
    "Month": 8,
    "Day": 27,
    "Country": "es",
    "Stack": 0,
    "Favorite": false,
    "Private": false,
    "Iso": 100,
    "FocalLength": 28,
    "FNumber": 11,
    "Exposure": "1/160",
    "Quality": 4,
    "Resolution": 8,
    "Lat": 42.568302,
    "Lng": -2.5908582,
    "PlaceLabel": "Laguardia, Euskadi, Spain",
    "PlaceCity": "Laguardia",
    "PlaceState": "Euskadi",
    "PlaceCountry": "es",
    "CameraMake": "Canon",
    "CameraModel": "EOS 30D",
    "LensModel": "EF28mm f/1.8 USM",
    "FileUID": "fse1yza2r4gsjq6f",
    "FileRoot": "/",
    "FileName": "2012/20120827-144025-Bodegas-Ysios-Winery-Laguardia-Spain.jpg",
    "Hash": "4bc82c3ea5aaa323aea801fe0125b554af8e49af",
    "Width": 3368,
    "Height": 2246,
    "Portrait": false,
    "Merged": false,
    "CreatedAt": "2024-05-25T17:52:22.291451832Z",
    "UpdatedAt": "2024-05-25T17:52:22.307889576Z",
    "Files": [
      {
        "UID": "fse1yza2r4gsjq6f",
        "PhotoUID": "pse1yzastu36irsj",
        "Name": "2012/20120827-144025-Bodegas-Ysios-Winery-Laguardia-Spain.jpg",
        "Root": "/",
        "Hash": "4bc82c3ea5aaa323aea801fe0125b554af8e49af",
        "Size": 2473990,
        "Primary": true,
        "Codec": "jpeg",
        "FileType": "jpg",
        "MediaType": "image",
        "Mime": "image/jpeg",
        "Width": 3368,
        "Height": 2246,
        "Orientation": 1,
        "AspectRatio": 1.5,
        "CreatedAt": "2024-05-25T17:52:22.291451832Z"
      }
    ]
  }
]
```

**关键字段说明**：

| 字段 | 说明 |
|------|------|
| `UID` | 照片唯一标识（用于 API 操作） |
| `Hash` | 文件 SHA1 哈希（用于缩略图/下载） |
| `TakenAtLocal` | 本地时区的拍摄时间 |
| `Files` | 关联文件列表（Live Photo 会有多个） |
| `Files[].Primary` | 是否为主文件 |

### 3.2 获取单张照片详情

```http
GET /api/v1/photos/{uid}
Authorization: Bearer <token>
```

返回单张照片的完整元数据。

### 3.3 获取相册列表

```http
GET /api/v1/albums?count=100&order=updated
Authorization: Bearer <token>
```

**响应字段**：

| 字段 | 说明 |
|------|------|
| `UID` | 相册唯一标识 |
| `Title` | 相册标题 |
| `Type` | 类型：album, folder, moment, month, state |
| `Path` | 路径（folder 类型） |
| `Thumb` | 封面图 UID |

### 3.4 获取相册内照片

```http
GET /api/v1/albums/{uid}/photos?count=100
Authorization: Bearer <token>
```

响应格式与 `/api/v1/photos` 相同。

### 3.5 创建会话（登录）

```http
POST /api/v1/session
Content-Type: application/json

{
  "username": "admin",
  "password": "your-password-or-app-password"
}
```

### 3.6 删除会话（登出）

```http
DELETE /api/v1/session
Authorization: Bearer <token>
```

---

## 4. 照片下载（缩略图与原始文件）

### 4.1 缩略图 API（Cookie-free）

PhotoPrism 使用无 cookie 的缩略图 API 以降低延迟：

```
GET /api/v1/t/{hash}/{token}/{size}
```

| 参数 | 说明 |
|------|------|
| `hash` | 文件 SHA1 哈希（来自 `Files[].Hash`） |
| `token` | `X-Preview-Token` 或 `public` |
| `size` | 缩略图尺寸名称 |

**常用尺寸**：

| 尺寸名 | 宽度 | 高度 | 用途 |
|--------|------|------|------|
| `tile_50` | 50 | 50 | 列表视图 |
| `tile_100` | 100 | 100 | 地点视图 |
| `tile_224` | 224 | 224 | AI / 马赛克视图 |
| `tile_500` | 500 | 500 | 卡片视图 |
| `fit_720` | 720 | 720 | 移动端 / SD |
| `fit_1280` | 1280 | 1024 | HD TV |
| `fit_1920` | 1920 | 1200 | 全高清 |
| `fit_2048` | 2048 | 2048 | DCI 2K |
| `fit_3840` | 3840 | 2400 | 4K |

**示例**：

```http
GET /api/v1/t/4bc82c3ea5aaa323aea801fe0125b554af8e49af/10d68214/tile_500
```

### 4.2 视频 API

```
GET /api/v1/videos/{hash}/{token}/{format}
```

当前仅支持 `avc` (H.264) 格式。

### 4.3 下载原始文件

```http
GET /api/v1/photos/{uid}/dl
Authorization: Bearer <token>
```

或按文件下载：

```http
GET /api/v1/dl/{file-hash}
Authorization: Bearer <token>
```

需要有效的 `X-Download-Token`。

### 4.4 相册批量下载

```http
GET /api/v1/albums/{uid}/dl
Authorization: Bearer <token>
```

返回 ZIP 文件。

---

## 5. inkcal 集成方案

### 5.1 架构定位

```
┌─────────────┐     ┌─────────────────┐     ┌──────────────┐
│  PhotoPrism │────▶│  inkcal adapter │────▶│  food detect │
│  (Go+Vue)   │     │  (Python)       │     │  + analyze   │
└─────────────┘     └─────────────────┘     └──────────────┘
```

### 5.2 适配器设计（`src/photoprism_client.py`）

```python
import httpx
from datetime import datetime, timezone
from typing import Iterator

class PhotoPrismClient:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {token}"},
            timeout=30
        )
        self._preview_token = None
        self._download_token = None

    def _fetch_tokens(self):
        """从搜索响应头获取缩略图/下载 token"""
        resp = self.client.get(f"{self.base}/api/v1/photos", params={"count": 1})
        resp.raise_for_status()
        self._preview_token = resp.headers.get("X-Preview-Token")
        self._download_token = resp.headers.get("X-Download-Token")

    def iter_photos(
        self,
        after: datetime | None = None,
        before: datetime | None = None,
        count: int = 100
    ) -> Iterator[dict]:
        """分页遍历照片，按拍摄时间倒序"""
        offset = 0
        q_parts = []
        if after:
            q_parts.append(f"after:{after.strftime('%Y-%m-%d')}")
        if before:
            q_parts.append(f"before:{before.strftime('%Y-%m-%d')}")

        while True:
            params = {
                "count": count,
                "offset": offset,
                "order": "newest",
                "merged": "true",
                "q": " ".join(q_parts) if q_parts else ""
            }
            resp = self.client.get(f"{self.base}/api/v1/photos", params=params)
            resp.raise_for_status()

            photos = resp.json()
            if not photos:
                break

            # 更新 token（每次请求都可能刷新）
            self._preview_token = resp.headers.get("X-Preview-Token", self._preview_token)
            self._download_token = resp.headers.get("X-Download-Token", self._download_token)

            for photo in photos:
                # 取主文件
                primary_file = next(
                    (f for f in photo.get("Files", []) if f.get("Primary")),
                    photo.get("Files", [{}])[0]
                )
                yield {
                    "asset_id": photo["UID"],
                    "photo_time": self._parse_time(photo["TakenAtLocal"]),
                    "hash": primary_file.get("Hash"),
                    "filename": primary_file.get("Name"),
                    "width": primary_file.get("Width"),
                    "height": primary_file.get("Height"),
                    "mime": primary_file.get("Mime"),
                    "raw_data": photo
                }

            if len(photos) < count:
                break
            offset += count

    def get_thumbnail_url(self, hash: str, size: str = "tile_500") -> str:
        """构造缩略图 URL"""
        token = self._preview_token or "public"
        return f"{self.base}/api/v1/t/{hash}/{token}/{size}"

    def get_original_url(self, uid: str) -> str:
        """构造原始文件下载 URL"""
        return f"{self.base}/api/v1/photos/{uid}/dl"

    def download_thumbnail(self, hash: str, size: str = "tile_500") -> bytes:
        """下载缩略图二进制"""
        url = self.get_thumbnail_url(hash, size)
        resp = self.client.get(url)
        resp.raise_for_status()
        return resp.content

    def _parse_time(self, ts: str) -> datetime:
        """解析 PhotoPrism 时间格式"""
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def close(self):
        self.client.close()
```

### 5.3 与 inkcal pipeline 的对接

在 `main.py` 的 `run` 命令中增加 PhotoPrism source：

```python
# main.py
from src.photoprism_client import PhotoPrismClient

def run_photoprism():
    client = PhotoPrismClient(
        base_url=os.environ["PHOTOPRISM_URL"],
        token=os.environ["PHOTOPRISM_API_KEY"]
    )

    # 获取上次同步时间（从 checkpoint 文件读取）
    last_sync = get_checkpoint("photoprism")

    for photo in client.iter_photos(after=last_sync):
        if already_processed(photo["asset_id"]):
            continue

        # 下载缩略图用于食物检测
        thumb = client.download_thumbnail(photo["hash"], "fit_720")

        # 走现有 pipeline
        result = process_photo(
            asset_id=photo["asset_id"],
            photo_time=photo["photo_time"],
            image_bytes=thumb,
            source="photoprism"
        )

        if result:
            save_record(result)

    # 写入 checkpoint
    set_checkpoint("photoprism", datetime.now())
    client.close()
```

### 5.4 配置项

`.env` 新增：

```bash
# PhotoPrism 配置（可选，与 Immich 二选一或同时启用）
PHOTOPRISM_URL=https://photos.your-domain.com
PHOTOPRISM_API_KEY=HY8fxO-8hvNqB-43UV4q-1AZ0vu
```

---

## 6. 环境变量与配置

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `PHOTOPRISM_URL` | 是 | 实例地址，如 `https://photos.example.com` |
| `PHOTOPRISM_API_KEY` | 是 | App Password 或 Access Token |

---

## 7. 错误处理

| HTTP 状态 | 含义 | 处理建议 |
|-----------|------|---------|
| 400 | 请求参数错误 | 检查过滤语法 |
| 401 | 认证失败 | Token 过期或无效，重新获取 |
| 403 | 权限不足 | 检查 scope 是否包含 `photos` |
| 404 | 照片/相册不存在 | UID 错误 |
| 429 | 请求过多 | 增加间隔，降低并发 |
| 500 | 服务器内部错误 | 重试或检查 PhotoPrism 日志 |

---

## 8. 参考源码链接

- **PhotoPrism 主仓库**：`https://github.com/photoprism/photoprism`
- **API 源码目录**：`https://github.com/photoprism/photoprism/tree/develop/internal/api`
- **Swagger JSON**：`https://github.com/photoprism/photoprism/blob/develop/internal/api/swagger.json`
- **缩略图尺寸定义**：`https://github.com/photoprism/photoprism/blob/develop/internal/thumb/sizes.go`

---

## 附录：与 Immich API 的对比

| 特性 | PhotoPrism | Immich |
|------|-----------|--------|
| 认证 | App Password / OAuth2 / Session | API Key (固定) |
| 搜索语法 | 字符串过滤（q 参数） | 结构化参数 |
| 缩略图 | SHA1 hash + token + size | asset ID + size param |
| 响应结构 | 照片嵌套 Files 数组 | 扁平 Asset 对象 |
| 相册概念 | album, folder, moment | album, shared album |
| 时间字段 | `TakenAtLocal`（带时区） | `fileCreatedAt` / `localDateTime` |
| 下载 token | 动态（X-Download-Token） | 固定 API Key |

两个 API 的核心差异在于：**PhotoPrism 使用文件 hash 作为缩略图 key，而 Immich 使用 asset ID**。inkcal adapter 需要分别处理这种映射关系。
