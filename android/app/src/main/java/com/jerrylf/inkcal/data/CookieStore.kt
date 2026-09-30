package com.jerrylf.inkcal.data

import kotlinx.coroutines.runBlocking
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl

/**
 * 把 Flask 的会话 cookie 持久化到 DataStore，App 重启后仍然登录。
 *
 * 只跟一个服务器打交道，所以不做 domain 匹配：存全部、发全部。换服务器时调用
 * [clear]（保存新地址时由 AppRepository 触发），避免把旧 cookie 发给新主机。
 *
 * DataStore 是挂起 API，而 CookieJar 是同步接口，这里在 OkHttp 的工作线程上用
 * runBlocking 读一次、写一次，不在主线程上跑。
 */
class CookieStore(private val store: SettingsStore) : CookieJar {

  private val cache = LinkedHashMap<String, Cookie>()

  @Volatile
  private var loaded = false

  override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
    if (cookies.isEmpty()) return
    ensureLoaded(url)
    synchronized(cache) { cookies.forEach { cache[it.name] = it } }
    persist()
  }

  override fun loadForRequest(url: HttpUrl): List<Cookie> {
    ensureLoaded(url)
    val now = System.currentTimeMillis()
    return synchronized(cache) { cache.values.filter { it.expiresAt > now } }
  }

  fun clear() {
    synchronized(cache) { cache.clear() }
    loaded = true
    persist()
  }

  private fun ensureLoaded(url: HttpUrl) {
    if (loaded) return
    runBlocking {
      store.readCookies()
        .lineSequence()
        .map(String::trim)
        .filter(String::isNotEmpty)
        .forEach { line -> Cookie.parse(url, line)?.let { cache[it.name] = it } }
    }
    loaded = true
  }

  private fun persist() {
    val raw = synchronized(cache) { cache.values.joinToString("\n") { it.toString() } }
    runBlocking { store.writeCookies(raw) }
  }
}
