# inkcal 原生 Android 客户端实现文档

> 读者：接手实现的 agent。目标：不翻 Vue 源码也能做出功能对等的原生 App。
> 事实来源：`web/server.py`、`src/db.py`、`web/ui/src/**`（截至 2026-09-30）。文档与代码冲突时以代码为准，并回来改本文。
> 项目规则见根目录 `AGENTS.md`，尤其 §1「绝对边界」，实现客户端时同样适用。
>
> **实现进度（0.12，2026-10-03）**：**首期功能全部完成**——三 Tab、日/周/月三视图、餐卡详情、设置页（体征/Calo 窗口/服务器/关于）、选择照片、Calo 聊天，含 §8.6 的 data-version 轮询；首期清单里只剩首期外的 §8.8。逐项状态见 §14 的「进度」列，实施顺序的完成情况见 §15；每个行为小节开头也标了状态。
>
> **0.12 是首期收尾版**：补上 §8.6 轮询，修掉两处自查发现的 bug（聊天乐观消息 id 撞 key 崩溃、周/月视图写后不刷新），并做了一批小修（设置页拆「服务器/关于」分组、BMR 失败可重试、相册上限提示与结果分类、Markdown 链接可点、图标去废弃告警）。明细见 §14 的第 23–25 行。
>
> **0.11 只有修复**：记录页与 Calo 页内嵌 TopAppBar 的 `windowInsets` 与 Scaffold 重复垫了状态栏，标题与列表之间出现一段空白；现显式清零（约定见 §8，本版本无功能变化）。
>
> **0.6 只有非功能性改动**：`network_security_config` 去掉真实地址白名单（见 §3.1），仓库转为 public 并清理了内网地址痕迹。功能与 0.5 相同。
>
> **维护约定**：每完成一次客户端改动，必须在**同一工作单元内**更新本文——至少同步 §14 的「进度」列、§15 的勾选，以及上面这行进度摘要；接口、行为或约定有变化时改对应章节。不要留给下一位接手的人。这条与 `AGENTS.md` §9 同源，不是可选项。

## 0. 范围与原则

1. 纯客户端。只调用现有 Flask API，不改后端（§13 的可选项必须先征得用户同意）。
2. 原生：Kotlin + Jetpack Compose + Material 3，不用 WebView，不套壳。
3. 能用系统或 Material 控件就不手搓。只有周柱状图需要少量自绘（§8.2），其余都有现成控件。
4. 功能对等：当前 Vue 版所有功能都要有（§14 对照清单）。外观不要求一致，按 Material 3 习惯来。
5. App 只认 inkcal 的 HTTP API，不接 SigLIP2、Luna、Gemini、Immich 等上游，它们都在 NUC 上。
6. 不在客户端复刻业务规则。热量汇总、分组、BMR 都由服务端给，客户端只做缺口公式（§7）。

## 1. 技术选型

| 项 | 选择 | 理由 |
|---|---|---|
| 语言/UI | Kotlin 2.x + Jetpack Compose + Material 3 | 原生控件最全 |
| minSdk | 26 | 够用 |
| 网络 | OkHttp + Retrofit + kotlinx.serialization | cookie 与超时控制成熟 |
| 图片 | Coil 3（compose） | 磁盘缓存，可共用 OkHttpClient 带 cookie |
| 导航 | Navigation Compose | 三个顶级目的地 |
| 状态 | ViewModel + StateFlow | 官方推荐 |
| 本地存储 | DataStore | 服务器地址、会话 ID、cookie；不要 Room |
| Markdown | Markwon（AndroidView 包 TextView） | Compose 暂无官方 Markdown |
| 相册选择 | PickVisualMedia / PickMultipleVisualMedia | 系统 Photo Picker，免权限 |

不要引入：Room、Firebase、第二个 HTTP 库、任何图表库、exifinterface（本地上传的日期判定在服务端做，见 §8.5(b)）。

## 2. 构建环境（NUC 实测，2026-09-30）

- 已有：java/javac 21、adb、/dev/kvm；4 核、7 GB 内存、378 GB 空闲磁盘。
- 没有：Android SDK、Gradle、sdkmanager、模拟器；ANDROID_HOME 为空。
- 第一步装 cmdline-tools、platform-tools、一个 platforms;android-3x、build-tools；Gradle 用项目自带 wrapper。全局安装前必须先问用户（AGENTS 规则）。
- 7 GB 内存偏紧：设 `org.gradle.jvmargs=-Xmx2g`，验证以真机 `adb install` 为主，模拟器为辅。
- agent 无法点真机。每个里程碑交付可安装的 debug APK，由用户试用；同时用 JVM 单元测试覆盖纯逻辑（§12）。
- 目录：新建 `android/`，与 `web/` 平级，不动 `web/ui`、`web/static`。`.gitignore` 加 `android/.gradle`、`android/**/build`、`local.properties`、`*.jks`。

## 3. 服务器连接与认证

### 3.1 服务器地址
首次启动让用户输入 Base URL（如 https://inkcal.example.com，内网也可以填 `IP:端口`），存 DataStore，设置页可改。外网走 FRP + 反向代理（建议上 HTTPS）。

**地址规范化（`domain/ServerUrl`，已实现）**：用户只填 `192.168.5.158:5800` 这类裸地址时自动补 `http://`；结尾统一补 `/`（Retrofit 要求 baseUrl 以 `/` 结束）；首尾空白去掉；空串或解析不出的返回 null（UI 提示「请填写服务器地址」）。规范化后的值才落 DataStore，**换服务器时会同时清掉 cookie 与记录缓存**，避免把上一台的会话/数据带过去。

**明文 HTTP 策略（2026-10-02 变更）**：早期做法是在 `network_security_config.xml` 里逐个列出放行的私网地址，但那是把真实内网地址写进仓库和 APK（而 APK 是公开下载的），而且该配置不支持网段、每换地址就得改代码重新发版。现在改成 `cleartextTrafficPermitted="true"`，不再放白名单——App 只连用户自己填的地址，白名单的实际防护收益有限。**服务器上了 HTTPS 后应把它改回 `false` 收紧**。

### 3.2 登录（Flask session cookie）
- 服务端认证是可选的：未设 INKCAL_USER/INKCAL_PASS 时无需登录。
- 未登录访问 `/api/*` 返回 HTTP 401，体为 error=unauthorized（只有页面路由才 302 到 /login，App 不用页面路由）。
- 登录：`POST /api/login`，JSON 体含 `user` 与 `password` 两个字段（注意是 password，不是 pass）。成功 200 且 Set-Cookie 会话 cookie（HttpOnly、SameSite=Lax、30 天）；401 bad credentials；429 too many attempts（每 IP 300 秒内 5 次失败）。
- 登出：`POST /api/logout`。
- 用 OkHttp CookieJar 持久化到 DataStore。任何请求收到 401：清 cookie、弹登录页，登录成功后回原页面重试。
- 启动时不预先探测是否需要登录，直接请求 `/api/data-version`：200 即免登录或已登录，401 进登录页。
- 账号密码只在登录时使用，不明文落盘；如要自动重登，用 EncryptedSharedPreferences，先问用户。

