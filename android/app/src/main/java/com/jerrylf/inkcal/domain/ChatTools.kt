package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.ApiFactory
import com.jerrylf.inkcal.data.PhotoDto
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.data.ToolCallDto
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlin.math.roundToInt

/** 过程层的一步。 */
data class ToolStep(
  val name: String,
  val title: String,
  val badge: String?,
  val argsJson: String,
  val summary: String,
  val ok: Boolean,
)

enum class ArtifactKind {
  ADDED,
  UPDATED,
  REANALYZED,
  DELETE_CONFIRM,
  STATS,
  RECORDS,
}

/** 产物层的一张卡。 */
data class ToolArtifact(
  val kind: ArtifactKind,
  val title: String,
  val record: RecordDto? = null,
  val records: List<RecordDto> = emptyList(),
  val confirmAssetId: String = "",
  val confirmMeal: String = "",
  val confirmTime: String = "",
  val confirmCalories: Double = 0.0,
  val stats: IntakeStats? = null,
)

/** 后端同时给两套别名（meals/count、protein/protein_g），读任一套并兜底 0。 */
data class IntakeStats(
  val start: String = "",
  val end: String = "",
  val calories: Double = 0.0,
  val meals: Int = 0,
  val protein: Double = 0.0,
  val carbs: Double = 0.0,
  val fat: Double = 0.0,
)

/**
 * 工具调用 → 过程层与产物层的翻译，规则全部来自 docs/android-app-spec.md §10。
 *
 * 放在 domain 里是因为这是纯数据变换，也是最容易写错、最值得测的部分：
 * 产物分流的判据（有写操作时查询结果不进产物层）写错，就会出现「一次补记弹出三张卡」。
 */
object ChatTools {

  private const val INTENT = "intent"

  private val WRITE_TOOLS =
    setOf("add_record", "edit_record", "reanalyze_record", "request_delete_record")

  private val RECORD_TOOLS = setOf("get_records_in_range", "search_meals")

  fun isWriteTool(name: String): Boolean = name in WRITE_TOOLS

  /** 本轮有没有写操作；决定查询结果要不要单独出卡。 */
  fun hasWriteTool(toolLog: List<ToolCallDto>): Boolean = toolLog.any { isWriteTool(it.name) }

  /** 本轮是否存在**成功**的写操作——写成功后要让时间轴联动刷新。 */
  fun hasSuccessfulWrite(toolLog: List<ToolCallDto>): Boolean =
    toolLog.any { isWriteTool(it.name) && it.result.bool("ok") }

  // ── 过程层 ─────────────────────────────────────────────────────

  fun step(tool: ToolCallDto): ToolStep {
    val args = tool.args
    val result = tool.result
    val ok = result?.let { it.bool("ok") } ?: true
    return ToolStep(
      name = tool.name,
      title = title(tool),
      badge = badge(tool),
      // 展示时剔除 intent，避免和标题重复
      argsJson = JsonObject(args.filterKeys { it != INTENT }).toString(),
      summary = summarize(tool),
      ok = ok,
    )
  }

  /** 优先用模型写的意图，缺失才退回「工具名 + 关键参数」。 */
  private fun title(tool: ToolCallDto): String {
    val intent = tool.args.str(INTENT)
    if (intent.isNotBlank()) return intent

    val args = tool.args
    return when (tool.name) {
      "get_records_in_range" -> {
        val start = args.str("start").takeIf { it.isNotBlank() }
        val end = args.str("end").takeIf { it.isNotBlank() }
        "查询餐食记录" + when {
          start != null && end != null && start != end -> " (${start.drop(5)}~${end.drop(5)})"
          start != null -> " (${start.drop(5)})"
          else -> ""
        }
      }
      "get_intake_stats" -> "统计摄入情况"
      "search_meals" -> "搜索餐食记录" + args.str("keyword").takeIf { it.isNotBlank() }?.let { "「$it」" }.orEmpty()
      "get_decisions" -> "查看 AI 识别决策" + args.str("date").takeIf { it.isNotBlank() }?.let { " (${it.drop(5)})" }.orEmpty()
      "edit_record" -> "修改餐食记录"
      "add_record" -> "补记餐食记录"
      "reanalyze_record" -> "重新分析餐食记录"
      "request_delete_record" -> "请求删除餐食记录"
      else -> tool.name
    }
  }

  private fun badge(tool: ToolCallDto): String? {
    val result = tool.result ?: return null
    return when {
      tool.name in RECORD_TOOLS -> {
        val n = result.arr("records")?.size ?: result.int("count")
        if (n > 0) "$n 条" else null
      }
      tool.name == "get_intake_stats" -> {
        val total = result.obj("total") ?: return null
        "${total.dbl("calories").roundToInt()} kcal"
      }
      tool.name == "get_decisions" -> {
        val n = result.int("count").takeIf { it > 0 } ?: result.arr("decisions")?.size ?: 0
        if (n > 0) "$n 条" else null
      }
      else -> null
    }
  }

  private fun summarize(tool: ToolCallDto): String {
    val result = tool.result ?: return "无结果"
    if (!result.bool("ok")) return result.str("error").ifBlank { "失败" }

    val record = result.record("record")
    val after = result.record("after")
    return when (tool.name) {
      "get_records_in_range", "search_meals" ->
        "匹配 ${result.arr("records")?.size ?: result.int("count")} 条记录"
      "get_intake_stats" -> {
        val total = result.obj("total")
        total?.let { "${it.dbl("calories").roundToInt()} kcal" } ?: result.str("error").ifBlank { "无数据" }
      }
      "get_decisions" ->
        "审计决策 ${result.int("count").takeIf { it > 0 } ?: result.arr("decisions")?.size ?: 0} 条"
      "add_record" -> record?.let { "新增「${it.meal}」${it.calories.roundToInt()} kcal" } ?: "已新增"
      "edit_record", "reanalyze_record" ->
        after?.let { "「${it.meal}」${it.calories.roundToInt()} kcal" } ?: "已更新"
      "request_delete_record" -> "已生成待确认删除卡"
      else -> result.str("error").ifBlank { "完成" }
    }
  }

