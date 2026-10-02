package com.jerrylf.inkcal.ui.picker

import com.jerrylf.inkcal.data.AnalyzeResponse
import com.jerrylf.inkcal.data.AnalyzeResult
import com.jerrylf.inkcal.data.AnalyzeSummary
import com.jerrylf.inkcal.data.RecordDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 服务端对「单张」和「多张」返回两个不同结构：
 *   单张 -> {ok, record, date}（出错时是 HTTP 4xx + {"error": status}）
 *   多张 -> {ok, results, summary}
 * 客户端必须把两套抹平，否则「只选了一张」这条路径会静默拿不到结果。
 */
class AnalyzeResponseTest {

  @Test
  fun `多张：直接用 results`() {
    val resp =
      AnalyzeResponse(
        ok = true,
        results =
          listOf(
            AnalyzeResult(assetId = "a", status = "ok", date = "2026-10-02"),
            AnalyzeResult(assetId = "b", status = "already_processed", date = "2026-10-02"),
          ),
        summary = AnalyzeSummary(total = 2, added = 1, alreadyProcessed = 1),
      )
    assertEquals(2, resp.normalizedResults.size)
    assertEquals("already_processed", resp.normalizedResults[1].status)
  }

  @Test
  fun `单张：从 record 合成一条 ok 结果`() {
    val resp =
      AnalyzeResponse(
        ok = true,
        record = RecordDto(assetId = "solo", meal = "水煮玉米", calories = 120.0),
        date = "2026-10-02",
      )
    val results = resp.normalizedResults
    assertEquals(1, results.size)
    assertEquals("ok", results.single().status)
    assertEquals("2026-10-02", results.single().date)
    assertEquals("solo", results.single().record?.assetId)
  }

  @Test
  fun `两者都空时返回空，不编造结果`() {
    assertTrue(AnalyzeResponse(ok = true).normalizedResults.isEmpty())
  }

  @Test
  fun `状态码翻译成人话`() {
    assertEquals("这张已在记录中", statusLabel("already_processed"))
    assertEquals("不是真实食物，已跳过", statusLabel("not_food"))
    assertEquals("下载原图失败", statusLabel("download_failed"))
    // 未知状态原样透出，方便排查，不要吞掉
    assertEquals("something_new", statusLabel("something_new"))
  }
}
