package com.jerrylf.inkcal.data

import com.jerrylf.inkcal.domain.ServerUrl
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.Interceptor
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Response
import retrofit2.HttpException
import java.util.concurrent.TimeUnit

/** 与服务器的连接状态，App 的顶层状态机。 */
sealed interface ConnState {
  data object Loading : ConnState

  /** 还没填服务器地址。 */
  data object NeedServer : ConnState

  /** 服务端要求登录（401）。未设 INKCAL_USER/PASS 的部署不会走到这里。 */
  data object NeedLogin : ConnState

  data class Ready(val version: String) : ConnState

  data class Failed(val message: String) : ConnState
}

/** 普通请求的读超时。 */
private const val DEFAULT_READ_TIMEOUT_S = 20L

/**
 * 按接口分超时（docs/android-app-spec.md §3.3）。
 *
 * 用 `endsWith` 而不是相等：Base URL 可能带子路径（反代挂在 `/inkcal/` 下）。
 *
 * 单独抽成函数是为了能被测试钉住——映射写错会静默退回 20 秒，而症状是
 * 「服务端已经写完记录、客户端却报失败」这种很难归因的假故障。
 */
internal fun readTimeoutSecondsFor(path: String): Long =
  when {
    path.endsWith("/api/reanalyze") -> 120L
    path.endsWith("/api/chat/send") -> 300L
    // 一次最多带 10 张、整批过一次 Luna harness，给足余量
    path.endsWith("/api/analyze-album-photo") -> 600L
    path.endsWith("/api/manual-upload") -> 300L
    else -> DEFAULT_READ_TIMEOUT_S
  }

/**
 * 慢操作很多：重新分析要跑一轮 Gemini，相册批量分析整批过一次 Luna harness
 * （AGENTS.md 记录过一轮可跑 ~11 分钟）。如果全用一个 20 秒读超时，会出现
 * **服务端已经写完记录、客户端却先报失败**——用户看到"失败"，回去刷新发现记录在。
 */
private object TimeoutInterceptor : Interceptor {
  override fun intercept(chain: Interceptor.Chain): Response {
    val seconds = readTimeoutSecondsFor(chain.request().url.encodedPath)
    // OkHttp 的 withReadTimeout 收 Int、Builder.readTimeout 收 Long，这里统一按秒存 Long
    return chain.withReadTimeout(seconds.toInt(), TimeUnit.SECONDS).proceed(chain.request())
  }
}