### 3.3 超时（慢操作很多）
| 场景 | 读超时 |
|---|---|
| 普通 GET/PUT/DELETE | 20 s |
| 图片（/api/image、/api/local-image） | 20 s，失败后重试一次 |
| POST /api/reanalyze | 120 s |
| POST /api/chat/send | 300 s（同步跑 agent loop，非流式） |
| POST /api/analyze-album-photo、POST /api/manual-upload | 300 s |

这些请求期间 UI 显示进度并禁用重复提交。用户离开页面时不要取消请求（服务端已在执行，取消只会丢结果），用 application 级 scope 发起。

**实现注记（0.9）**：按接口分超时由 `AppRepository.kt` 里的 `TimeoutInterceptor` 做，映射函数是 `readTimeoutSecondsFor(path)`（按后缀匹配，所以 Base URL 带子路径也认）。两点值得记：
- 单张 `manual-upload` 用 300 s，但 `analyze-album-photo` 用 **600 s**——一次最多带 10 张、整批过一次 Luna harness，AGENTS.md 记录过一轮可跑 ~11 分钟，300 s 不够。
- 之前这里漏做了分超时（全用 20 s），症状是**服务端已经写完记录、客户端先报失败**：用户看到"重新分析失败"，回去一刷新记录其实是新的。`TimeoutTest` 现在钉住了这张表。

## 4. 时间与日期（必须照做，AGENTS §1 铁律）

- 一条记录属于哪天 = `photo_time` 字符串前 10 位（YYYY-MM-DD，照片拍摄地当地日历日）。严禁把 photo_time 解析成 UTC 或系统时区的 Instant 再取日期，会造成凌晨照片日期倒退一天。
- photo_time 形如 `2026-09-30T12:34:56+08:00`。显示时分取下标 [11,16) 子串；详情的「时间+时区」：把 T 换成空格取前 16 位，再拼末尾 ±HH:MM（有则拼）。一律用字符串切片，不走 java.time 转换。
- 「今天」= 东八区当前日期：`LocalDate.now(ZoneId.of("Asia/Hong_Kong"))`，不是手机本地时区（与网页 hktNow 一致）。
- 周一为一周起点。周视图不能前进到未来周，月视图不能前进到未来月。
- 文案：星期 周日/一/二/三/四/五/六；短日期 8月27日；详情 2026年08月27日。

## 5. 数据模型（JSON 契约）

数值字段可能是整数或小数，统一用 Double。DTO 必须 ignoreUnknownKeys=true，缺失字段给默认值。

### 5.1 Record（已分组的一餐，只含主记录）
- id: Int；asset_id: String（幂等键，手动记录形如 manual-2026…）
- source_type: immich / photoprism / manual；可能缺失，缺失时 asset_id 以 manual- 开头则为 manual，否则 immich
- photo_time: String
- thumbnail_url: 可空，上游原始 URL，需经 /api/image 代理
- replacement_image: 可空，本地替换图路径，经 /api/local-image 取
- meal（短标题）、meal_detail（明细，旧记录可能为空串）
- calories、protein_g、carbs_g、fat_g
- confidence: high / medium / low
- emoji: 可空，纯文本补录时代替缩略图
- merged_into: 主记录恒为 null
- photos: List<Photo>，组内全部照片，主行在前，其余按 photo_time 升序
- 区间查询（start+end）的记录额外带 date；单日查询不带。客户端统一用 `photo_time.take(10)` 得到日期，不依赖 date 字段。

### 5.2 Photo（photos 元素）
asset_id、thumbnail_url、photo_time、meal、meal_detail、calories、protein_g、carbs_g、fat_g、emoji。刻意没有 confidence 和 replacement_image。

### 5.3 同餐组语义（UI 必须理解）
- 主行 merged_into 为 null，一餐一张卡；photos 数量大于 1 时卡片显示角标 ×N（含义：N 张照片已合并为一餐）。
- 形态 A（状态延续，吃前/吃后）：从行数值全为 0，总值只在主行。详情里从行显示「已并入整餐估算」，绝不显示 0 kcal（2026-08-29 事故教训）。判据：asset_id 不等于主行 asset_id，且四个数值全为 0。
- 形态 B（独立条目）：从行带自己的数值；服务端已把组头数值累加、餐名用 ` + ` 拼接。客户端直接显示组头，不要再累加。
- summary 由服务端按原始行求和，两种形态都正确；客户端不要对 photos 重算热量。

### 5.4 Summary
键名是 calories、protein、carbs、fat、meals（不带 _g）。

### 5.5 Burn
date、active_kcal、steps、source、created_at、updated_at；当天无数据时整体为 null。

### 5.6 Decision（AI 决策审计）
id、session_date、action（add/update/skip）、relation（new_meal/same_meal/rejected 或空）、asset_ids: List<String>、target_asset_id、group_with、reasoning、prompt_for_gemini、result。
文案：action → 新增/合并更新/跳过；relation → 新餐/同餐/非食物。

### 5.7 聊天
- Session：id、title、created_at、message_count、last_active。
- Message：id、session_id、role（user/assistant）、content、tool_log: List<ToolCall>、response_id、created_at。
- ToolCall：name、args（对象）、result（对象，结构随工具变化，见 §10）。

## 6. API 清单（相对 Base URL，JSON，UTF-8）

日期参数一律 YYYY-MM-DD，非法返回 400 带 error 字段。

### 读
| 方法 路径 | 参数 | 返回 |
|---|---|---|
| GET /api/dates | 无 | 有记录日期的字符串数组，**新→旧**（`src/db.py::get_available_dates` 为 `ORDER BY d DESC`）。最后一项即最早日期，用来判断时间轴是否到底 |
| GET /api/records | date，或 start+end（不超过 366 天）；都缺省=今天 | 单日：date、records、summary、burn。区间：start、end、records、summary、burns（日期到 Burn 的字典） |
| GET /api/today | 无 | 同单日 |
| GET /api/week | start（任意日期，服务端取该周周一；缺省本周） | start、end、by_day（日期到 records/summary/burn）、summary、burns |
| GET /api/data-version | 无 | version（字符串）、pending |
| GET /api/decisions | date（必填） | date、decisions |
| GET /api/burn | date（缺省今天） | date、burn |
| GET /api/settings | 无 | chat_window、user_height、user_weight、user_birthdate、user_gender、bmr。身高/体重/出生日期未填时为空串，user_gender 默认返回 "male"（不会空）；bmr 为 null 表示未填齐。不要拿空串自己判断是否填齐——BMR 由服务端给 |
| GET /api/album-photos | cursor（缺省今天）、days（1 到 30，默认 7） | dates（date + photos[asset_id、thumbnail_url、photo_time、source、classified_non_food]）、next_cursor |
| GET /api/chat/sessions | 无 | sessions，新→旧 |
| GET /api/chat/messages | session_id（缺省或无效=最新会话） | session_id、messages；一条会话都没有时 session_id 为 null、messages 为空 |
| GET /api/image | url（URL 编码） | 图片字节 |
| GET /api/local-image | path（URL 编码） | 图片字节 |

