package com.jerrylf.inkcal.ui.picker

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jerrylf.inkcal.data.AnalyzeItem
import com.jerrylf.inkcal.data.AnalyzeResponse
import com.jerrylf.inkcal.data.AppContainer
import com.jerrylf.inkcal.data.AlbumDayDto
import com.jerrylf.inkcal.data.AlbumPhotoDto
import com.jerrylf.inkcal.data.ErrorDto
import com.jerrylf.inkcal.data.ApiFactory
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.decodeFromString
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import retrofit2.HttpException

/** 后端硬限制：items 超过 10 直接 400。 */
const val MAX_SELECTION = 10

private const val PAGE_DAYS = 7

/** 无 EXIF 时待用户确认日期的上传。 */
data class PendingDateFix(
  val assetId: String,
  val date: String,
  val label: String,
)

data class PickerUiState(
  val loading: Boolean = false,
  val days: List<AlbumDayDto> = emptyList(),
  /** 已选中的 asset_id；上限 [MAX_SELECTION]。 */
  val selected: Set<String> = emptySet(),
  val nextCursor: String = "",
  val atEnd: Boolean = false,
  val submitting: Boolean = false,
  val message: String? = null,
  val error: String? = null,
  val pendingDateFix: PendingDateFix? = null,
) {
  val selectedCount: Int get() = selected.size
  val overLimit: Boolean get() = selected.size >= MAX_SELECTION
}

/**
 * 相册选择 + 本地上传，对应 docs/android-app-spec.md §8.5。
 *
 * 两个来源都汇到同一个「加入记录」动作：相册走 `analyze-album-photo`，
 * 本地上传走 `manual-upload`（服务端读 EXIF 定日期）。用户主动选的照片**不再跑
 * SigLIP2**——选图本身就是「这是食物」的确认。
 */
class PickerViewModel(app: Application) : AndroidViewModel(app) {

  private val repo = AppContainer.of(app).repository

  private val _state = MutableStateFlow(PickerUiState())
  val state: StateFlow<PickerUiState> = _state.asStateFlow()

