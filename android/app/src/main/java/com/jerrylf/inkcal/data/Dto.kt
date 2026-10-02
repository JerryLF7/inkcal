package com.jerrylf.inkcal.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * API 契约。字段名靠 ApiFactory.json 的 SnakeCase 命名策略做映射，
 * 所以这里写惯用的 camelCase，不需要每个字段挂 @SerialName。
 *
 * 一律给默认值：服务端有若干"有值才输出"的可选字段（emoji、merged_into、
 * replacement_image），缺失时按缺省处理，不要让解析失败。
 */

@Serializable
data class PhotoDto(
  val assetId: String = "",
  val thumbnailUrl: String = "",
  val photoTime: String = "",
  val meal: String = "",
  val mealDetail: String = "",
  val calories: Double = 0.0,
  val proteinG: Double = 0.0,
  val carbsG: Double = 0.0,
  val fatG: Double = 0.0,
  val emoji: String = "",
)

/** 已分组的一餐（只含主记录），photos 是组内全部照片。 */
@Serializable
data class RecordDto(
  val id: Int = 0,
  val assetId: String = "",
  val sourceType: String = "",
  val photoTime: String = "",
  /** 区间查询才有，单日查询没有；客户端统一用 photoTime 前 10 位取日期。 */
  val date: String = "",
  val thumbnailUrl: String = "",
  /** 本地替换图路径，经 /api/local-image 取。 */
  val replacementImage: String = "",
  val meal: String = "",
  val mealDetail: String = "",
  val calories: Double = 0.0,
  val proteinG: Double = 0.0,
  val carbsG: Double = 0.0,
  val fatG: Double = 0.0,
  val confidence: String = "",
  /** 纯文本补录时的占位图标（无图才用）。 */
  val emoji: String = "",
  /** 主记录恒为 null。 */
  val mergedInto: String? = null,
  val photos: List<PhotoDto> = emptyList(),
) {
  /** 无图记录（典型是聊天补录）靠 emoji 顶替餐盘。 */
  val hasImage: Boolean get() = thumbnailUrl.isNotBlank() || replacementImage.isNotBlank()
}

/** 键名不带 _g，且是原始行求和（不是按主记录）。 */
@Serializable
data class SummaryDto(
  val calories: Double = 0.0,
  val protein: Double = 0.0,
  val carbs: Double = 0.0,
  val fat: Double = 0.0,
  val meals: Int = 0,
)

/** 当天没有数据时整个对象为 null。 */
@Serializable
data class BurnDto(
  val date: String = "",
  val activeKcal: Double = 0.0,
  val steps: Int = 0,
  val source: String = "",
)

/** GET /api/records?date= or /api/today */
@Serializable
data class DayResponse(
  val date: String = "",
  val records: List<RecordDto> = emptyList(),
  val summary: SummaryDto = SummaryDto(),
  val burn: BurnDto? = null,
)

/** GET /api/records?start=&end= —— 注意是 burns（字典）不是 burn。 */
@Serializable
data class RangeResponse(
  val start: String = "",
  val end: String = "",
  val records: List<RecordDto> = emptyList(),
  val summary: SummaryDto = SummaryDto(),
  val burns: Map<String, BurnDto> = emptyMap(),
)

@Serializable
data class DataVersionDto(
  val version: String = "",
  val pending: Int = 0,
)

@Serializable
data class LoginRequest(
  val user: String,
  /** 服务端字段名是 password，不是 pass。 */
  val password: String,
)

@Serializable
data class OkDto(val ok: Boolean = false)

/** GET /api/settings —— 体征未填是空串，bmr 为 null 表示没填齐。 */
@Serializable
data class SettingsDto(
  val chatWindow: Int = 20,
  val userHeight: String = "",
  val userWeight: String = "",
  val userBirthdate: String = "",
  val userGender: String = "male",
  val bmr: Double? = null,
)

/**
 * PUT /api/settings —— 只发要改的键。Json 配了 explicitNulls = false，
 * 值为 null 的字段不会出现在请求体里，正好满足「部分更新」的契约
 * （服务端只处理出现的键，缺的键不动）。
 */
@Serializable
data class SettingsUpdateRequest(
  val chatWindow: Int? = null,
  val userHeight: String? = null,
  val userWeight: String? = null,
  val userBirthdate: String? = null,
  val userGender: String? = null,
)