`/api/skipped` 存在，但当前网页 UI 不展示，App 也不做。

### 写
| 方法 路径 | 请求 | 响应/错误 |
|---|---|---|
| PUT /api/settings | JSON，只传要改的键：chat_window（5 到 50，越界被钳制）、user_height（50 到 260）、user_weight（20 到 300）、user_gender（male/female）、user_birthdate（YYYY-MM-DD） | 返回同 GET；非法值 400，error 为 invalid <key>。该路由只支持 GET 和 PUT |
| PUT 或 POST /api/burn | date、active_kcal、steps、source | ok、burn |
| DELETE /api/record | asset_id、mode（meal 默认，或 photo） | ok、deleted（asset_id 列表）、promoted；404 record not found |
| POST /api/reanalyze | asset_id、notes（必填非空） | ok、record；400 缺参；404；502 image unavailable（纯文本补录无图或原图取不到）；500 缺 Gemini key |
| POST /api/analyze-album-photo | 见 §8.5 | 见 §8.5 |
| POST /api/manual-upload | multipart，见 §8.5 | 见 §8.5 |
| POST /api/move-record | asset_id、date | ok、asset_id、old_date、new_date、immich_matched；404 |
| POST /api/chat/sessions | 空 | ok、session_id（App 用惰性新建，不调用，见 §10） |
| POST /api/chat/send | session_id（可空）、message | 成功 ok、session_id、reply、tool_log；失败 502，带 error、tool_log、session_id；空消息 400 |
| POST /api/login、POST /api/logout | 见 §3.2 | |

`/api/upload-image`（替换某条记录的图片）前端没有任何调用，App 不做。

**App 当前未使用**（实现状态，不是遗漏）：`GET /api/today`（用 `/api/records?date=` 代替）、`GET /api/week`（周视图改用区间接口，见 §8.2 注记）、`GET /api/burn` 与 `PUT/POST /api/burn`（消耗只读展示，没有录入 UI）、`/api/skipped`。`/api/chat/*` 自 0.10 起已全线在用。

## 7. 热量缺口与 BMR（客户端唯一要算的业务公式）

```
tdee(burn, bmr)    = bmr != null ? bmr + (burn?.active_kcal ?: 0) : 2500
deficit(kcal, ...) = tdee - kcal      // 正=有缺口，负=超标
```
三级降级：有 BMR 和当天 burn → BMR + active；有 BMR 无 burn → 仅 BMR；无体征 → 固定 2500（仅兜底常量）。

- bmr 来自 GET /api/settings，App 启动拉一次缓存在全局（单例 Repository）；设置页保存成功后用响应里的 bmr 刷新缓存并触发全局刷新。
- 日/周/月里「超标变红」的阈值都用 TDEE，不是 2500（无体征除外）。
- BMR 由服务端算，客户端不要自己算。

## 8. 页面与行为规格

全局结构：Scaffold + Material 3 NavigationBar，三个顶级目的地：记录 / Calo / 设置。
- 记录与 Calo 之间可用 HorizontalPager 左右滑动切换（可选，做不好就只保留点击），设置页不参与滑动。
- 默认落在哪页未拍板，先默认「记录」，做成常量。
- 大屏（600dp 以上）可选 NavigationRail + Calo 常驻侧栏（对应网页 PC 三栏），非首期。
- 全局提示用 SnackbarHost（2.6 秒，错误用错误色）。
- **Inset 约定（2026-10-03 修复顶栏空白后拍板）**：MainScaffold 的 Scaffold 已把状态栏 inset 消化进 innerPadding，页面内嵌的 TopAppBar 必须显式 `windowInsets = WindowInsets(0, 0, 0, 0)`，否则状态栏高度被垫两次、标题与列表之间出现大段空白。全屏 Dialog（如选择照片）不经 Scaffold padding，其 TopAppBar 保留默认 inset。
- 全局刷新信号：一个 SharedFlow 或计数器 bump，任何写操作成功后触发，各页监听后重拉已加载范围；§8.6 的后台轮询也触发它。

### 8.1 记录页：日视图（默认子视图）

> **状态：✅ 已实现**（0.2 日视图与餐卡；0.3 补下拉刷新 + 冷启动磁盘缓存；0.7 补日/周/月切换与月视图跳转）
- TopAppBar 标题 = 当前可见日期（今天显示「今天 · 9月30日」，副标题「周三」）；动作：视图切换、「选择照片」入口（可用 ExtendedFloatingActionButton）。
- 视图切换用 SingleChoiceSegmentedButtonRow：日 / 周 / 月。
- 日视图是无限向下滚动的时间轴，LazyColumn，最新日期在顶。
  - 初始加载 end=今天、start=end 减 6 天，调 GET /api/records?start&end；触底再加载更早 7 天。
  - 用 /api/dates 的最早日期作 minDate，end 小于 minDate 即到底。
  - 客户端按 photo_time 前 10 位分日；日内按 photo_time 倒序，相同则按 asset_id 倒序；日期组按日期倒序。
  - 每日一个 stickyHeader：左「8月27日 周三」；右当天总摄入 kcal（对主记录求和）、P/C/F 克数（有宏量才显示）、缺口 chip（绿「缺口 N」/ 红「超 N」，N 取整）。今天的 kcal 与缺口前加 ~ 并弱化显示（表示截至目前，已拍板照显不隐藏）。
  - 没有记录的日期不渲染；整体无记录时显示引导空态。
  - 顶栏标题随滚动变化：取可见的最新日期组，用 LazyListState 的 visibleItemsInfo 推导。
  - 支持 jumpTo(date)：必要时循环加载更早分片直到覆盖该日期（上限 60 片）再 scrollToItem。月视图点日期走它。
- 重载策略：收到 bump 后重拉已加载的整个范围并整体替换，保留滚动位置；失败保留旧数据不清空。

**Android 侧的缓存与刷新（0.3 起，已实现）**：
- 冷启动是 **stale-while-revalidate**：先画 `filesDir/records-cache.json` 里的上次结果，再后台重拉覆盖。**不做**「缓存没过期就不请求」——服务端 cron 随时写新记录，缓存永远不算可信。
- 下拉刷新重拉的是**已加载的整个范围**（上限 365 天），不是只重拉最近 7 天，否则会把用户翻过的历史抖掉。
- 缓存 payload 带 `baseUrl`，换服务器即失效（`saveBaseUrl` / `logout` 也会主动清）；写入先落临时文件再改名，避免写一半被杀留下坏 JSON；解码失败一律当「没有缓存」，不崩。
- 三个 loading 状态要分开：`initialLoading`（首次且无缓存，整屏转圈）、`loadingMore`（触底，底部条）、`refreshing`（下拉，顶部指示器）。
- 请求序号防抖：每次加载带递增 id，只采纳最新响应（对应网页 _loadSeq）。

