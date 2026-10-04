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

/** 一个区间（一周或一月）的数据。 */
data class RangeChunk(
  val loading: Boolean = false,
  val groups: List<DayGroup> = emptyList(),
  val burns: Map<String, BurnDto> = emptyMap(),
  val error: String? = null,
)

/** key 是 "start..end"，start/end 为本地日历日 YYYY-MM-DD。 */
data class RangeUiState(
  val chunks: Map<String, RangeChunk> = emptyMap(),
) {
  fun chunk(start: String, end: String): RangeChunk = chunks["$start..$end"] ?: RangeChunk()
}

/**
 * 周视图与月视图共用的区间数据。
 *
 * **刻意用 `/api/records?start&end` 而不是 `/api/week`**（spec §8.2 原本写的是后者）：
 * 周接口返回的 by_day / summary 都能由区间数据在客户端算出来（`MealGrouping.groupByDate`
 * 已经是按日聚合），月视图又必须走任意区间，两条路合成一条能少一半代码、也少一个
 * 前后端不一致的机会。已回写文档。
 *
 * **按区间缓存多份**（2026-10-04）：周/月视图改成 HorizontalPager 左右滑动之后，
 * 相邻两页会同时出现在屏幕上，单一区间状态会让两页都显示同一份数据。每个区间一个
 * 槽位，各拉各的，互不覆盖；区间 key 去重，划过的页各发一次请求，回到已加载的页
 * 不再请求。
 */
class RangeViewModel(app: Application) : AndroidViewModel(app) {

  private val container = AppContainer.of(app)
  private val repo = container.repository

  private val _state = MutableStateFlow(RangeUiState())
  val state: StateFlow<RangeUiState> = _state.asStateFlow()

  val bmr: StateFlow<Double?> = container.bmrCache.value

  /** 解析出的缓存里那份是给日视图用的，这里不碰它。 */

  /** 已请求过的区间 key -> (start, end)，用于去重与 invalidate 重拉。 */
  private val requested = mutableMapOf<String, Pair<String, String>>()

  init {
    viewModelScope.launch { container.bmrCache.ensureLoaded() }
  }

  /** 拉取任意区间；同一区间只请求一次（失败的区间允许重试）。 */
  fun load(start: String, end: String) {
    if (start.isBlank() || end.isBlank()) return
    val key = "$start..$end"
    if (requested.putIfAbsent(key, start to end) != null) return

    viewModelScope.launch {
      updateChunk(key) { it.copy(loading = true, error = null) }
      try {
        val resp = repo.recordsInRange(start, end)
        updateChunk(key) {
          it.copy(
            loading = false,
            groups = MealGrouping.groupByDate(resp.records),
            burns = resp.burns,
            error = null,
          )
        }
      } catch (e: Exception) {
        // 失败就移出去重表，下次滚回来可以重试
        requested.remove(key)
        updateChunk(key) { it.copy(loading = false, error = e.message ?: e.javaClass.simpleName) }
      }
    }
  }

  /**
   * 写操作之后调用：把所有已加载区间原地重拉。
   *
   * 不能只清标记等视图自己重拉——`load()` 由 `LaunchedEffect(monday/monthAnchor)`
   * 触发，区间集合没变时不会重跑，写完之后卡片会一直显示旧数据（2026-10-03
   * 修复前：在周视图里删餐，要切走再切回来才消失）。
   */
  fun invalidate() {
    val ranges = requested.values.toList()
    requested.clear()
    ranges.forEach { (start, end) -> load(start, end) }
  }

  private fun updateChunk(key: String, transform: (RangeChunk) -> RangeChunk) {
    _state.update {
      val chunk = it.chunks[key] ?: RangeChunk()
      it.copy(chunks = it.chunks + (key to transform(chunk)))
    }
  }
}
