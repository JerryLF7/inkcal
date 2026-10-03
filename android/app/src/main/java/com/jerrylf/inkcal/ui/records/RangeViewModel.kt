package com.jerrylf.inkcal.ui.records

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jerrylf.inkcal.data.AppContainer
import com.jerrylf.inkcal.data.BurnDto
import com.jerrylf.inkcal.domain.DayGroup
import com.jerrylf.inkcal.domain.MealGrouping
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class RangeUiState(
  val loading: Boolean = false,
  val groups: List<DayGroup> = emptyList(),
  val burns: Map<String, BurnDto> = emptyMap(),
  val error: String? = null,
)

/**
 * 周视图与月视图共用的区间数据。
 *
 * **刻意用 `/api/records?start&end` 而不是 `/api/week`**（spec §8.2 原本写的是后者）：
 * 周接口返回的 by_day / summary 都能由区间数据在客户端算出来（`MealGrouping.groupByDate`
 * 已经是按日聚合），月视图又必须走任意区间，两条路合成一条能少一半代码、也少一个
 * 前后端不一致的机会。已回写文档。
 */
class RangeViewModel(app: Application) : AndroidViewModel(app) {

  private val container = AppContainer.of(app)
  private val repo = container.repository

  private val _state = MutableStateFlow(RangeUiState())
  val state: StateFlow<RangeUiState> = _state.asStateFlow()

  val bmr: StateFlow<Double?> = container.bmrCache.value

  /** 解析出的缓存里那份是给日视图用的，这里不碰它。 */
  private var seq = 0

  init {
    viewModelScope.launch { container.bmrCache.ensureLoaded() }
  }

  /** 拉取任意区间；重复调用同一区间会被忽略（切视图时避免重复请求）。 */
  fun load(start: String, end: String) {
    if (start.isBlank() || end.isBlank()) return
    val key = "$start..$end"
    if (loadedKey == key || start == loadingKey) return
    loadingKey = start
    lastRange = start to end

    val mine = ++seq
    viewModelScope.launch {
      _state.update { it.copy(loading = true, error = null) }
      try {
        val resp = repo.recordsInRange(start, end)
        if (mine != seq) return@launch
        loadedKey = key
        _state.update {
          it.copy(
            loading = false,
            groups = MealGrouping.groupByDate(resp.records),
            burns = resp.burns,
            error = null,
          )
        }
      } catch (e: Exception) {
        if (mine != seq) return@launch
        _state.update { it.copy(loading = false, error = e.message ?: e.javaClass.simpleName) }
      } finally {
        if (mine == seq) loadingKey = null
      }
    }
  }

  /**
   * 写操作之后调用：清掉去重标记，并**立刻重拉当前区间**（如果加载过）。
   *
   * 不能只清标记等视图自己重拉——`load()` 由 `LaunchedEffect(monday/monthAnchor)`
   * 触发，周/月视图不重组就不会重跑，写完之后卡片会一直显示旧数据（2026-10-03
   * 修复前：在周视图里删餐，要切走再切回来才消失）。
   */
  fun invalidate() {
    val range = lastRange
    loadedKey = null
    if (range != null) load(range.first, range.second)
  }

  private var loadedKey: String? = null
  private var loadingKey: String? = null
  /** 最近一次请求的区间，invalidate 时用它原地重拉。 */
  private var lastRange: Pair<String, String>? = null
}
