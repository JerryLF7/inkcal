package com.jerrylf.inkcal.ui.records

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jerrylf.inkcal.data.ApiFactory
import com.jerrylf.inkcal.data.AppContainer
import com.jerrylf.inkcal.data.DecisionDto
import com.jerrylf.inkcal.data.ErrorDto
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.domain.Decisions
import com.jerrylf.inkcal.domain.DetailRefresh
import com.jerrylf.inkcal.domain.TimeFmt
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.serialization.decodeFromString
import retrofit2.HttpException
import kotlin.math.roundToInt

/**
 * 独立详情页（`MealDetailActivity`）的 ViewModel。
 *
 * 写操作（重新分析 / 删整餐 / 单张移除）一律跑在 `AppContainer.appScope` 上，遵循 spec §3.3：
 * 用户中途返回离开页面时服务端已经在执行，绝不能取消请求；完成后通过 `dataSignal.bump()` 通知首页刷新。
 */
class MealDetailViewModel(app: Application) : AndroidViewModel(app) {

  private val container = AppContainer.of(app)
  private val repo = container.repository

  val baseUrl: StateFlow<String> =
    container.settingsStore.baseUrl.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "")

  private val _record = MutableStateFlow<RecordDto?>(null)
  val record: StateFlow<RecordDto?> = _record.asStateFlow()

  private val _decisions = MutableStateFlow<List<DecisionDto>>(emptyList())
  val decisions: StateFlow<List<DecisionDto>> = _decisions.asStateFlow()

  private val _busy = MutableStateFlow(false)
  val busy: StateFlow<Boolean> = _busy.asStateFlow()

  private val _toast = MutableStateFlow<String?>(null)
  val toast: StateFlow<String?> = _toast.asStateFlow()

  private val _shouldFinish = MutableStateFlow(false)
  val shouldFinish: StateFlow<Boolean> = _shouldFinish.asStateFlow()

  private var initialized = false

  fun init(initialRecord: RecordDto, initialDecisions: List<DecisionDto>) {
    if (initialized) return
    initialized = true
    _record.value = initialRecord
    if (initialDecisions.isNotEmpty()) {
      _decisions.value = Decisions.forRecord(initialRecord, initialDecisions)
    } else {
      loadDecisionsFor(initialRecord)
    }
  }

  fun consumeToast() {
    _toast.value = null
  }

  private fun loadDecisionsFor(rec: RecordDto) {
    val date = TimeFmt.dateOf(rec.photoTime)
    if (date.isBlank()) return
    viewModelScope.launch {
      runCatching { repo.decisions(date) }
        .onSuccess { list ->
          val latest = _record.value ?: rec
          _decisions.value = Decisions.forRecord(latest, list)
        }
    }
  }

  /**
   * 组级重新分析：成功后重拉当天分组原地更新（形态 B 从行会被清零），并广播首页刷新。
   * 失败时保留表单与 notes 供修改重试。
   */
  fun reanalyze(notes: String, onSuccess: () -> Unit) {
    val current = _record.value ?: return
    if (_busy.value) return
    _busy.value = true
    val date = TimeFmt.dateOf(current.photoTime)
    val known = DetailRefresh.knownAssetIds(current)
    container.appScope.launch {
      try {
        val resp = repo.reanalyze(current.assetId, notes)
        container.dataSignal.bump()
        val refreshed =
          runCatching { repo.recordsOfDay(date).records }
            .getOrNull()
            ?.let { DetailRefresh.findGroup(it, current.assetId, known) }
            ?: resp.record
        if (refreshed != null) {
          _record.value = refreshed
        }
        val kcal = (refreshed ?: resp.record)?.calories?.roundToInt()
        _toast.value = if (kcal != null) "已更新：$kcal kcal" else "已更新"
        onSuccess()
      } catch (e: Exception) {
        _toast.value = "重新分析失败: ${errorMessage(e)}"
      } finally {
        _busy.value = false
      }
    }
  }

  /** 删除整餐：成功后通知首页刷新、投递全局提示并关闭详情 Activity。 */
  fun deleteMeal() {
    val current = _record.value ?: return
    if (_busy.value) return
    _busy.value = true
    container.appScope.launch {
      try {
        repo.deleteRecord(current.assetId, "meal")
        container.dataSignal.bump()
        container.postGlobalMessage("已删除整餐，照片不会再被同步")
        _shouldFinish.value = true
      } catch (e: Exception) {
        _toast.value = "删除失败: ${errorMessage(e)}"
      } finally {
        _busy.value = false
      }
    }
  }

  /**
   * 单张移除（spec §8.4）：删主行时最早从行晋升为新主行，原地重拉当天分组更新；
   * 若组已无剩余照片则关闭详情页并把提示投递回首页；重拉失败不关页，只提示用户。
   */
  fun deletePhoto(photoAssetId: String) {
    val current = _record.value ?: return
    if (_busy.value) return
    _busy.value = true
    val date = TimeFmt.dateOf(current.photoTime)
    val known = DetailRefresh.knownAssetIds(current)
    container.appScope.launch {
      try {
        val resp = repo.deleteRecord(photoAssetId, "photo")
        container.dataSignal.bump()
        val anchor = resp.promoted ?: current.assetId
        val dayRecords =
          try {
            repo.recordsOfDay(date).records
          } catch (_: Exception) {
            _toast.value = "操作已完成，但刷新失败——关闭后页面会自动更新"
            return@launch
          }
        val group = DetailRefresh.findGroup(dayRecords, anchor, known)
        if (group == null) {
          container.postGlobalMessage("已移除，该餐没有剩余照片")
          _shouldFinish.value = true
        } else {
          _record.value = group
          _toast.value =
            if (resp.promoted != null && DetailRefresh.isZeroValueRecord(group)) {
              "已移除主照片，这餐数值需要重新估算（可点下方「重新分析」）"
            } else {
              "已移除照片，记录已更新"
            }
        }
      } catch (e: Exception) {
        _toast.value = "删除失败: ${errorMessage(e)}"
      } finally {
        _busy.value = false
      }
    }
  }

  private fun errorMessage(e: Exception): String =
    if (e is HttpException) {
      runCatching {
          val body = e.response()?.errorBody()?.string().orEmpty()
          ApiFactory.json.decodeFromString<ErrorDto>(body).error.ifBlank { "HTTP ${e.code()}" }
        }
        .getOrDefault("HTTP ${e.code()}")
    } else {
      e.message ?: e.javaClass.simpleName
    }
}
