package com.jerrylf.inkcal.ui.records

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jerrylf.inkcal.data.ApiFactory
import com.jerrylf.inkcal.data.AppContainer
import com.jerrylf.inkcal.data.BurnDto
import com.jerrylf.inkcal.data.DecisionDto
import com.jerrylf.inkcal.data.ErrorDto
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
import kotlinx.serialization.decodeFromString
import retrofit2.HttpException
import kotlin.math.roundToInt

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
 *
 * 详情页的写操作也挂在这里，因为它必须活过详情页的关闭（spec §3.3：不要在用户
 * 离开页面时取消已经在跑的请求），而且写完要重载列表让详情原地更新。
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

  /** 详情页打开的是哪一组（主行 asset_id）；null 表示没打开。 */
  private val _detailAnchor = MutableStateFlow<String?>(null)
  val detailAnchor: StateFlow<String?> = _detailAnchor.asStateFlow()

  private val _decisions = MutableStateFlow<List<DecisionDto>>(emptyList())
  val decisions: StateFlow<List<DecisionDto>> = _decisions.asStateFlow()

  /** 详情页写操作进行中，用于禁用按钮防重复提交。 */
  private val _busy = MutableStateFlow(false)
  val busy: StateFlow<Boolean> = _busy.asStateFlow()

  private val _toast = MutableStateFlow<String?>(null)
  val toast: StateFlow<String?> = _toast.asStateFlow()

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

  /** 下拉刷新，以及写操作后的重载入口。 */
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

  // ── 详情页 ─────────────────────────────────────────────────────

  fun openDetail(record: RecordDto) {
    _detailAnchor.value = record.assetId
    _decisions.value = emptyList()
    val date = TimeFmt.dateOf(record.photoTime)
    viewModelScope.launch {
      _decisions.value = runCatching { repo.decisions(date) }.getOrDefault(emptyList())
    }
  }

  fun closeDetail() {
    _detailAnchor.value = null
  }

  fun consumeToast() {
    _toast.value = null
  }

  /**
   * 重新分析。成功后**必须重拉分组**：组级联合重估会把形态 B 的从行清零，
   * 只听响应里的 record 会让详情页显示过期数据（spec §8.4）。
   */
  fun reanalyze(assetId: String, notes: String) {
    if (_busy.value) return
    viewModelScope.launch {
      _busy.value = true
      try {
        val resp = repo.reanalyze(assetId, notes)
        val kcal = resp.record?.calories?.roundToInt()
        _toast.value = if (kcal != null) "已更新：$kcal kcal" else "已更新"
        reloadAll(manual = false)
      } catch (e: Exception) {
        _toast.value = "重新分析失败: ${message(e)}"
      }
      _busy.value = false
    }
  }

  /** photoOnly=true 只移除一张照片，否则删整餐。 */
  fun delete(assetId: String, photoOnly: Boolean) {
    if (_busy.value) return
    viewModelScope.launch {
      _busy.value = true
      try {
        val resp = repo.deleteRecord(assetId, if (photoOnly) "photo" else "meal")
        if (photoOnly) {
          val promoted = resp.promoted
          // 删的是主行且最早的从行晋升：详情改锚到新主行，别让它指着一个不存在的 asset
          if (promoted != null) _detailAnchor.value = promoted
          _toast.value =
            if (promoted != null) "已移除主照片，这餐数值需要重新估算（可点「重新分析」）"
            else "已移除照片，记录已更新"
        } else {
          _detailAnchor.value = null
          _toast.value = "已删除整餐，照片不会再被同步"
        }
        reloadAll(manual = false)
      } catch (e: Exception) {
        _toast.value = "删除失败: ${message(e)}"
      }
      _busy.value = false
    }
  }

  // ── 内部 ───────────────────────────────────────────────────────

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

  /**
   * 优先用服务端给的 error 文案（比如「image unavailable」），拿不到才退回 HTTP 状态码。
   * errorBody 只能读一次，读完就没了。
   */
  private fun message(e: Exception): String =
    if (e is HttpException) {
      runCatching {
          val body = e.response()?.errorBody()?.string().orEmpty()
          ApiFactory.json.decodeFromString<ErrorDto>(body).error.ifBlank { "HTTP ${e.code()}" }
        }
        .getOrDefault("HTTP ${e.code()}")
    } else {
      friendly(e)
    }

  private fun friendly(e: Exception) = e.message ?: e.javaClass.simpleName
}
