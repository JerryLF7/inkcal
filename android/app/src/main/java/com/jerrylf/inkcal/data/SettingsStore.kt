package com.jerrylf.inkcal.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "inkcal")

/**
 * 本地持久化：服务器地址、会话 cookie。刻意不用 Room——总共就几个键值。
 *
 * cookie 直接存 OkHttp Cookie 的 toString()，每行一条；读回时用请求 URL 解析
 * （见 CookieStore），所以不需要额外存 domain/path。
 */
class SettingsStore(private val context: Context) {

  private val baseUrlKey = stringPreferencesKey("base_url")
  private val cookiesKey = stringPreferencesKey("cookies")
  private val chatSessionKey = stringPreferencesKey("chat_session_id")

  val baseUrl: Flow<String> = context.dataStore.data.map { it[baseUrlKey] ?: "" }

  suspend fun currentBaseUrl(): String = baseUrl.first()

  suspend fun setBaseUrl(url: String) {
    context.dataStore.edit { it[baseUrlKey] = url }
  }

  suspend fun readCookies(): String = context.dataStore.data.map { it[cookiesKey] ?: "" }.first()

  suspend fun writeCookies(raw: String) {
    context.dataStore.edit { it[cookiesKey] = raw }
  }

  /** Calo 停留的会话；空串表示「新会话」（惰性新建，首条消息才落库）。 */
  suspend fun currentChatSessionId(): Int? =
    context.dataStore.data.map { it[chatSessionKey] ?: "" }.first().toIntOrNull()

  suspend fun setChatSessionId(id: Int?) {
    context.dataStore.edit { prefs ->
      if (id == null) prefs.remove(chatSessionKey) else prefs[chatSessionKey] = id.toString()
    }
  }
}
