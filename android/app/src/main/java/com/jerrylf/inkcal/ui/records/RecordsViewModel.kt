package com.jerrylf.inkcal.ui.records

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jerrylf.inkcal.data.AppContainer
import com.jerrylf.inkcal.data.BurnDto
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.data.RecordsCache
import com.jerrylf.inkcal.data.RecordsCachePayload
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

/** 区间接口上限 366 天，留一天余量。 */
private const val MAX_RANGE_DAYS = 365L

data class RecordsUiState(
  /** 一点内容都没有时的整屏 loading（首次启动且无缓存）。 */
  val initialLoading: Boolean = false,
  /** 往下翻更早的记录，底部进度条。 */
  val loadingMore: Boolean = false,
  /** 下拉刷新 / 写操作后的重载，顶部下拉指示器。 */
  val refreshing: Boolean = false,
  val groups: List<DayGroup> = emptyList(),
  /** 日期 -> 当日消耗，供缺口计算；缺哪天就是那天没同步。 */
  val burns: Map<String, BurnDto> = emptyMap(),
  val error: String? = null,
  /** 已经翻到最早一条记录，不用再往下拉。 */
  val atEnd: Boolean = false,
)

/**
 * 日视图数据，对应 docs/android-app-spec.md §8.1。
 *
 * 冷启动策略是 stale-while-revalidate：先把上次的缓存画出来，再在后台重拉覆盖。
 * 不做"缓存没到期就不请求"——服务端 cron 随时会写新记录，缓存永远不算可信。
 */
class RecordsViewModel(app: Application) : AndroidViewModel(app) {

  private val container = AppContainer.of(app)
  private val repo = container.repository
  private val bmrCache = container.bmrCache
  private val cache: RecordsCache = container.recordsCache

  private val _state = MutableStateFlow(RecordsUiState())
  val state: StateFlow<RecordsUiState> = _state.asStateFlow()

  val bmr: StateFlow<Double?> = bmrCache.value

  val baseUrl: StateFlow<String> =
    container.settingsStore.baseUrl
      .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "")

  /** 跨分片累积的原始记录，是 groups 的唯一来源，也是写缓存的内容。 */
  private var loadedRecords: List<RecordDto> = emptyList()
  private var burns: Map<String, BurnDto> = emptyMap()
  private var earliestLoaded: String? = null

  /** 最早有记录的日期，来自 /api/dates；null 表示还没有或没取到。 */
  private var minDate: String? = null

  /** 请求序号：只采纳最新一次请求的响应，防止旧响应覆盖新数据。 */
  private var seq = 0

  init {
    viewModelScope.launch {
      paintFromCache()
      reloadAll(manual = false)
    }
    // BMR 不挡内容，单独拉
    viewModelScope.launch { bmrCache.ensureLoaded() }
  }

  /** 下拉刷新，以及将来写操作后的重载入口。 */
  fun refresh() {
    if (_state.value.refreshing) return
    viewModelScope.launch { reloadAll(manual = true) }
  }

  /** 触底加载更早的 7 天。 */
  fun loadMore() {
    val current = _state.value
    if (current.initialLoading || current.refreshing || current.loadingMore || current.atEnd) return
    val earliest = earliestLoaded ?: return

    viewModelScope.launch {
      val mine = ++seq
      _state.update { it.copy(loadingMore = true) }
      val end = TimeFmt.minusDays(earliest, 1)
      val start = TimeFmt.minusDays(end, CHUNK_DAYS - 1)
      try {
        val resp = repo.recordsInRange(start, end)
        if (mine != seq) return@launch
        loadedRecords = loadedRecords + resp.records
        burns = burns + resp.burns
        earliestLoaded = start
        publishResult()
      } catch (e: Exception) {
        if (mine != seq) return@launch
        _state.update { it.copy(loadingMore = false, error = friendly(e)) }
      }
    }
  }

  /**
   * 重拉**已加载的整个范围**整体替换（而不是只重拉最近 7 天），这样下拉刷新
   * 不会把用户翻过的历史抖掉。
   */
  private suspend fun reloadAll(manual: Boolean) {
    val mine = ++seq
    _state.update {
      it.copy(
        initialLoading = it.groups.isEmpty(),
        refreshing = manual && it.groups.isNotEmpty(),
        error = null,
      )
    }
    try {
      val today = TimeFmt.hktToday()
      val requested = earliestLoaded ?: TimeFmt.minusDays(today, CHUNK_DAYS - 1)
      val floor = TimeFmt.minusDays(today, MAX_RANGE_DAYS)
      val start = if (requested < floor) floor else requested

      val resp = repo.recordsInRange(start, today)
      minDate = runCatching { repo.availableDates().lastOrNull() }.getOrNull()
      if (mine != seq) return

      loadedRecords = resp.records
      burns = resp.burns
      earliestLoaded = start
      publishResult()
    } catch (e: Exception) {
      if (mine != seq) return
      _state.update {
        it.copy(initialLoading = false, refreshing = false, loadingMore = false, error = friendly(e))
      }
    }
  }

  /** 把当前累积状态发到 UI 并落盘。调用点都在一次请求成功之后。 */
  private suspend fun publishResult() {
    val start = earliestLoaded
    val atEnd = start == null || reachedEnd(start, loadedRecords.isEmpty())
    _state.update {
      it.copy(
        initialLoading = false,
        refreshing = false,
        loadingMore = false,
        groups = MealGrouping.groupByDate(loadedRecords),
        burns = burns,
        error = null,
        atEnd = atEnd,
      )
    }
    persistCache(atEnd)
  }

  private suspend fun paintFromCache() {
    val base = container.settingsStore.currentBaseUrl()
    val cached = cache.read(base) ?: return
    if (cached.records.isEmpty()) return
    loadedRecords = cached.records
    burns = cached.burns
    earliestLoaded = cached.earliest.ifBlank { null }
    _state.update {
      it.copy(
        groups = MealGrouping.groupByDate(cached.records),
        burns = cached.burns,
        atEnd = cached.atEnd,
      )
    }
  }

  private suspend fun persistCache(atEnd: Boolean) {
    val base = container.settingsStore.currentBaseUrl()
    if (base.isBlank() || loadedRecords.isEmpty()) return
    cache.write(
      RecordsCachePayload(
        baseUrl = base,
        records = loadedRecords,
        burns = burns,
        earliest = earliestLoaded ?: "",
        atEnd = atEnd,
      )
    )
  }

  private fun reachedEnd(chunkStart: String, chunkEmpty: Boolean): Boolean {
    val min = minDate
    if (min != null) return chunkStart <= min
    // 拿不到 /api/dates 时：这一片空就当作到底，避免无限拉
    return chunkEmpty
  }

  private fun friendly(e: Exception) = e.message ?: e.javaClass.simpleName
}
