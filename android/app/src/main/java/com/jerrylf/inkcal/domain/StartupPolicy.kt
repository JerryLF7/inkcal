package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.BurnDto
import com.jerrylf.inkcal.data.RecordDto
import java.io.IOException

/** 落盘缓存裁剪结果：防止某次历史翻页把冷启动缓存永久滚成几百天全量。 */
data class TrimmedCache(
  val records: List<RecordDto>,
  val burns: Map<String, BurnDto>,
  val earliest: String,
)

/**
 * 冷启动与网络恢复相关的纯策略逻辑，抽离到 domain 层以供 JVM 单测完整覆盖。
 */
object StartupPolicy {

  const val DEFAULT_CACHE_DAYS = 7L
  const val FALLBACK_MAX_RECORDS = 20

  /**
   * 判断一个 HTTP 响应是否属于「反代/隧道瞬时故障」而应静默重试。
   *
   * 只对幂等的 `GET` 请求启用：
   * - `502 / 503 / 504`：网关或上游瞬时不可用；
   * - `404` 且 `Content-Type` 为 `text/html`（路径含 `/api/`）：
   *   inkcal Flask 的 `/api/` 端点（含真实的 404 错误）一律返回 `application/json` 或 `image/`，
   *   绝不返回 HTML。收到 HTML 404 说明请求在 `frps` HTTP vhost 连接池撞上了半开死连接
   *   （`frps` 把上游转发错误统一映成自带的 HTML 404 页），请求从未到达 Flask，重试完全安全。
   */
  fun shouldRetryProxyResponse(
    method: String,
    path: String,
    code: Int,
    contentType: String?,
  ): Boolean {
    if (!method.equals("GET", ignoreCase = true)) return false
    if (code == 502 || code == 503 || code == 504) return true
    if (code == 404 && path.contains("/api/")) {
      val ct = contentType?.lowercase().orEmpty()
      if (ct.startsWith("text/html") || ct.startsWith("text/plain")) return true
    }
    return false
  }

  /** 启动探测遇网络层瞬时异常（如手机刚唤醒切网时的 EOF/连接重置）时允许自动重试。 */
  fun isTransientNetworkException(e: Throwable): Boolean = e is IOException

  /** 冷启动首屏拉取起点：固定拉最近 [chunkDays] 天（约 15 KB），不受上次翻过的历史边界拖累。 */
  fun coldStartRangeStart(today: String, chunkDays: Long = DEFAULT_CACHE_DAYS): String =
    TimeFmt.minusDays(today, (chunkDays - 1).coerceAtLeast(0))

  /**
   * 裁剪要落盘的缓存窗口：只保留最近 [chunkDays] 天的记录与消耗，避免历史上翻过 73 天甚至 365 天
   * 后永久把缓存文件与后续冷启动撑大；若最近窗口内恰好无记录（例如停记了一周），退回保留最新
   * [fallbackMaxRecords] 条，确保冷启动首屏仍立即可看。
   */
  fun trimForDiskCache(
    records: List<RecordDto>,
    burns: Map<String, BurnDto>,
    today: String,
    chunkDays: Long = DEFAULT_CACHE_DAYS,
    fallbackMaxRecords: Int = FALLBACK_MAX_RECORDS,
  ): TrimmedCache {
    if (records.isEmpty()) {
      return TrimmedCache(emptyList(), emptyMap(), coldStartRangeStart(today, chunkDays))
    }
    val windowStart = coldStartRangeStart(today, chunkDays)
    val recent = records.filter { TimeFmt.dateOf(it.photoTime) >= windowStart }
    val kept =
      if (recent.isNotEmpty()) {
        recent
      } else {
        records
          .sortedWith(compareByDescending<RecordDto> { it.photoTime }.thenByDescending { it.assetId })
          .take(fallbackMaxRecords)
      }
    val earliestKeptDate =
      kept.map { TimeFmt.dateOf(it.photoTime) }.filter { it.isNotBlank() }.minOrNull()
    val earliest =
      if (recent.isNotEmpty()) windowStart
      else earliestKeptDate ?: windowStart
    val keptBurns = burns.filterKeys { it >= earliest }
    return TrimmedCache(records = kept, burns = keptBurns, earliest = earliest)
  }

  /**
   * 列表顶部锚点：同时包含「最新日期 + 该日第一条记录 asset_id」。
   *
   * 只盯日期头时，若同一天内缓存已有午饭、新刷新又插进了晚饭，日期头不变会漏掉置顶滚动；
   * 拼上首条记录 id 后，跨天与同日新入库都能稳稳把最新餐卡亮在顶部。
   */
  fun topAnchorKey(groups: List<DayGroup>): String? {
    val first = groups.firstOrNull() ?: return null
    val topRecordId = first.records.firstOrNull()?.assetId.orEmpty()
    return "${first.date}:$topRecordId"
  }
}
