package com.jerrylf.inkcal.data

import com.jerrylf.inkcal.domain.ServerUrl
import okhttp3.OkHttpClient
import retrofit2.HttpException
import java.util.concurrent.TimeUnit

/** 与服务器的连接状态。整个 App 的顶层状态机。 */
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
 * 连接与认证。业务数据访问后续按 docs/android-app-spec.md 加在这里。
 *
 * 启动时不做探测，直接请求 /api/data-version：200 就是免登录或已登录，401 才要登录页。
 */
class AppRepository(
  private val store: SettingsStore,
  private val cookieStore: CookieStore,
) {

  private val client = OkHttpClient.Builder()
    .cookieJar(cookieStore)
    .connectTimeout(15, TimeUnit.SECONDS)
    .readTimeout(20, TimeUnit.SECONDS)
    .build()

  suspend fun savedBaseUrl(): String = store.currentBaseUrl()

  /** 规范化并保存；地址为空返回 null。换地址时清掉旧 cookie，避免发给新主机。 */
  suspend fun saveBaseUrl(input: String): String? {
    val normalized = ServerUrl.normalize(input) ?: return null
    if (normalized != store.currentBaseUrl()) cookieStore.clear()
    store.setBaseUrl(normalized)
    return normalized
  }

  suspend fun probeSaved(): ConnState = probe(store.currentBaseUrl())

  suspend fun probe(baseUrl: String): ConnState {
    if (baseUrl.isBlank()) return ConnState.NeedServer
    return try {
      ConnState.Ready(api(baseUrl).dataVersion().version)
    } catch (e: HttpException) {
      if (e.code() == 401) ConnState.NeedLogin else ConnState.Failed("HTTP ${e.code()}")
    } catch (e: Exception) {
      ConnState.Failed(e.message ?: e.javaClass.simpleName)
    }
  }

  suspend fun login(baseUrl: String, user: String, password: String): ConnState = try {
    api(baseUrl).login(LoginRequest(user, password))
    probe(baseUrl)
  } catch (e: HttpException) {
    when (e.code()) {
      401 -> ConnState.Failed("账号或密码不正确")
      429 -> ConnState.Failed("尝试次数过多，等几分钟再试")
      else -> ConnState.Failed("HTTP ${e.code()}")
    }
  } catch (e: Exception) {
    ConnState.Failed(e.message ?: e.javaClass.simpleName)
  }

  suspend fun logout(baseUrl: String): ConnState {
    runCatching { api(baseUrl).logout() }
    cookieStore.clear()
    return probe(baseUrl)
  }

  private fun api(baseUrl: String): InkcalApi = ApiFactory.create(baseUrl, client)
}
