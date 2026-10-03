package com.jerrylf.inkcal.domain

import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * `/api/data-version` 的指纹转成人能读的「数据概况」。
 *
 * 服务端 `db.get_data_version()` 返回的是冒号分隔的 7 段：
 * `记录条数 : 最新创建 : 最新更新 : 最新重分析 : burn行数 : burn总消耗 : burn更新时间`
 * （`src/db.py`）。空库时时间字段为空串。
 *
 * **时间戳是 UTC**：SQLite 的 `datetime('now')` 给的是 UTC 且不带时区标记，
 * 所以这里显式按 UTC 解析再转 HKT——直接当本地时间显示会差 8 小时。
 */
data class DataSummary(
  val records: Int,
  /** 「10-03 19:20」，UTC 转换后的 HKT；没有任何写入时为 null。 */
  val lastWrite: String?,
)

object DataVersion {

  /**
   * 记录条数是第一段，且恒为数字。
   *
   * **不能按 `:` 切分**：时间戳本身就带两个冒号（`2026-10-03 11:20:00`），而且空值
   * 段会让段数不定，切出来既不是 7 段也不等长。所以条数取前缀、时间戳全部正则抓取。
   */
  private val RECORDS = Regex("""^(\d+):""")
  private val TIMESTAMP = Regex("""\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}""")

  /** 指纹至少 7 段 = 6 个分隔符；不够就是别的什么东西。 */
  private const val MIN_COLONS = 6

  private val UTC_PARSER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
  private val HKT = ZoneId.of("Asia/Hong_Kong")
  private val DISPLAY = DateTimeFormatter.ofPattern("MM-dd HH:mm")

  /** 解析失败（格式变了、不是指纹）就返回 null，UI 显示「—」。 */
  fun summarize(raw: String): DataSummary? {
    if (raw.count { it == ':' } < MIN_COLONS) return null
    val records = RECORDS.find(raw)?.groupValues?.get(1)?.toIntOrNull() ?: return null

    // 记录创建/更新/重分析、burn 更新时间里取最新的一条
    val latest = TIMESTAMP.findAll(raw).map { it.value }.maxOrNull()
    return DataSummary(records = records, lastWrite = latest?.let(::toHkt))
  }

  /** UTC 的 `YYYY-MM-DD HH:MM:SS` → HKT 的 `MM-dd HH:mm`；解析不了返回 null。 */
  internal fun toHkt(raw: String): String? =
    runCatching {
        LocalDateTime.parse(raw.trim(), UTC_PARSER)
          .atZone(ZoneOffset.UTC)
          .withZoneSameInstant(HKT)
          .format(DISPLAY)
      }
      .getOrNull()
}
