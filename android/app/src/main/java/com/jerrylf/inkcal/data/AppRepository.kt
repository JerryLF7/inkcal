package com.jerrylf.inkcal.data

import com.jerrylf.inkcal.domain.ServerUrl
import okhttp3.OkHttpClient
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

/**
 * 连接、认证与业务数据访问。
 *
 * 启动时不做探测，直接请求 /api/data-version：200 就是免登录或已登录，401 才要登录页。
 */
class AppRepository(
  private val store: SettingsStore,
  private val cookieStore: CookieStore,
  private val recordsCache: RecordsCache,
) {

  /** 给 Coil 复用：图片请求要带上同一个会话 cookie。 */
  val httpClient: OkHttpClient =
    OkHttpClient.Builder()
      .cookieJar(cookieStore)
      .connectTimeout(15, TimeUnit.SECONDS)
      .readTimeout(20, TimeUnit.SECONDS)
      .build()

  @Volatile private var cachedApi: Pair<String, InkcalApi>? = null

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
    api().recordsInRange(start, end)

  suspend fun recordsOfDay(date: String): DayResponse = api().recordsOfDay(date)

  /** 有记录的日期，新→旧。最后一项即最早日期，用来判断时间轴是否到底。 */
  suspend fun availableDates(): List<String> = api().dates()

  suspend fun settings(): SettingsDto = api().settings()

  suspend fun decisions(date: String): List<DecisionDto> = api().decisions(date).decisions

  suspend fun reanalyze(assetId: String, notes: String): ReanalyzeResponse =
    api().reanalyze(ReanalyzeRequest(assetId = assetId, notes = notes))

  /** mode 取 "meal"（整餐级联）或 "photo"（仅一张）。 */
  suspend fun deleteRecord(assetId: String, mode: String): DeleteRecordResponse =
    api().deleteRecord(DeleteRecordRequest(assetId = assetId, mode = mode))
}