/**
 * 连接、认证与业务数据访问。
 *
 * 启动时不做探测，直接请求 /api/data-version：200 就是免登录或已登录，401 才要登录页。
 */class AppRepository(
  private val store: SettingsStore,
  private val cookieStore: CookieStore,
  private val recordsCache: RecordsCache,
) {

  /** 给 Coil 复用：图片请求要带上同一个会话 cookie。 */
  val httpClient: OkHttpClient =
    OkHttpClient.Builder()
      .cookieJar(cookieStore)
      .addInterceptor(TimeoutInterceptor)
      .connectTimeout(15, TimeUnit.SECONDS)
      .readTimeout(DEFAULT_READ_TIMEOUT_S, TimeUnit.SECONDS)
      .build()

  @Volatile private var cachedApi: Pair<String, InkcalApi>? = null

  /** 会话在使用中失效（任何数据请求收到 401）时置 true，由 AppViewModel 弹回登录页。 */
  private val _unauthorized = MutableStateFlow(false)
  val unauthorized: StateFlow<Boolean> = _unauthorized.asStateFlow()

  fun acknowledgeUnauthorized() {
    _unauthorized.value = false
  }

  /**
   * 包一层请求：401 说明会话过期了（cron 跑着跑着、或服务端重启换了 INKCAL_SECRET），
   * 这时要把人送回登录页，而不是让"HTTP 401"当成普通错误挂在列表顶上。
   */
  private suspend fun <T> call(block: suspend (InkcalApi) -> T): T =
    try {
      block(api())
    } catch (e: HttpException) {
      if (e.code() == 401) _unauthorized.value = true
      throw e
    }

  private suspend fun api(): InkcalApi {
    val url = store.currentBaseUrl()
    cachedApi?.takeIf { it.first == url }?.let { return it.second }
    return ApiFactory.create(url, httpClient).also { cachedApi = url to it }
  }

  suspend fun savedBaseUrl(): String = store.currentBaseUrl()

  /** 规范化并保存；地址为空返回 null。换地址时清掉旧 cookie 与记录缓存，避免串服务器。 */
  suspend fun saveBaseUrl(input: String): String? {
    val normalized = ServerUrl.normalize(input) ?: return null
    if (normalized != store.currentBaseUrl()) {
      cookieStore.clear()
      recordsCache.clear()
    }
    store.setBaseUrl(normalized)
    return normalized
  }

  suspend fun probe(): ConnState {
    val baseUrl = store.currentBaseUrl()
    if (baseUrl.isBlank()) return ConnState.NeedServer
    return try {
      ConnState.Ready(api().dataVersion().version)
    } catch (e: HttpException) {
      if (e.code() == 401) ConnState.NeedLogin else ConnState.Failed("HTTP ${e.code()}")
    } catch (e: Exception) {
      ConnState.Failed(e.message ?: e.javaClass.simpleName)
    }
  }

  suspend fun login(user: String, password: String): ConnState = try {
    api().login(LoginRequest(user, password))
    probe()
  } catch (e: HttpException) {
    when (e.code()) {
      401 -> ConnState.Failed("账号或密码不正确")
      429 -> ConnState.Failed("尝试次数过多，等几分钟再试")
      else -> ConnState.Failed("HTTP ${e.code()}")
    }
  } catch (e: Exception) {
    ConnState.Failed(e.message ?: e.javaClass.simpleName)
  }

  suspend fun logout(): ConnState {
    runCatching { api().logout() }
    cookieStore.clear()
    recordsCache.clear()
    return probe()
  }

  // ── 业务数据 ────────────────────────────────────────────────────

  suspend fun recordsInRange(start: String, end: String): RangeResponse =
    call { it.recordsInRange(start, end) }

  suspend fun recordsOfDay(date: String): DayResponse = call { it.recordsOfDay(date) }

  /** 有记录的日期，新→旧。最后一项即最早日期，用来判断时间轴是否到底。 */
  suspend fun availableDates(): List<String> = call { it.dates() }

  suspend fun settings(): SettingsDto = call { it.settings() }

  suspend fun updateSettings(body: SettingsUpdateRequest): SettingsDto =
    call { it.updateSettings(body) }

  suspend fun decisions(date: String): List<DecisionDto> = call { it.decisions(date).decisions }

  suspend fun reanalyze(assetId: String, notes: String): ReanalyzeResponse =
    call { it.reanalyze(ReanalyzeRequest(assetId = assetId, notes = notes)) }

  /** mode 取 "meal"（整餐级联）或 "photo"（仅一张）。 */
  suspend fun deleteRecord(assetId: String, mode: String): DeleteRecordResponse =
    call { it.deleteRecord(DeleteRecordRequest(assetId = assetId, mode = mode)) }

  // ── 相册选择与本地上传（spec §8.5）─────────────────────────────

  suspend fun albumPhotos(cursor: String, days: Int): AlbumPhotosResponse =
    call { it.albumPhotos(cursor, days) }

  suspend fun analyzeAlbumPhotos(items: List<AnalyzeItem>): AnalyzeResponse =
    call { it.analyzeAlbumPhoto(AnalyzeRequest(items)) }

  suspend fun manualUpload(body: MultipartBody.Part): ManualUploadResponse =
    call { it.manualUpload(body) }

  suspend fun moveRecord(assetId: String, date: String): MoveRecordResponse =
    call { it.moveRecord(MoveRecordRequest(assetId = assetId, date = date)) }

  // ── Calo 聊天（spec §10）───────────────────────────────────────

  suspend fun chatSessions(): List<ChatSessionDto> = call { it.chatSessions().sessions }

  suspend fun chatMessages(sessionId: Int?): ChatMessagesResponse =
    call { it.chatMessages(sessionId) }

  /** sessionId 为 null 时服务端会新建会话（惰性新建）。 */
  suspend fun chatSend(sessionId: Int?, message: String): ChatSendResponse =
    call { it.chatSend(ChatSendRequest(sessionId = sessionId, message = message)) }
}
