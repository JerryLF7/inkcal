# Synology Photos API 对接文档

> 本文档面向 inkcal 项目，描述如何通过 Synology DSM Web API 读取 Synology Photos 中的照片元数据并下载原始文件/缩略图。
>
> 目标 DSM 版本：7.x（兼容 6.x 核心机制）

---

## 目录

1. [官方文档与参考资源](#1-官方文档与参考资源)
2. [认证机制](#2-认证机制)
3. [API 发现机制](#3-api-发现机制)
4. [Photos 核心 API 详解](#4-photos-核心-api-详解)
5. [照片下载（缩略图与原始文件）](#5-照片下载缩略图与原始文件)
6. [ inkcal 集成方案](#6-inkcal-集成方案)
7. [环境变量与配置](#7-环境变量与配置)
8. [错误码速查](#8-错误码速查)
9. [参考源码链接](#9-参考源码链接)

---

## 1. 官方文档与参考资源

Synology 官方并未为 Photos 套件单独发布 PDF API Guide，但 DSM 整体的 Web API 机制对所有套件通用。以下是最权威的参考来源：

- **DSM Developer Guide 7 (PDF)**
  - 下载地址：`https://global.download.synology.com/download/Document/Software/DeveloperGuide/Os/DSM/All/enu/DSM_Developer_Guide_7_enu.pdf`
  - 涵盖：通用 API 架构、认证流程、请求构造、错误码体系

- **Synology Photos 产品规格页**
  - `https://www.synology.com/zh-tw/dsm/7.3/software_spec/synology_photos`
  - 涵盖：功能概述、兼容性要求（Node.js v12 + Synology Application Service）

- **Synology Photos 快速入门**
  - `https://kb.synology.cn/DSM/tutorial/Quick_Start_Synology_Photos`
  - 涵盖：个人空间 vs 共享空间、相册概念、权限模型

- **社区 Python 封装库（核心参考）**
  - `https://github.com/N4S4/synology-api`
  - 该库的 `photos.py` / `auth.py` / `base_api.py` 是目前最完整的逆向实现参考

---

## 2. 认证机制

Synology DSM 使用基于 Session 的认证。所有 API 请求（除 `SYNO.API.Info` 外）都需要有效的 `_sid`（Session ID）。

### 2.1 登录流程

```
POST /webapi/auth.cgi
Content-Type: application/x-www-form-urlencoded

api=SYNO.API.Auth
version=7
method=login
account=<用户名>
passwd=<密码>
session=webui
format=cookie
enable_syno_token=yes
```

**关键参数说明：**

- `session`: 应用上下文标识。Photos 使用 `FotoStation`（见 `photos.py` 第 99 行）。`auth.py` 中硬编码为 `webui` 以兼容非管理员用户
- `enable_syno_token=yes`: 返回 `synotoken`，用于后续请求的 `X-SYNO-TOKEN` 头部（DSM 7 反 CSRF 机制）
- `format=cookie`: 让 DSM 同时设置 Cookie，便于浏览器环境使用

**DSM 7 特殊处理：**

DSM 7 引入了参数加密机制。`auth.py` 中：

- 若 `secure=True`（HTTPS），密码明文传输
- 若 `secure=False`（HTTP），调用 `encrypt_params()` 进行 RSA+AES 加密
- 额外需要 `ik_message`（Noise_IK_25519 握手）

对于 inkcal 场景（内网 HTTPS 或可信 HTTP），建议直接走 HTTPS 跳过加密复杂度。

### 2.2 响应示例

```json
{
  "success": true,
  "data": {
    "sid": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "synotoken": "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
    "did": "..."
  }
}
```

### 2.3 登出

```
GET /webapi/auth.cgi?api=SYNO.API.Auth&version=7&method=logout&session=webui
```

### 2.4 2FA / OTP

若账户开启双重验证，登录请求需附加：

```
otp_code=<6位数字>
```

### 2.5 设备绑定

长期运行场景（如 inkcal cron）建议使用设备绑定避免频繁 2FA：

```
device_id=<唯一标识>
device_name=inkcal-pipeline
```

---

## 3. API 发现机制

Synology DSM 没有静态 API 文档。所有 API 的路径、版本、可用方法都通过运行时查询获得。

### 3.1 查询所有可用 API

```
GET /webapi/query.cgi?api=SYNO.API.Info&version=1&method=query&query=all
```

**响应结构：**

```json
{
  "success": true,
  "data": {
    "SYNO.API.Auth": {
      "path": "auth.cgi",
      "minVersion": 1,
      "maxVersion": 7
    },
    "SYNO.Foto.Browse.Item": {
      "path": "entry.cgi",
      "minVersion": 1,
      "maxVersion": 2
    },
    ...
  }
}
```

### 3.2 按应用过滤

```
GET /webapi/query.cgi?api=SYNO.API.Info&version=1&method=query&query=SYNO.Foto
```

**inkcal 实现要点：**

- 初始化时调用一次 `query=all`，缓存 `api_name → {path, maxVersion}` 映射
- 后续所有请求使用缓存的 `path` 和 `maxVersion`
- `photos.py` 中通过 `self.photos_list[api_name]` 获取这些信息（第 99 行）

---

## 4. Photos 核心 API 详解

以下 API 全部基于 `synology-api` 库的 `photos.py` 源码（`entry.cgi` 路径）。

### 4.1 SYNO.Foto.UserInfo — 获取当前用户信息

```
GET /webapi/entry.cgi?api=SYNO.Foto.UserInfo&version=<maxVersion>&method=me
```

**用途：** 获取当前登录用户的 `id`，用于条件相册等场景。

**响应关键字段：**

- `data.id`: 用户 ID
- `data.name`: 用户名

---

### 4.2 SYNO.Foto.Browse.Folder — 文件夹操作（个人空间）

#### 获取单个文件夹

```
GET /webapi/entry.cgi?api=SYNO.Foto.Browse.Folder&version=<maxVersion>&method=get&id=<folder_id>
```

**参数：**

- `id`: 文件夹 ID，`0` 表示根目录

#### 列出文件夹

```
GET /webapi/entry.cgi?api=SYNO.Foto.Browse.Folder&version=<maxVersion>&method=list&id=<folder_id>&limit=<limit>&offset=<offset>&additional=<json_array>
```

**参数：**

- `id`: 父文件夹 ID，默认 `0`
- `limit`: 返回数量上限，默认 `1000`
- `offset`: 跳过数量，用于分页
- `additional`: JSON 数组字符串，附加字段（如 `["thumbnail"]`）

**响应关键字段：**

```json
{
  "success": true,
  "data": {
    "list": [
      {
        "id": 123,
        "name": "/Photos/2024",
        "parent": 0,
        "thumbnail": { ... }
      }
    ]
  }
}
```

#### 统计文件夹数量

```
GET /webapi/entry.cgi?api=SYNO.Foto.Browse.Folder&version=<maxVersion>&method=count&id=<folder_id>
```

---

### 4.3 SYNO.FotoTeam.Browse.Folder — 文件夹操作（团队空间）

与个人空间 API 完全一致，仅 `api` 参数替换为 `SYNO.FotoTeam.Browse.Folder`。

**inkcal 场景：** 如果用户将食物照片备份到团队空间（共享相册），需要调用 Team 系列 API。

---

### 4.4 SYNO.Foto.Browse.Item — 列出照片/视频（核心 API）

```
GET /webapi/entry.cgi?api=SYNO.Foto.Browse.Item&version=<maxVersion>&method=list&offset=<offset>&limit=<limit>&folder_id=<folder_id>&sort_by=<sort_by>&sort_direction=<sort_direction>&type=<type>&additional=<additional>
```

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `offset` | int | 否 | 跳过数量，默认 `0` |
| `limit` | int | 否 | 返回上限，`0` 表示全部，默认 `0` |
| `folder_id` | int | 否 | 文件夹 ID，`0` 表示所有文件夹，默认 `0` |
| `sort_by` | str | 否 | 排序字段：`filename` / `filesize` / `takentime` / `item_type` |
| `sort_direction` | str | 否 | `asc` / `desc`，默认 `desc` |
| `type` | str | 否 | 过滤类型：`photo` / `video` / `live` |
| `passphrase` | str | 否 | 共享相册的通行短语 |
| `additional` | list | 否 | 附加字段数组 |

**additional 可选值：**

```python
["thumbnail", "resolution", "orientation", "video_convert", "video_meta",
 "provider_user_id", "exif", "tag", "description", "gps", "geocoding_id",
 "address", "person"]
```

**inkcal 建议：** 至少请求 `["thumbnail", "exif", "resolution"]`，用于：

- `thumbnail`: 获取缩略图下载参数
- `exif`: 提取拍摄时间（用于按日期分组）
- `resolution`: 图片尺寸信息

**响应结构：**

```json
{
  "success": true,
  "data": {
    "list": [
      {
        "id": 456,
        "filename": "IMG_20240512_123456.jpg",
        "filesize": 3145728,
        "takentime": "2024-05-12T12:34:56+08:00",
        "folder_id": 123,
        "thumbnail": {
          "cache_key": "abc123...",
          "m": "ready",
          "preview": "broken",
          "sm": "ready",
          "xl": "ready"
        },
        "exif": {
          "DateTimeOriginal": "2024:05:12 12:34:56",
          "Make": "Apple",
          "Model": "iPhone15,2"
        },
        "resolution": "4032x3024"
      }
    ],
    "total": 150
  }
}
```

**关键字段说明：**

- `id`: 照片唯一标识（inkcal 中作为 `asset_id`）
- `takentime`: 拍摄时间（优先使用）
- `thumbnail.cache_key`: 下载缩略图必需参数
- `thumbnail.m/sm/xl`: 缩略图尺寸状态，`ready` 表示可用

---

### 4.5 SYNO.Foto.Browse.Album — 相册操作

#### 获取相册信息

```
GET /webapi/entry.cgi?api=SYNO.Foto.Browse.Album&version=<maxVersion>&method=get&id=["<album_id>"]&additional=[]
```

#### 列出所有相册

```
GET /webapi/entry.cgi?api=SYNO.Foto.Browse.Album&version=<maxVersion>&method=list&offset=0&limit=100
```

#### 删除相册

```
GET /webapi/entry.cgi?api=SYNO.Foto.Browse.Album&version=<maxVersion>&method=delete&id=["<album_id>"]
```

---

### 4.6 SYNO.Foto.Sharing.Passphrase — 共享设置

```
GET /webapi/entry.cgi?api=SYNO.Foto.Sharing.Passphrase&version=<maxVersion>&method=set_shared&policy=album&album_id=<id>
```

---

### 4.7 SYNO.Foto.Search.Filter — 搜索过滤器

```
GET /webapi/entry.cgi?api=SYNO.Foto.Search.Filter&version=<maxVersion>&method=list
```

---

## 5. 照片下载（缩略图与原始文件）

Synology Photos 没有提供专门的 "Download" API。照片下载通过 `entry.cgi` 的直接 URL 访问实现，需要 `_sid` 认证。

### 5.1 缩略图下载

```
GET /webapi/entry.cgi?api=SYNO.Foto.Thumbnail&version=1&method=get&id=<item_id>&type=<size>&cache_key=<cache_key>&_sid=<sid>
```

**参数：**

- `id`: 照片 ID（来自 `list_item_in_folders` 的 `id`）
- `type`: 缩略图尺寸
  - `sm`: 小图（约 120x120）
  - `m`: 中图（约 320x320）
  - `xl`: 大图（约 1280x1280）
  - `preview`: 预览图
- `cache_key`: 来自 `thumbnail.cache_key`
- `_sid`: Session ID

**等效 Python 代码：**

```python
thumb_url = (
    f"{base_url}/webapi/entry.cgi"
    f"?api=SYNO.Foto.Thumbnail"
    f"&version=1"
    f"&method=get"
    f"&id={item_id}"
    f"&type=m"
    f"&cache_key={cache_key}"
    f"&_sid={sid}"
)
response = requests.get(thumb_url, headers={"X-SYNO-TOKEN": syno_token})
# response.content 为 JPEG 二进制数据
```

### 5.2 原始文件下载

原始文件下载有两种方式：

#### 方式 A：通过 FileStation API（推荐）

如果知道照片在 NAS 文件系统中的绝对路径，可以直接用 FileStation API：

```
GET /webapi/entry.cgi?api=SYNO.FileStation.Download&version=2&method=download&path=<文件路径>&mode=download&_sid=<sid>
```

**问题：** Synology Photos 的 `item` 对象不直接暴露文件系统路径。

#### 方式 B：通过 Photos 内部下载 URL（逆向）

通过浏览器开发者工具分析，原始文件下载 URL 为：

```
GET /webapi/entry.cgi?api=SYNO.Foto.Download&version=1&method=get&id=<item_id>&_sid=<sid>
```

**注意：** `SYNO.Foto.Download` 未在 `synology-api` 库中封装，属于逆向发现。实际可用性因 DSM 版本而异。

#### 方式 C：通过 DSM 统一下载（最可靠）

```
GET /webapi/entry.cgi?api=SYNO.FileStation.Download&version=2&method=download&path=/photos/IMG_123.jpg&mode=open&_sid=<sid>
```

**inkcal 建议：**

1. 优先使用缩略图（`type=m`）给 SigLIP2 做食物检测
2. 若需要原始文件进行 Gemini 分析，通过 FileStation API 配合已知路径下载
3. 如果 Photos 元数据中不包含文件路径，需要额外调用 `SYNO.FileStation.List` 遍历找到对应文件

---

## 6. inkcal 集成方案

### 6.1 架构位置

Synology Photos 作为 inkcal 的第二个 Photo Source（与 Immich 并列）：

```
Synology Photos (手机自动备份)
    ↓
SynologyPhotosClient (新模块)
    ↓
list_recent_photos() → 返回 [{asset_id, thumbnail_url, photo_time, ...}]
    ↓
FoodDetector (SigLIP2)
    ↓
CalorieAnalyzer (Gemini)
    ↓
data/YYYY-MM-DD.json
```

### 6.2 建议的客户端接口

参考 `src/immich_client.py` 设计：

```python
class SynologyPhotosClient:
    def __init__(self, url: str, username: str, password: str,
                 otp_code: str = None, secure: bool = True):
        """初始化并登录 Synology Photos。"""

    def list_recent_photos(self, after: datetime, limit: int = 100) -> list[dict]:
        """
        列出指定时间之后的新照片。
        返回字段与 Immich 兼容：asset_id, thumbnail_url, photo_time, etc.
        """

    def download_thumbnail(self, item_id: int, cache_key: str, size: str = "m") -> bytes:
        """下载缩略图二进制数据。"""

    def download_original(self, item_id: int) -> bytes:
        """下载原始文件二进制数据。"""

    def close(self):
        """登出并清理会话。"""
```

### 6.3 增量同步策略

Synology Photos API 没有内置的 "since" 参数。建议实现：

1. **时间窗口法**：按 `takentime` 排序，每次拉取最近 N 小时的照片
2. **ID 去重法**：维护已处理的 `item_id` 集合（类似 Immich 的 `asset_id`）
3. **文件夹监控法**：如果用户按日期组织文件夹（如 `/Photos/2024/05/12`），直接监控最新文件夹

### 6.4 与 Immich 的差异化

| 维度 | Immich | Synology Photos |
|------|--------|-----------------|
| 认证 | API Key | 用户名/密码 + Session |
| 增量 | `updatedAfter` 参数 | 需自行按时间/ID 过滤 |
| 缩略图 | 直接 URL + API Key | `cache_key` + `_sid` |
| 原始文件 | 直接 URL | 需通过 FileStation 或内部 URL |
| 手机备份 | 需安装 Immich App | 官方 App，系统级集成 |

---

## 7. 环境变量与配置

建议添加到 `.env`：

```bash
# Synology Photos
SYNOLOGY_URL=https://nas.local:5001
SYNOLOGY_USERNAME=your_username
SYNOLOGY_PASSWORD=your_password
SYNOLOGY_OTP_CODE=          # 可选，2FA 码
SYNOLOGY_SECURE=true        # 是否使用 HTTPS
SYNOLOGY_VERIFY_CERT=false  # 是否验证 SSL 证书（自签名证书设为 false）
```

---

## 8. 错误码速查

Synology API 返回的错误码为数字，通过 `error_codes.py` 映射为可读消息。

**通用错误码：**

- `100`: 未知错误
- `101`: 无效参数
- `102`: 请求的 API 不存在
- `103`: 请求的方法不存在
- `104`: 请求的版本不支持
- `105`: 请求被拒绝（权限不足）
- `106`: 会话超时/无效
- `107`: 会话中断

**Photos 专属错误：** 通过 `PhotosError` 异常抛出，具体码值需查阅 DSM 日志或 `error_codes.py`。

---

## 9. 参考源码链接

以下链接指向 `synology-api` 库（GitHub）的关键源码文件，所有 API 参数、路径构造、认证逻辑均来自这些文件的逆向工程：

| 文件 | 链接 | 说明 |
|------|------|------|
| `photos.py` | `https://github.com/N4S4/synology-api/blob/master/synology_api/photos.py` | Photos API 封装：文件夹、相册、物品列表 |
| `auth.py` | `https://github.com/N4S4/synology-api/blob/master/synology_api/auth.py` | 认证、加密、请求发送、错误处理 |
| `base_api.py` | `https://github.com/N4S4/synology-api/blob/master/synology_api/base_api.py` | 基类：会话复用、API 列表缓存 |
| `error_codes.py` | `https://github.com/N4S4/synology-api/blob/master/synology_api/error_codes.py` | 错误码映射表 |

---

## 附录：请求构造模板

### 基础 URL

```
{schema}://{ip}:{port}/webapi/{path}?api={api_name}
```

### 通用请求参数

```
version={maxVersion}
method={method_name}
_sid={session_id}
```

### 必需 HTTP 头部（DSM 7）

```
X-SYNO-TOKEN: {syno_token}
```

### 完整示例：列出最近照片

```python
import requests

# 1. 登录获取 sid
login_resp = requests.post(
    "https://nas.local:5001/webapi/auth.cgi",
    data={
        "api": "SYNO.API.Auth",
        "version": 7,
        "method": "login",
        "account": "user",
        "passwd": "pass",
        "session": "FotoStation",
        "format": "cookie",
        "enable_syno_token": "yes"
    },
    verify=False
)
sid = login_resp.json()["data"]["sid"]
syno_token = login_resp.json()["data"]["synotoken"]

# 2. 查询 API 信息
info_resp = requests.get(
    "https://nas.local:5001/webapi/query.cgi",
    params={"api": "SYNO.API.Info", "version": 1, "method": "query", "query": "SYNO.Foto.Browse.Item"},
    verify=False
)
path = info_resp.json()["data"]["SYNO.Foto.Browse.Item"]["path"]
max_version = info_resp.json()["data"]["SYNO.Foto.Browse.Item"]["maxVersion"]

# 3. 列出照片
items_resp = requests.get(
    f"https://nas.local:5001/webapi/{path}",
    params={
        "api": "SYNO.Foto.Browse.Item",
        "version": max_version,
        "method": "list",
        "offset": 0,
        "limit": 50,
        "folder_id": 0,
        "sort_by": "takentime",
        "sort_direction": "desc",
        "type": "photo",
        "additional": '["thumbnail", "exif"]',
        "_sid": sid
    },
    headers={"X-SYNO-TOKEN": syno_token},
    verify=False
)
photos = items_resp.json()["data"]["list"]
```

---

*文档版本: 2025-05-12*
*基于 synology-api v0.10+ 和 DSM 7.x 逆向分析*