### 8.2 周视图

> **状态：✅ 已实现（0.7）**
- 顶栏「本周」或「MM.DD – MM.DD」，左右箭头切周，不能进入未来周，提供「回到本周」。
- **实现注记（2026-10-02）**：原本写的是 `GET /api/week?start=周一`，实际改用 `GET /api/records?start&end`——周接口的 `by_day`/`summary` 都能由区间数据在客户端算出来，而月视图又必须走任意区间，两条路合成一条少一半代码。没有用到的 `/api/week` 也不要再接回来。
- 上半部分 7 根柱的双层柱状图（唯一需要自绘，Canvas 约 100 行）：底层灰柱高度=当日 TDEE，上层较窄柱（约 55% 宽）=当日摄入，摄入大于 TDEE 时上层变红；无摄入不画上层。归一化：max = max(各日 kcal 与 tdee 的最大值, 1)；摄入柱高度 max(kcal/max*100, 2)%（有摄入时），TDEE 柱同理。柱下标签 一到日，点击弹出「摄入 X / 消耗 Y」。
- 汇总行：「本周已记录 N 天 · 日均 X kcal · 累计缺口 Z kcal」。累计缺口只统计有记录的天（漏记不计，避免 0 摄入虚增缺口）；日均=总摄入/有记录天数；不换算体重（已拍板）。
- 下半部分按日分组的餐卡时间轴（新日期在前，日内倒序，规则同 §8.1）。点卡片进详情。

### 8.3 月视图

> **状态：✅ 已实现（0.7）**
- GET /api/records?start=月初&end=月末；按日累加 records 的 calories 得每日 kcal，burns 字典给 TDEE。
- 顶栏「2026年9月」，左右切月，不看未来月。
- 周一起始的 7 列网格（格子 aspectRatio 1）。**实现注记**：用普通 Column/Row 铺 42 个格子而不是 LazyVerticalGrid——外面已经有一层滚动，套 Lazy 反而会嵌套冲突。每格：日期数字 + 环形进度。直接用 Material 的 CircularProgressIndicator，progress = min(kcal/tdee, 1)，不要自绘圆环。
- 二值语义（已拍板）：kcal/tdee 大于 1 → 红环（超消耗），否则绿环（有缺口）。kcal 为 0 不画环。数字保持中性色；有记录的日期加粗；今天加强调描边。图例两项：有缺口 / 超消耗。
- 点某天 → 切到日视图并 jumpTo(date)。

### 8.4 餐卡与详情

> **状态：✅ 已实现**（0.2 餐卡；0.4 详情页；0.5 补卡片 🤖 角标）

卡片（Material Card）：
- 左侧 96dp 方形缩略图；右侧：meal（粗体，允许折行，不截断）、meal_detail（小号灰字，最多 2 行省略，空则不渲染）、HH:mm、来源标签（手动/Immich/PhotoPrism）、置信度（高/中/低，低置信度要有可见提示）、宏量 P / C / F（用字母，三者全 0 则隐藏）、kcal。
- photos 数量大于 1 → 角标 ×N（BadgedBox）。
- 有覆盖该记录的 Decision → 显示 🤖 角标，无障碍描述「Luna 决策：新增 · 新餐」。决策按日期预取并缓存；匹配规则：decision.asset_ids 含该记录 asset_id，或 decision.target_asset_id 等于该记录 asset_id。
- 无图（thumbnail_url 与 replacement_image 都空，典型是纯文本补录）：居中显示 emoji，按字符数（codePoint 计数）自适应字号：1→38sp、2→30sp、3→24sp、更多→20sp；emoji 也空则 🍽️。
- 整卡可点，点击打开详情。聊天产物里的卡片同样可点打开详情。

图片地址规则（写成单元测试）：
```
replacement_image 非空 → {base}/api/local-image?path={urlencode(replacement_image)}
否则 thumbnail_url 非空：
  卡片缩略图：把 thumbnail_url 中的 /original 替换为 /thumbnail?size=thumbnail，再 {base}/api/image?url={urlencode(结果)}
  详情大图：{base}/api/image?url={urlencode(thumbnail_url)}（不替换）
否则：无图
```
卡片缩略图必须用 size=thumbnail（约 7KB），不要换成 preview（约 157KB，慢网下很痛）。Coil 配磁盘缓存；图片请求走同一个带 cookie 的 OkHttpClient。

详情页（推荐全屏 Dialog 或新页面，便于大图缩放）：
- 大图区：当前选中照片大图，支持双指缩放；多图时 HorizontalPager 左右滑动，显示 i / N，下方 LazyRow 缩略图条，选中高亮。照片按 photo_time 升序排列（后端只保证主行在前，不是全序，客户端必须自己排）。
- 信息区：meal、meal_detail（全文不截断）、kcal 与 P/C/F、副行「详细时间 · 来源 · 置信度 高/中/低」。
- 多照片组才显示「照片明细」：每张一行（缩略图、HH:mm）；形态 A 从行显示「已并入整餐估算」；形态 B 显示该张的 meal、meal_detail（2 行省略）、kcal 与 PCF。点行切换大图。
- AI 决策折叠块（有决策才显示）：标题「🤖 AI 决策」，展开后每条：动作 · 关系、reasoning、prompt_for_gemini（标签「给 Gemini 的提示词」）。匹配范围=组内全部 asset_id（含 target_asset_id），按 rec 的日期取。
- 重新分析：仅当组内至少一张照片有 thumbnail_url 或 replacement_image 才显示入口（纯文本补录隐藏，后端恒 502）。
  - 点「重新分析」展开内联表单：多行输入（占位「修正说明，例：米饭只吃了一半 / 其实是玉米猪肉馅」），notes 必填，空则提交按钮禁用。
  - 提交 POST /api/reanalyze（asset_id 用主行的），进行中文案「分析中…（约半分钟）」，期间禁用表单。
  - 成功后必须重拉当天分组并原地替换（组级联合重估会把形态 B 从行清零，photos 显示必须重拉，不能只用响应里的 record 覆盖）。Snackbar「已更新：{calories} kcal」。失败「重新分析失败: {error}」。
  - 打开表单时解除删除的武装态。