/** GET /api/decisions?date= —— Luna 批处理的审计记录。 */
@Serializable
data class DecisionDto(
  val id: Int = 0,
  val sessionDate: String = "",
  /** add / update / skip */
  val action: String = "",
  /** new_meal / same_meal / rejected，可能为空 */
  val relation: String = "",
  val assetIds: List<String> = emptyList(),
  val targetAssetId: String? = null,
  val groupWith: String? = null,
  val reasoning: String = "",
  val promptForGemini: String? = null,
  val createdAt: String = "",
)

@Serializable
data class DecisionsResponse(
  val date: String = "",
  val decisions: List<DecisionDto> = emptyList(),
)

@Serializable
data class ReanalyzeRequest(val assetId: String, val notes: String)

@Serializable
data class ReanalyzeResponse(val ok: Boolean = false, val record: RecordDto? = null)

/**
 * DELETE /api/record —— 接口用 JSON body 传参。
 * mode=meal 删整餐（组内全部照片进忽略列表）；mode=photo 只移除一张，
 * 删的是主行时最早的从行晋升，晋升的 asset_id 放在 promoted。
 */
@Serializable
data class DeleteRecordRequest(val assetId: String, val mode: String = "meal")

@Serializable
data class DeleteRecordResponse(
  val ok: Boolean = false,
  val deleted: List<String> = emptyList(),
  val promoted: String? = null,
)

/** 服务端出错时统一是 `{"error": "..."}`。 */
@Serializable
data class ErrorDto(val error: String = "")

// ── 相册选择（spec §8.5a）─────────────────────────────────────────

@Serializable
data class AlbumPhotoDto(
  val assetId: String = "",
  val thumbnailUrl: String = "",
  val photoTime: String = "",
  val source: String = "",
  /** true 的照片必须置灰不可选：SigLIP2 已判为非食物。 */
  val classifiedNonFood: Boolean = false,
)

@Serializable
data class AlbumDayDto(
  val date: String = "",
  val photos: List<AlbumPhotoDto> = emptyList(),
)

/** GET /api/album-photos —— 只含有照片的日期，没照片的日子整个不出现。 */
@Serializable
data class AlbumPhotosResponse(
  val dates: List<AlbumDayDto> = emptyList(),
  val nextCursor: String = "",
)

@Serializable
data class AnalyzeItem(
  val assetId: String,
  val source: String,
  val date: String = "",
  val thumbnailUrl: String = "",
  val photoTime: String = "",
)

@Serializable
data class AnalyzeRequest(val items: List<AnalyzeItem>)

@Serializable
data class AnalyzeResult(
  val assetId: String = "",
  /** ok / already_processed / not_food / analysis_failed / error */
  val status: String = "",
  val date: String = "",
  val detail: String? = null,
  val record: RecordDto? = null,
)

@Serializable
data class AnalyzeSummary(
  val total: Int = 0,
  val added: Int = 0,
  val alreadyProcessed: Int = 0,
  val notFood: Int = 0,
  val failed: Int = 0,
)

/**
 * POST /api/analyze-album-photo 的响应。
 *
 * **单张和多张返回的结构不一样**：单张沿用旧契约 `{ok, record, date}`（错误时是 HTTP 4xx），
 * 多张才返回 `{ok, results, summary}`。所以这里把两套字段都收着，由
 * [normalizedResults] 抹平。
 */
@Serializable
data class AnalyzeResponse(
  val ok: Boolean = false,
  val record: RecordDto? = null,
  val date: String = "",
  val results: List<AnalyzeResult> = emptyList(),
  val summary: AnalyzeSummary? = null,
) {
  val normalizedResults: List<AnalyzeResult>
    get() =
      if (results.isNotEmpty()) results
      else if (record != null) listOf(AnalyzeResult(status = "ok", date = date, record = record))
      else emptyList()
}

// ── 本地上传（spec §8.5b）────────────────────────────────────────

@Serializable
data class ManualUploadResponse(
  val ok: Boolean = false,
  val record: RecordDto? = null,
  val matched: Boolean = false,
  val date: String = "",
  /** exif / user / fallback：fallback 表示没读到拍摄时间，用了当天兜底，要提示用户改。 */
  @SerialName("_date_source") val dateSource: String = "",
)

@Serializable
data class MoveRecordRequest(val assetId: String, val date: String)

@Serializable
data class MoveRecordResponse(
  val ok: Boolean = false,
  val assetId: String = "",
)