  /** 缩略图仍要经服务端代理取。 */
  val baseUrl: StateFlow<String> =
    AppContainer.of(app).settingsStore.baseUrl
      .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "")

  private var seq = 0

  init {
    loadMore()
  }

  fun loadMore() {
    val current = _state.value
    if (current.loading || current.atEnd) return
    val cursor = current.nextCursor
    val mine = ++seq

    viewModelScope.launch {
      _state.update { it.copy(loading = true, error = null) }
      try {
        val resp = repo.albumPhotos(cursor, PAGE_DAYS)
        if (mine != seq) return@launch
        _state.update {
          it.copy(
            loading = false,
            days = it.days + resp.dates,
            nextCursor = resp.nextCursor,
            // 服务端总是回一个更早的 cursor，所以「这一页一张都没有」才是到底
            atEnd = resp.dates.isEmpty(),
          )
        }
      } catch (e: Exception) {
        if (mine != seq) return@launch
        _state.update { it.copy(loading = false, error = friendly(e)) }
      }
    }
  }

  /** 非食物照片不可选；到上限后不再接受新增（取消选中不受限），并提示一次。 */
  fun toggle(photo: AlbumPhotoDto) {
    if (photo.classifiedNonFood) return
    _state.update { current ->
      val selected = current.selected
      when {
        photo.assetId in selected -> current.copy(selected = selected - photo.assetId)
        selected.size >= MAX_SELECTION ->
          current.copy(message = "一次最多选择 $MAX_SELECTION 张")
        else -> current.copy(selected = selected + photo.assetId)
      }
    }
  }

  fun consumeMessage() = _state.update { it.copy(message = null) }

  fun consumeError() = _state.update { it.copy(error = null) }

  /** 提交选中的相册照片。 */
  fun submit(onDone: () -> Unit) {
    val current = _state.value
    if (current.submitting || current.selected.isEmpty()) return

    val items =
      current.days
        .flatMap { day -> day.photos.map { day.date to it } }
        .filter { (_, photo) -> photo.assetId in current.selected }
        .map { (date, photo) ->
          AnalyzeItem(
            assetId = photo.assetId,
            source = photo.source,
            date = date,
            thumbnailUrl = photo.thumbnailUrl,
            photoTime = photo.photoTime,
          )
        }

    viewModelScope.launch {
      _state.update { it.copy(submitting = true, error = null) }
      try {
        val resp = repo.analyzeAlbumPhotos(items)
        val text = summarize(resp)
        // 有失败项就用错误态提示（spec §8.5a）
        _state.update {
          if ((resp.summary?.failed ?: 0) > 0) {
            it.copy(submitting = false, selected = emptySet(), error = text)
          } else {
            it.copy(submitting = false, selected = emptySet(), message = text)
          }
        }
        onDone()
      } catch (e: Exception) {
        _state.update { it.copy(submitting = false, error = statusMessage(e)) }
      }
    }
  }

  /** 本地图片：multipart 上传，服务端读 EXIF 决定日期。 */
  fun upload(uri: Uri, onDone: () -> Unit) {
    if (_state.value.submitting) return
    viewModelScope.launch {
      _state.update { it.copy(submitting = true, error = null) }
      try {
        val resolver = getApplication<Application>().contentResolver
        val mime = resolver.getType(uri) ?: "image/jpeg"
        val bytes =
          resolver.openInputStream(uri)?.use { it.readBytes() }
            ?: throw IllegalStateException("读不到这张图片")

        val part =
          MultipartBody.Part.createFormData(
            "image",
            "upload.${mime.substringAfterLast('/', "jpg")}",
            bytes.toRequestBody(mime.toMediaType()),
          )
        val resp = repo.manualUpload(part)

        if (resp.dateSource == "fallback") {
          // 没读到拍摄时间，用当天兜底了——让用户确认或改期
          val assetId = resp.record?.assetId.orEmpty()
          val label = resp.record?.meal?.ifBlank { "上传记录" } ?: "上传记录"
          _state.update {
            it.copy(
              submitting = false,
              pendingDateFix = PendingDateFix(assetId, resp.date, label),
              message = "没能读取拍摄日期，暂记在 ${resp.date}",
            )
          }
        } else {
          _state.update {
            it.copy(
              submitting = false,
              message = if (resp.matched) "已加入记录（已匹配到相册原图）" else "已加入记录",
            )
          }
          onDone()
        }
      } catch (e: Exception) {
        _state.update { it.copy(submitting = false, error = statusMessage(e)) }
      }
    }
  }

  /** 确认改期：把刚入库的记录挪到用户选的日期。 */
  fun fixDate(date: String, onDone: () -> Unit) {
    val pending = _state.value.pendingDateFix ?: return
    viewModelScope.launch {
      _state.update { it.copy(submitting = true) }
      try {
        if (pending.assetId.isNotBlank() && date != pending.date) {
          repo.moveRecord(pending.assetId, date)
        }
        _state.update { it.copy(submitting = false, pendingDateFix = null, message = "已加入记录") }
        onDone()
      } catch (e: Exception) {
        _state.update { it.copy(submitting = false, error = statusMessage(e)) }
      }
    }
  }

  /** 保持当天：不发请求。 */
  fun keepDate(onDone: () -> Unit) {
    _state.update { it.copy(pendingDateFix = null, message = "已加入记录") }
    onDone()
  }

  // ── 文案 ───────────────────────────────────────────────────────

  /** 逐类拼结果（spec §8.5a 的文案），0 的那些不出现。 */
  private fun summarize(resp: AnalyzeResponse): String {
    val summary = resp.summary
    if (summary != null) {
      val parts =
        buildList {
            if (summary.added > 0) add("已添加 ${summary.added} 条记录")
            if (summary.alreadyProcessed > 0) add("${summary.alreadyProcessed} 张已在记录中")
            if (summary.notFood > 0) add("${summary.notFood} 张非食物已跳过")
            if (summary.failed > 0) add("${summary.failed} 张分析失败")
          }
          .ifEmpty { listOf("已提交 ${summary.total} 张，没有新增记录") }
      return parts.joinToString("，")
    }
    val result = resp.normalizedResults.firstOrNull()
    return when (result?.status) {
      "ok" -> "已加入记录"
      null -> "已提交"
      else -> statusLabel(result.status)
    }
  }

  private fun statusMessage(e: Exception): String =
    if (e is HttpException) {
      runCatching {
          val body = e.response()?.errorBody()?.string().orEmpty()
          val raw = ApiFactory.json.decodeFromString<ErrorDto>(body).error
          if (raw.isBlank()) "HTTP ${e.code()}" else statusLabel(raw)
        }
        .getOrDefault("HTTP ${e.code()}")
    } else {
      friendly(e)
    }

  private fun friendly(e: Exception) = e.message ?: e.javaClass.simpleName
}

/** 把服务端的状态码翻译成人话。 */
internal fun statusLabel(status: String): String =
  when (status) {
    "already_processed" -> "这张已在记录中"
    "not_food" -> "不是真实食物，已跳过"
    "analysis_failed" -> "分析失败，稍后再试"
    "download_failed" -> "下载原图失败"
    "error" -> "处理出错"
    else -> status
  }