- 删除有两个互不干扰的入口，都是两步确认：
  - 删除整餐：第一次点击变为「确认删除整餐？」（3 秒后自动还原），再点才发 DELETE /api/record（主行 asset_id，mode=meal）。成功：关闭详情、触发全局刷新、Snackbar「已删除整餐，照片不会再被同步」。
  - 单张移除（仅多照片组，行内 ✕）：独立武装态，第一次点变「确认?」（3 秒还原），再点发 mode=photo。响应的 promoted 非空表示删的是主行、最早的从行晋升为新主行，客户端以 promoted 为锚点重拉当天分组并更新详情；重拉后若按锚点找不到就按已知 asset_id 集合有交集再找，仍找不到则关闭详情并提示「已移除，该餐没有剩余照片」。形态 A 删主行后晋升行是 0 值，提示「已移除主照片，这餐数值需要重新估算（可点下方「重新分析」）」；否则提示「已移除照片，记录已更新」。
  - 原生实现可用 AlertDialog 做确认，但必须保留两步，且整餐与单张不能共用同一个确认状态。
  - 删除后服务端会把资产写入忽略列表，客户端无需处理。
- 原地刷新 refreshGroup：请求 GET /api/records?date={该记录日期}，按 promoted 或当前主行 asset_id 找，找不到按已知 asset_id 交集找，都找不到视为组已消失。刷新失败不要关闭详情，提示「操作已完成，但刷新失败——关闭后页面会自动更新」。
- 系统返回键关闭详情。

### 8.5 选择照片（补漏入口）

> **状态：✅ 已实现（0.8）**——相册多选与本地上传两条路径都在。
两条来源都必须保留。

(a) 相册未处理照片（GET /api/album-photos）：
- 全屏页或 ModalBottomSheet。按日期分组的缩略图网格（LazyVerticalGrid + 日期 header），滚动到底自动加载更早 7 天：cursor 从今天开始，下一页用响应的 next_cursor；某页 dates 为空视为没有更多。
- 多选，最多 10 张；超出 Snackbar「一次最多选择 10 张」（错误态）。选中项保存 asset_id、source、date、thumbnail_url、photo_time。classified_non_food 为 true 的照片可加角标（曾被判非食物，供用户纠错）。
- 底部操作条：已选 N 张、清除、「分析」。提交 POST /api/analyze-album-photo，体为 items 数组，每项含 asset_id、source、date、thumbnail_url、photo_time。进行中文案「正在分析 N 张照片（同一餐会合并为一条记录）…」，禁用重复提交，超时 300 s。
- 响应：ok、results（asset_id、status、record、date）、summary（total、added、already_processed、not_food、failed）。Snackbar 拼接：「已添加 {added} 条记录」+「，{already_processed} 张已在记录中」+「，{not_food} 张非食物已跳过」+「，{failed} 张分析失败」；failed 大于 0 用错误态。完成后触发全局刷新；failed 小于选中数时清空选择并关闭页面。
- 错误：too many items (max 10) → 「一次最多选择 10 张」；其他 → 「批量分析失败: {error}」。整批先校验，任一项缺 asset_id、source 或合法 date，整批 400。500 表示服务端缺 GEMINI_API_KEY。
- 缩略图 thumbnail_url 是上游 URL，同样经 /api/image 代理显示。
- 单项 shape（不带 items）仍被后端支持，App 只用批量 shape。
- 分析进行中禁止关闭页面（网页版 close 有 analyzing 保护）。

(b) 本地上传（对应网页的拖拽/粘贴/选文件）：
- 用系统 Photo Picker 选一张图，POST /api/manual-upload（multipart，字段名 image；**不传 date 参数**，网页版不传）。
- 日期判定在服务端：服务端读 EXIF，有 EXIF 按拍摄时间入库；无 EXIF 用当天兜底。`_date_source` 是三态：`"exif"`（读到 EXIF）、`"user"`（调用方传了 date 参数，App 不传，不会出现）、`"fallback"`（都没，用当天）。**客户端只需要判 `== "fallback"`，不需要读 EXIF，不需要预先弹日期选择**。
- 响应：成功 ok、record、matched、date、_date_source；409 already processed（提示「此照片已在记录中」）；422 not food（提示「此图片不是真实食物，无法记录」）；400 unsupported mime 或 invalid image；500 缺 Gemini key（提示「上传失败: …」）。成功且 _date_source 不是 fallback → Snackbar「已添加记录」并关闭。
- **无 EXIF 的日期修正（_date_source 为 fallback 时）**：上传已入库，此时显示日期修正区：文案「未能读取拍摄日期：{record.meal 或 上传记录}」+ 日期输入（原生用 DatePicker，默认值 = 响应的 date）+ 两个动作：
  - 保存：POST /api/move-record {asset_id, date}，成功 → Snackbar「已添加记录」并关闭；失败 → 「调整日期失败: {error}」。
  - 保持当前日期：不发请求，直接 Snackbar「已添加记录」并关闭。
- 允许的 MIME（服务端 ALLOWED_IMAGE_MIME）：image/jpeg、image/png、image/heic、image/heif、image/webp。
- 上传进行中禁止重复选择文件。

### 8.6 后台数据同步（data-version 轮询）

> **状态：✅ 已实现（0.12）**——`AppRoot` 里的 `DataVersionWatcher` 在连上服务器后按 `LifecycleStartEffect`（= `repeatOnLifecycle(STARTED)`）每 30 秒轮询。
>
> 实现注记：
> - 基线（上次见到的版本号）存在 `AppViewModel` 里，**不是**存在轮询协程里。协程进后台会被取消，基线跟着丢的话，回前台第一次轮询只会把「后台期间 cron 写的新版本」记成新基线，那些记录就再也触发不了刷新——正是这个功能要解决的问题。
> - 版本变化 → `dataSignal.bump()`；记录页收到后重取已加载日期的决策（`refreshDecisions`，只清不取的话 🤖 角标要等滚动才回来）、让区间视图原地重拉、再刷日视图。
> - 失败静默，不弹任何提示。

行为：cron 在后台写记录，App 在前台每 30 秒 GET `/api/data-version`，首次只记基线，版本变化时刷新记录与决策；进后台停止，回前台立即轮询一次。用 `repeatOnLifecycle(STARTED)` 实现，不引前台服务或 WorkManager。

### 8.7 设置页

> **状态：✅ 已实现（0.5）**
- 表单：身高（cm，50 到 260）、体重（kg，20 到 300）、出生日期（DatePicker）、性别（SingleChoiceSegmentedButtonRow，男/女）、Calo 上下文窗口（Slider 5 到 50，步进 1，默认 20）。
- 「保存」发 PUT /api/settings（只发已填的键），成功后显示服务端返回的 bmr（kcal/天取整，未填齐显示「—」），刷新全局 BMR 缓存并触发全局刷新，Snackbar「设置已保存」。客户端校验范围与服务端一致。
- 另设「服务器」分组：**数据概况**、Base URL、登出、（可选）清除图片缓存。
  - 数据概况由 `/api/data-version` 的指纹解析而来（`domain/DataVersion`）：`数据概况：1245 条记录 · 最后写入 10-03 12:10（HKT）`。**指纹里的时间戳是 UTC**（SQLite `datetime('now')`），必须转 HKT 再显示。注意**不能按 `:` 切分指纹**——时间戳自带冒号、空字段又会让段数不定，条数取前缀正则、时间戳用正则全量抓取。解析不出来就显示「—」。
  - 概况的刷新点：连接探测（`probe`/`login`/`logout` 后由 `AppViewModel.applyProbe` 顺手解析）与 §8.6 每 30 秒的轮询，不用额外请求。
