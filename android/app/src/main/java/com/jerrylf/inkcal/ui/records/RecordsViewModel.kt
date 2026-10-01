package com.jerrylf.inkcal.ui.records

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jerrylf.inkcal.data.AppContainer
import com.jerrylf.inkcal.data.BurnDto
import com.jerrylf.inkcal.data.SettingsStore
import com.jerrylf.inkcal.domain.DayGroup
import com.jerrylf.inkcal.domain.MealGrouping
import com.jerrylf.inkcal.domain.TimeFmt
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** 一次拉 7 天。 */
private const val CHUNK_DAYS = 7L

data class RecordsUiState(
  val loading: Boolean = false,
  val groups: List<DayGroup> = emptyList(),
  /** 日期 -> 当日消耗，供缺口计算；缺哪天就是那天没同步。 */
  val burns: Map<String, BurnDto> = emptyMap(),
  val error: String? = null,
  /** 已经翻到最早一条记录，不用再往下拉。 */
  val atEnd: Boolean = false,
)

/**
 * 日视图数据。对应 docs/android-app-spec.md §8.1。
 *
 * 分片拉取：先拉最近 7 天，触底再往前拉 7 天，直到 /api/dates 给出的最早日期。
 */
class RecordsViewModel(app: Application) : AndroidViewModel(app) {

  private val container = AppContainer.of(app)
  private val repo = container.repository
  private val bmrCache = container.bmrCache

  private val _state = MutableStateFlow(RecordsUiState())
  val state: StateFlow<RecordsUiState> = _state.asStateFlow()

  val bmr: StateFlow<Double?> = bmrCache.value

  val baseUrl: StateFlow<String> =
    container.settingsStore.baseUrl
      .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "")

  /** 最早有记录的日期，来自 /api/dates；null 表示还没有或没取到。 */
  private var minDate: String? = null

  /** 请求序号：只采纳最新一次请求的响应，防止旧响应覆盖新数据。 */
  private var seq = 0

  init {
    refresh()
  }

  /** 收到 data-version 变化或写操作后重拉已加载范围。失败时保留旧数据不清空。 */
  fun refresh() {
    val mine = ++seq
    viewModelScope.launch {
      _state.update { it.copy(loading = true, error = null) }
      bmrCache.ensureLoaded()
      try {
        val today = TimeFmt.hktToday()
        val start = TimeFmt.minusDays(today, CHUNK_DAYS - 1)
        val resp = repo.recordsInRange(start, today)
        minDate = runCatching { repo.availableDates().lastOrNull() }.getOrNull()
        if (mine != seq) return@launch
        _state.update {
          it.copy(
            loading = false,
            groups = MealGrouping.groupByDate(resp.records),
            burns = resp.burns,
            error = null,
            atEnd = reachedEnd(start, resp.records.isEmpty()),
          )
        }
      } catch (e: Exception) {
        if (mine != seq) return@launch
        _state.update { it.copy(loading = false, error = friendly(e)) }
      }
    }
  }

  /** 触底加载更早的 7 天。 */
  fun loadMore() {
    val current = _state.value
    if (current.loading || current.atEnd) return
    val earliest = current.groups.lastOrNull()?.date ?: return
    val mine = ++seq
    viewModelScope.launch {
      _state.update { it.copy(loading = true) }
      val end = TimeFmt.minusDays(earliest, 1)
      val start = TimeFmt.minusDays(end, CHUNK_DAYS - 1)
      try {
        val resp = repo.recordsInRange(start, end)
        if (mine != seq) return@launch
        _state.update {
          it.copy(
            loading = false,
            groups = it.groups + MealGrouping.groupByDate(resp.records),
            burns = it.burns + resp.burns,
            atEnd = reachedEnd(start, resp.records.isEmpty()),
          )
        }
      } catch (e: Exception) {
        if (mine != seq) return@launch
        _state.update { it.copy(loading = false, error = friendly(e)) }
      }
    }
  }

  private fun reachedEnd(chunkStart: String, chunkEmpty: Boolean): Boolean {
    val min = minDate
    if (min != null) return chunkStart <= min
    // 拿不到 /api/dates 时：这一片空就当作到底，避免无限拉
    return chunkEmpty
  }

  private fun friendly(e: Exception) = e.message ?: e.javaClass.simpleName
}
