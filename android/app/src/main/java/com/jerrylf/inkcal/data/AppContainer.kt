package com.jerrylf.inkcal.data

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

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

  /** Application 级协程域：供慢写请求（重新分析 / 删除）使用，离开详情 Activity 不被取消（spec §3.3）。 */
  val appScope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

  /** Calo 与独立详情页写成功后广播，记录页据此重拉。 */
  val dataSignal: DataChangeSignal = DataChangeSignal()

  /** 跨 Activity 全局提示（如详情页删完整餐后立即 finish，由首页 Snackbar 展示结果）。 */
  private val _globalMessages = MutableSharedFlow<String>(extraBufferCapacity = 4)
  val globalMessages: SharedFlow<String> = _globalMessages.asSharedFlow()

  fun postGlobalMessage(message: String) {
    _globalMessages.tryEmit(message)
  }

  companion object {
    @Volatile private var instance: AppContainer? = null

    fun of(context: Context): AppContainer =
      instance
        ?: synchronized(this) {
          instance ?: AppContainer(context.applicationContext).also { instance = it }
        }
  }
}