  // ── 产物层 ─────────────────────────────────────────────────────

  /**
   * 按 tool_log 顺序产出产物卡。
   *
   * 关键规则：**本轮只要有写操作，查询类结果就不出卡**——用户说「记一根玉米，分量和
   * 昨天差不多」时，Calo 会先查今天（查重）再查昨天（取份量参考），那些是内部步骤，
   * 平铺出来会让一次补记弹出三张卡。
   */
  fun artifacts(toolLog: List<ToolCallDto>): List<ToolArtifact> {
    val showQueries = !hasWriteTool(toolLog)
    return toolLog.mapNotNull { tool ->
      val result = tool.result ?: return@mapNotNull null
      val ok = result.bool("ok")
      when (tool.name) {
        "add_record" -> {
          val record = result.record("record")
          if (ok && record != null) {
            ToolArtifact(ArtifactKind.ADDED, "📝 已添加餐食记录：", record = normalizeRecord(record))
          } else null
        }
        "edit_record" -> {
          val after = result.record("after")
          if (ok && after != null) {
            ToolArtifact(ArtifactKind.UPDATED, "✏️ 已更新餐食记录：", record = normalizeRecord(after))
          } else null
        }
        "reanalyze_record" -> {
          val after = result.record("after")
          if (ok && after != null) {
            ToolArtifact(ArtifactKind.REANALYZED, "🔄 已重新分析餐食记录：", record = normalizeRecord(after))
          } else null
        }
        "request_delete_record" -> {
          val card = result.obj("confirm_card")
          if (card != null) {
            ToolArtifact(
              kind = ArtifactKind.DELETE_CONFIRM,
              title = "",
              confirmAssetId = card.str("asset_id"),
              confirmMeal = card.str("meal"),
              confirmTime = card.str("photo_time"),
              confirmCalories = card.dbl("calories"),
            )
          } else null
        }
        "get_intake_stats" -> {
          val total = result.obj("total")
          if (ok && total != null) {
            ToolArtifact(
              kind = ArtifactKind.STATS,
              title = "${total.str("start")} 至 ${total.str("end")} 摄入汇总",
              stats = IntakeStats(
                start = total.str("start"),
                end = total.str("end"),
                calories = total.dbl("calories"),
                meals = total.int("meals").takeIf { it > 0 } ?: total.int("count"),
                protein = total.dbl("protein").takeIf { it != 0.0 } ?: total.dbl("protein_g"),
                carbs = total.dbl("carbs").takeIf { it != 0.0 } ?: total.dbl("carbs_g"),
                fat = total.dbl("fat").takeIf { it != 0.0 } ?: total.dbl("fat_g"),
              ),
            )
          } else null
        }
        "get_records_in_range", "search_meals" -> {
          val list = result.records("records")
          if (showQueries && ok && list.isNotEmpty()) {
            val keyword = tool.args.str("keyword")
            ToolArtifact(
              kind = ArtifactKind.RECORDS,
              title =
                if (keyword.isNotBlank()) "搜索「$keyword」找到 ${list.size} 餐：" else "找到 ${list.size} 餐：",
              records = list.map(::normalizeRecord),
            )
          } else null
        }
        else -> null
      }
    }
  }

  /**
   * 工具返回的记录比 /api/records 的少几个字段：补 date、confidence 缺省 low、
   * photos 为空时用自身字段合成一张，否则详情页和图库会空着。
   */
  fun normalizeRecord(record: RecordDto): RecordDto {
    val photos =
      record.photos.ifEmpty {
        listOf(
          PhotoDto(
            assetId = record.assetId,
            thumbnailUrl = record.thumbnailUrl,
            photoTime = record.photoTime,
            meal = record.meal,
            mealDetail = record.mealDetail,
            calories = record.calories,
            proteinG = record.proteinG,
            carbsG = record.carbsG,
            fatG = record.fatG,
            emoji = record.emoji,
          )
        )
      }
    return record.copy(
      date = record.date.ifBlank { TimeFmt.dateOf(record.photoTime) },
      confidence = record.confidence.ifBlank { "low" },
      photos = photos,
    )
  }
}

// ── JsonObject 取值小工具（全是防御式：字段缺了就当没有，不抛异常）──

private fun JsonObject?.prim(key: String): JsonPrimitive? = this?.get(key) as? JsonPrimitive

private fun JsonObject?.str(key: String): String = prim(key)?.contentOrNull.orEmpty()

private fun JsonObject?.int(key: String): Int = prim(key)?.intOrNull ?: 0

private fun JsonObject?.dbl(key: String): Double = prim(key)?.doubleOrNull ?: 0.0

private fun JsonObject?.bool(key: String): Boolean = prim(key)?.contentOrNull == "true"

private fun JsonObject?.obj(key: String): JsonObject? = this?.get(key) as? JsonObject

private fun JsonObject?.arr(key: String): JsonArray? = this?.get(key) as? JsonArray

private fun JsonObject?.record(key: String): RecordDto? =
  obj(key)?.let { runCatching { ApiFactory.json.decodeFromJsonElement<RecordDto>(it) }.getOrNull() }

private fun JsonObject?.records(key: String): List<RecordDto> =
  arr(key)?.mapNotNull { element ->
    runCatching { ApiFactory.json.decodeFromJsonElement<RecordDto>(element) }.getOrNull()
  }.orEmpty()
