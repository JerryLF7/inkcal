package com.jerrylf.inkcal.data

import android.content.Context

/**
 * 极简依赖容器：保证 SettingsStore / CookieStore / AppRepository 全局只有一份。
 *
 * 不能各 ViewModel 各建一份——CookieStore 自带内存缓存，两份会互相看不见对方的
 * cookie，出现"刚登录完又变未登录"。用 Application 级单例就够，不值得引 DI 框架。
 */
class AppContainer private constructor(context: Context) {

  val settingsStore: SettingsStore = SettingsStore(context)
  val cookieStore: CookieStore = CookieStore(settingsStore)
  val recordsCache: RecordsCache = RecordsCache(context.filesDir)
  val repository: AppRepository = AppRepository(settingsStore, cookieStore, recordsCache)
  val bmrCache: BmrCache = BmrCache(repository)

  /** Calo 写成功后广播，记录页据此重拉。 */
  val dataSignal: DataChangeSignal = DataChangeSignal()

  companion object {
    @Volatile private var instance: AppContainer? = null

    fun of(context: Context): AppContainer =
      instance
        ?: synchronized(this) {
          instance ?: AppContainer(context.applicationContext).also { instance = it }
        }
  }
}