- 末尾「关于」分组只放一行 **App 版本**（只显示 `BuildConfig.VERSION_NAME`，不带版本代码——已拍板，版本代码是给 Android 比大小的，给人看没有意义）。为此 `buildFeatures.buildConfig = true`，取的就是 `app/build.gradle.kts` 里发布的那个版本号。**别把它和「数据概况」混在一起**——一个是「装的哪个包」，一个是「服务端有多少数据」，此前并列显示过、被用户指出看不懂。
- Calo 页顶部不放设置入口（已拍板）。

### 8.8 系统集成（首期后做）

> **状态：未做**（首期范围外）
- 分享入口：ACTION_SEND 的 image/* Intent Filter，把照片送进 §8.5(b) 的上传流程。
- 桌面小组件（Glance）：今日摄入 / TDEE / 缺口，数据来自 GET /api/today 与 GET /api/settings。
- 不做：推送通知、后台同步热量消耗、Health Connect（需要另行设计，burn 目前由 NUC 上 cron 写入）。

## 9. 写入通用约定

asset_id 是幂等键。重复提交会得到 409，客户端把 409 当作「已在记录中」而不是错误。提交进行中禁用按钮。

## 10. Calo 聊天页

> **状态：✅ 已实现（0.10）**——消息流、会话管理、过程层折叠、产物分流、删除确认卡都在。
>
> **实现注记**：
> - **Markdown 是子集实现，不是 Markwon**。`domain/MarkdownText` 把文本解析成纯 Kotlin 的块/行内结构（段落、粗体、斜体、行内代码、围栏代码块、列表、引用、链接），Compose 再渲染成 `AnnotatedString`。不引 Markwon 是因为它属 Android View 体系、在 Compose 里要额外包一层，而这里要覆盖的语法用几十行就够。表格、嵌套列表、脚注不支持（后端也不会输出）。换行按**硬换行**（每行自成一段），与网页版一致。
> - **跨 Tab 刷新**用 `AppContainer.dataSignal`：Calo 写成功后 `bump()`，记录页订阅后重拉。两个 Tab 的 ViewModel 互相看不见（各自 `viewModel()`），共享计数器比把记录页 VM 提到 Activity 级再往 Calo 传回调轻。
> - 删除确认卡的状态**只存本地**（`ChatViewModel.deleteStates`），历史消息重开即恢复待确认——不要试图持久化，那是网页版的行为且是刻意的。

- 消息流用 LazyColumn，新消息追加后滚到底。输入区：OutlinedTextField + 发送 IconButton；发送中禁用并显示「Calo 正在思考…」占位气泡。
- 空会话引导：标题「我是 Calo」、简介、4 个快捷提示 SuggestionChip：「今天摄入了多少热量？」「记一下昨天下午吃了包薯片」「帮我查查昨天的午餐」「最近吃过什么高蛋白食物？」，点击即发送。
- 会话管理：
  - 进入时优先读 DataStore 里保存的 session_id 调 GET /api/chat/messages?session_id=…，回退到不带参数（服务端给最新会话）。
  - 顶栏：历史会话（ModalBottomSheet 列表，标题缺省显示「新会话」，时间取 last_active 或 created_at 的前 16 位并把 T 换成空格）、新建会话。
  - 新建是惰性的：点「＋」只清空本地状态与保存的 session_id，不调用 POST /api/chat/sessions；首条消息发送时 session_id 为 null，由服务端创建（避免空会话占位）。
  - 发送成功后用响应里的 session_id 覆盖并持久化，再刷新会话列表（标题更新）。
- 发送流程（乐观更新）：先本地追加用户消息（临时 id），再 POST /api/chat/send。失败（非 2xx、ok 不为 true 或网络异常）→ 移除乐观消息，把文本放回输入框，Snackbar 报错（「发送失败，请重试」/「网络异常，发送失败」）。成功 → 追加 assistant 消息（content=reply，带 tool_log）。
- 写操作联动：本轮 tool_log 里只要有 add_record、edit_record、reanalyze_record 且 result.ok 为 true，触发全局刷新。
- Markdown：用户消息为纯文本气泡；assistant 气泡用 Markwon 渲染（段落、粗体、列表、行内代码、代码块、引用、链接，换行按硬换行）。
- 工具过程折叠 + 产物分流（已拍板，务必照做，不要把每次工具调用都渲染成大卡片）：
  - 过程层：一条 assistant 消息若有 tool_log，顶部放默认折叠的「已执行 N 步操作 ▾」。展开后每步一行：✓ + 步骤标题，右侧可选徽标；点某步再展开「参数」与「结果摘要」。
  - 步骤标题：优先 args.intent（去空白后非空）；否则工具名标签 + 参数兜底：

    | 工具 | 标签 | 兜底附加 |
    |---|---|---|
    | get_records_in_range | 查询餐食记录 | (MM-DD) 或 (MM-DD~MM-DD)，取 start、end 的 slice(5) |
    | get_intake_stats | 统计摄入情况 | 无 |
    | search_meals | 搜索餐食记录 | 「{keyword}」 |
    | get_decisions | 查看 AI 识别决策 | (MM-DD)，取 date |
    | edit_record | 修改餐食记录 | 无 |
    | add_record | 补记餐食记录 | 无 |
    | reanalyze_record | 重新分析餐食记录 | 无 |
    | request_delete_record | 请求删除餐食记录 | 无 |

  - 步骤徽标：records/search → 「{n} 条」（result.records 数量，为 0 不显示）；stats → 「{round(total.calories)} kcal」；get_decisions → 「{count 或 decisions 数量} 条」。
  - 参数展示：把 args 去掉 intent 键后转 JSON 字符串（等宽小字）。
  - 结果摘要：records/search → 「匹配 N 条记录」；stats → 「{kcal} kcal」（无 total 显示 error）；get_decisions → 「审计决策 N 条」；add_record → 「新增「meal」kcal kcal」；edit/reanalyze → 「「after.meal」after.calories kcal」；request_delete_record → 「已生成待确认删除卡」；失败时显示 result.error。
  - 产物层（在过程层下方、正文上方，按 tool_log 顺序逐个渲染）：

    | 工具 | 是否渲染 | 内容 |
    |---|---|---|
    | add_record | 始终（有 result.record） | 标题「📝 已添加餐食记录：」+ 餐卡 |
    | edit_record / reanalyze_record | 始终（有 result.after） | 标题「✏️ 已更新餐食记录：」或「🔄 已重新分析餐食记录：」+ 餐卡 |
    | request_delete_record | 始终（有 result.confirm_card） | 删除确认卡（见下） |
    | get_intake_stats | 始终（有 result.total） | 统计卡：「{start} 至 {end} 摄入汇总」，格子：总热量 kcal、餐数、蛋白质 g、碳水 g、脂肪 g |
    | get_records_in_range / search_meals | 仅当本轮 tool_log 没有任何写工具（add/edit/reanalyze/request_delete）且 result.records 非空 | 标题「找到 N 餐：」（search 为「搜索「{keyword}」找到 N 餐：」）+ 餐卡列表 |

    统计卡的键：后端同时给两套别名（meals 与 count、protein 与 protein_g 等），已拍板保留；客户端读任一套并兜底 0。
    反例：用户说「记一根玉米，分量和昨天差不多」，Calo 会先查今天（查重）、昨天（份量参考）再 add；此时两次查询只留在折叠步骤里，只展示新增卡一张。
    get_decisions 没有产物卡，只在步骤里。
  - 聊天里的餐卡点击要能打开 §8.4 详情。工具返回的 record 缺字段，需要 normalizeRecord：补 date（photo_time 前 10 位）、confidence 缺省为 low、若无 photos 则用自身字段合成单元素 photos（含 asset_id、photo_time、meal、meal_detail、calories、thumbnail_url、replacement_image、emoji）。
- 删除确认卡（安全契约，AGENTS §4：严禁绕过确认删除）：
  - 文案：「确认删除 {meal 或 该餐}（{HH:mm}，{calories} kcal）吗？」，按钮「确认删除」（危险色）与「取消」。
  - 只有用户点「确认删除」才调 DELETE /api/record（confirm_card.asset_id，mode=meal）；成功 → 卡片变「已删除该餐记录」、触发全局刷新、Snackbar「已删除记录」；失败 → Snackbar 错误，卡片保持可重试；请求中按钮文案「删除中…」并禁用两个按钮。「取消」只把卡片置为「已取消删除」，不发请求。
  - 已确认/已取消状态只存本地，历史消息重开时重新显示为待确认，与网页版一致，不要试图持久化。
  - 绝不能让模型结果（tool_log）直接触发删除。
- 不做：聊天传图、流式输出、工具调用中途进度（后端非流式，tool_log 只在结束时一次性返回）。

## 11. 工程结构（实际）

下面是**已经落地的**结构，不是建议稿——接手时按这个改，别再另起一套。

```
android/
  app/src/main/java/com/jerrylf/inkcal/
    MainActivity.kt
    data/      Api.kt  Dto.kt  AppRepository.kt  AppContainer.kt
               SettingsStore.kt  CookieStore.kt  RecordsCache.kt  BmrCache.kt
               DataChangeSignal.kt
    domain/    TimeFmt.kt  Tdee.kt  ImageUrl.kt  MealGrouping.kt  Decisions.kt
               BodyMetrics.kt  Periods.kt  WeekStats.kt  MonthGrid.kt  ServerUrl.kt
               ChatTools.kt  MarkdownText.kt  DataVersion.kt
    theme/     Color.kt  Theme.kt  Type.kt
    ui/
      app/     AppRoot.kt  AppViewModel.kt  MainScaffold.kt  ImageLoader.kt
      setup/   SetupScreen.kt
      records/ RecordsTab.kt  RecordsScreen.kt  RecordsViewModel.kt  RangeViewModel.kt
               MealCard.kt  MealDetailDialog.kt  DateSeparator.kt  Labels.kt
               WeekView.kt  WeekChart.kt  MonthView.kt
      picker/  PhotoPickerScreen.kt  PickerViewModel.kt
      settings/SettingsScreen.kt  SettingsViewModel.kt
      calo/    CaloScreen.kt  ChatViewModel.kt  ChatArtifacts.kt
  app/src/test/java/com/jerrylf/inkcal/   15 个测试类，100 个用例
```

几点约定：
- `domain/` 全是纯 Kotlin（无 Android 依赖），是单测重点，也是唯一能在这台机器上验证的部分。
- **详情弹窗、Snackbar、写操作都在 `RecordsTab` 那一层**，不在各子视图里——三个视图的卡片都要能进详情，写完还要让当前视图重拉。子视图只负责渲染。
- `RangeViewModel` 是周/月共用的区间数据源；`RecordsViewModel` 管日视图 + 详情锚点 + 写操作。
- 单例（store / cookie / repository / 两个 cache）走 `AppContainer`，别在各 ViewModel 里各建一份——CookieStore 有内存缓存，两份会互相看不见对方的 cookie。

## 12. 测试与验收

**已落地的做法（0.10 起，2026-10-03 补到 15 类 100 例）**：15 个 JVM 测试类、100 个用例，全部集中在 `domain/` 与 `data/` 的纯逻辑上，`./gradlew :app:testDebugUnitTest` 一条命令跑完。

覆盖：data-version 指纹解析（DataVersion）、三级降级（Tdee）、时间字符串切片（含 `+08:00`/无时区/空串/凌晨 00:30 仍归当天）、DatePicker 的 UTC 毫秒换算、图片地址规则（含「库里存的其实是 `size=preview`」）、形态 A 判据、日内与周的排序、周期算术（周一起点/闰月/跨年/月首空格）、周汇总（只算有记录的天）、月格二值语义、决策匹配（含 `target_asset_id`）、体征校验范围、按接口分超时、缓存往返与损坏兜底、单张/多张两种分析响应的归一化、聊天工具的步骤标题/徽标/摘要与**产物分流**、以及 Markdown 子集解析。

已证明有效：Markdown 的列表解析就是被测试抓出来的（`Regex.matches` 是全串匹配，导致列表项永远判不出、全被当成段落）。**新逻辑优先写测试**，别指望在 UI 层用眼睛验。

**为什么重点在这**：这台机器上没有模拟器也没有真机自动化，`domain/` 与 `data/` 是唯一能在这里验证的部分；UI 只能靠用户手动过。所以凡是能抽成纯函数的判断（日期归属、缺口公式、分页边界、形态 A/B）都抽出来了，**新逻辑优先补测试**，别指望在 UI 层用眼睛验。

其余要求仍然有效：
1. DTO fixtures 放在 `android/app/src/test/resources/`——**目前没有用**（真实响应是直接用 curl 对着 NUC 核对字段的，见 AGENTS.md）。不要提交账号、密钥、照片 URL 中的密钥。
2. 集成验证：可配置 Base URL，对着 NUC 真实服务；或用 `INKCAL_DB` 指向隔离库起本地 Flask（写法见 `scripts/test_lightbox_smoke.py` 开头，注意它预置 `INKCAL_USER` 为空以防 `.env` 注入鉴权）。
3. 每个里程碑交付可安装 APK，附「请用户手动验证」清单；**不要声称验证了自己无法验证的交互**——真机上的手势、系统照片选择器、返回键都只能由用户确认。
4. 提交前 `git diff --check`；不要 `git add .`；不要提交 `local.properties`、keystore、`.env`。

## 13. 已知后端注意事项

- 区间查询的记录带 date，单日查询不带（§5.1）。
- records 相关响应有 burns（区间/周）与 burn（单日）两种键，别混。
- 聊天工具统计同时含别名两套，已拍板保留。
- 可选后端改动（仅在用户同意后，且需更新 AGENTS.md）：给 API 加 token 认证代替 cookie；单日响应补 date 字段；聊天流式 SSE（当前刻意未做，见 AGENTS.md）。都不是首期必需。
- 不要动：web/static、src、AGENT_ENABLED 逻辑。

## 14. 功能对照清单（验收用）

「进度」列记录到 0.4 为止的实现情况；标了版本号的即已完成并在真机验证过。

| # | Vue 版功能 | App 对应 | 首期 | 进度 |
|---|---|---|---|---|
| 1 | 日视图无限滚动、日期吸顶汇总、缺口 chip | §8.1 | 是 | ✅ 0.2；日/周/月切换 0.7 补上 |
| 2 | 周视图双层柱状图、汇总、时间轴 | §8.2 | 是 | ✅ 0.7 |
| 3 | 月视图圆环日历 | §8.3 | 是 | ✅ 0.7（点日期跳回日视图） |
| 4 | 餐卡（标题、明细、PCF、置信度、来源、×N、🤖、emoji 占位） | §8.4 | 是 | ✅ 0.5（🤖 角标 0.5 补上） |
| 5 | 详情：大图、多图切换、照片明细、形态 A/B | §8.4 | 是 | ✅ 0.4 |
| 6 | AI 决策区块 | §8.4 | 是 | ✅ 0.4 |
| 7 | 重新分析（组级联合） | §8.4 | 是 | ✅ 0.4 |
| 8 | 删除整餐 / 单张移除（两步确认、晋升处理） | §8.4 | 是 | ✅ 0.4 |
| 9 | 选择照片：相册多选不超过 10 张、分页 | §8.5(a) | 是 | ✅ 0.8 |
| 10 | 本地上传、无 EXIF 日期修正（_date_source=fallback 流程） | §8.5(b) | 是 | ✅ 0.8 |
| 11 | data-version 轮询刷新 | §8.6 | 是 | ✅ 0.12 |
| 12 | 设置：体征、BMR、Calo 窗口 | §8.7 | 是 | ✅ 0.5 |
| 13 | 热量缺口（三级降级） | §7 | 是 | ✅ 0.2 |
| 14 | Calo：会话恢复、历史、惰性新建 | §10 | 是 | ✅ 0.10 |
| 15 | Calo：Markdown、步骤折叠、产物分流、统计卡 | §10 | 是 | ✅ 0.10（Markdown 为子集实现，见 §10 注记） |
| 16 | Calo：删除确认卡 | §10 | 是 | ✅ 0.10 |
| 17 | 登录/登出/401 重登 | §3 | 是 | ✅ 0.5（使用中会话失效也会回登录页，0.1 时只有启动时会） |
| 18 | 桌面三栏 | 大屏 NavigationRail | 否（后续） | 未做 |
| 19 | 分享入口、小组件 | §8.8 | 否（后续） | 未做 |
| 20 | burn 手动录入 | PUT /api/burn | 网页版无 UI，暂不做 | — |

清单之外额外做的（不在 Vue 版功能对照范围内，但已实现）：

| # | 功能 | 说明 | 进度 |
|---|---|---|---|
| 21 | 下拉刷新 + 冷启动磁盘缓存 | 先画缓存再后台重拉（stale-while-revalidate），重拉已加载的整个范围 | ✅ 0.3 |
| 22 | 内嵌 TopAppBar inset 清零 | 修复 Scaffold 与 TopAppBar 重复垫状态栏 inset 导致的标题下空白（§8 约定） | ✅ 0.11 |
| 23 | 聊天乐观消息唯一 id + 周/月写后原地重拉 | 修复两条崩溃/过期：固定乐观 id 导致第二轮对话 LazyColumn 撞 key 崩溃（删除确认卡状态也串）；RangeViewModel.invalidate 只清标记不重拉，写后周/月视图显示旧数据 | ✅ 0.12 |
| 24 | §8.6 轮询配套修正 | 轮询基线存 VM（存协程里会漏掉后台期间的写入）；决策缓存改为「按已加载日期重取」而不是清空；BMR 拉取失败可重试；相册超 10 张给提示、批量结果分类展示（有失败走错误态）；Markdown 链接可点；聊天详情删单张走 promoted 重拉；废弃图标换 AutoMirrored；删未用 DTO | ✅ 0.12 |
| 25 | 设置页分组：服务器 / 关于 | 「服务器」组显示可读的数据概况（`domain/DataVersion` 解析 `/api/data-version` 指纹：记录条数 + 最后写入，UTC 转 HKT），末尾「关于」组显示 App 版本（BuildConfig）。原先是两行并列的「App 版本 / 数据版本（原始指纹）」，用户反馈看不懂 | ✅ 0.12 |

## 15. 建议实施顺序

1. ✅ 0.1 搭环境与空壳（三 Tab、主题、Base URL、登录、OkHttp + cookie）。里程碑 A：能登录并拉到 /api/data-version。
2. ✅ 0.2 `domain/` 纯函数 + 单元测试 + DTO。
3. ✅ 0.2 日视图 + 餐卡 + 图片加载。里程碑 B：能看今天的记录。
4. ✅ 0.4 详情（删除、重新分析、决策）。
5. ✅ 0.5 设置页（体征 / BMR / Calo 窗口）+ 缺口展示（缺口在 0.2 就落到日视图了）。
6. ✅ 0.7 周、月视图（含日/周/月切换与月视图点日期跳转）。
7. ✅ 0.8 选择照片（相册多选 ≤10、按天分页、非食物置灰）+ 本地上传（系统照片选择器，无 EXIF 时提示改期）。
8. ✅ 0.10 Calo（会话管理、步骤折叠、产物分流、统计卡、删除确认卡、聊天里的餐卡可进详情）。
9. ✅ 0.12 轮询刷新（§8.6）；剩收尾。（§8.8 的分享入口与小组件不在首期，别在这里排进去）

> 实际执行顺序与上面略有出入：0.3 先补了「下拉刷新 + 磁盘缓存」（用户反馈冷启动每次都重新加载才加的），排在第 3 步之后、第 4 步之前；
> 0.5 又回头补了 0.4 遗留的三处半成品（卡片 🤖 角标、设置页体征、使用中 401 回登录页）；
> 0.9 是补漏：§3.3 的**按接口分超时**之前一直没做（全用 20 s），重分析和批量加照片会在客户端超时、而服务端其实已经成功。
>
> **剩下的两步（8 轮询、9 收尾）可以在 Calo 之后再回头做**，它们是增强不是阻塞。
