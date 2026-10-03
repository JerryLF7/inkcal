package com.jerrylf.inkcal.data

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * BMR 全局缓存：App 启动拉一次，所有视图共用；设置页保存体征后用响应里的值刷新它。
 *
 * null 表示体征没填齐，此时 TDEE 走 2500 兜底（见 domain/Tdee）。
 */
class BmrCache(private val repo: AppRepository) {

  private val _value = MutableStateFlow<Double?>(null)
  val value: StateFlow<Double?> = _value.asStateFlow()

  @Volatile private var loaded = false

  suspend fun ensureLoaded() {
    if (loaded) return
    refresh()
  }

  /**
   * 失败时**不置 loaded**：否则冷启动时网络抖一下，BMR 就整场为 null、TDEE 全程
   * 退到 2500 兜底且不再重试。留在未加载态，下一次 [ensureLoaded] 会再试。
   */
  suspend fun refresh() {
    runCatching { repo.settings().bmr }
      .onSuccess {
        _value.value = it
        loaded = true
      }
  }

  /** 设置页保存成功后直接写入，省一次往返。 */
  fun set(bmr: Double?) {
    _value.value = bmr
    loaded = true
  }
}
