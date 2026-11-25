package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.BurnDto
import com.jerrylf.inkcal.data.RecordDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.EOFException

class StartupPolicyTest {

  private fun rec(id: String, date: String, time: String = "12:00:00") =
    RecordDto(
      assetId = id,
      photoTime = "${date}T$time+08:00",
      meal = "餐食 $id",
      calories = 500.0,
    )

  @Test
  fun `shouldRetryProxyResponse retries frps HTML 404 and gateway 5xx on GET only`() {
    assertTrue(
      StartupPolicy.shouldRetryProxyResponse(
        method = "GET",
        path = "/api/data-version",
        code = 404,
        contentType = "text/html; charset=utf-8",
      )
    )
    assertTrue(
      StartupPolicy.shouldRetryProxyResponse(
        method = "GET",
        path = "/inkcal/api/records",
        code = 404,
        contentType = "text/plain",
      )
    )
    assertTrue(
      StartupPolicy.shouldRetryProxyResponse(
        method = "GET",
        path = "/api/records",
        code = 502,
        contentType = "text/html",
      )
    )
    assertTrue(
      StartupPolicy.shouldRetryProxyResponse(
        method = "GET",
        path = "/api/data-version",
        code = 503,
        contentType = null,
      )
    )
    assertTrue(
      StartupPolicy.shouldRetryProxyResponse(
        method = "GET",
        path = "/api/data-version",
        code = 504,
        contentType = null,
      )
    )
  }

  @Test
  fun `shouldRetryProxyResponse never retries JSON 404, 401, 500, or non-GET methods`() {
    // Flask 真实业务 404 是 JSON
    assertFalse(
      StartupPolicy.shouldRetryProxyResponse(
        method = "GET",
        path = "/api/records",
        code = 404,
        contentType = "application/json",
      )
    )
    // 401 要进登录页，不能重试
    assertFalse(
      StartupPolicy.shouldRetryProxyResponse(
        method = "GET",
        path = "/api/data-version",
        code = 401,
        contentType = "application/json",
      )
    )
    // 非 GET 绝不在通用拦截器里重试，防重复写入
    assertFalse(
      StartupPolicy.shouldRetryProxyResponse(
        method = "POST",
        path = "/api/reanalyze",
        code = 404,
        contentType = "text/html",
      )
    )
    assertFalse(
      StartupPolicy.shouldRetryProxyResponse(
        method = "DELETE",
        path = "/api/record",
        code = 502,
        contentType = "text/html",
      )
    )
    assertFalse(
      StartupPolicy.shouldRetryProxyResponse(
        method = "GET",
        path = "/api/data-version",
        code = 500,
        contentType = "application/json",
      )
    )
  }

  @Test
  fun `isTransientNetworkException matches IOException only`() {
    assertTrue(StartupPolicy.isTransientNetworkException(EOFException("eof")))
    assertFalse(StartupPolicy.isTransientNetworkException(IllegalStateException("bug")))
  }

  @Test
  fun `trimForDiskCache keeps only recent 7 days so scrolled history does not bloat cold start`() {
    val today = "2026-11-25"
    val records =
      listOf(
        rec("today", "2026-11-25"),
        rec("edge", "2026-11-19"),
        rec("old1", "2026-11-18"),
        rec("ancient", "2026-09-12"),
      )
    val burns =
      mapOf(
        "2026-11-25" to BurnDto(date = "2026-11-25", activeKcal = 300.0),
        "2026-11-19" to BurnDto(date = "2026-11-19", activeKcal = 250.0),
        "2026-09-12" to BurnDto(date = "2026-09-12", activeKcal = 400.0),
      )

    val trimmed = StartupPolicy.trimForDiskCache(records, burns, today)
    assertEquals(listOf("today", "edge"), trimmed.records.map { it.assetId })
    assertEquals("2026-11-19", trimmed.earliest)
    assertEquals(setOf("2026-11-25", "2026-11-19"), trimmed.burns.keys)
  }

  @Test
  fun `trimForDiskCache falls back to latest records when last 7 days are empty`() {
    val today = "2026-11-25"
    val records =
      listOf(
        rec("older", "2026-11-01"),
        rec("latest", "2026-11-10"),
      )
    val burns = mapOf("2026-11-10" to BurnDto(date = "2026-11-10", activeKcal = 200.0))

    val trimmed = StartupPolicy.trimForDiskCache(records, burns, today, fallbackMaxRecords = 1)
    assertEquals(listOf("latest"), trimmed.records.map { it.assetId })
    assertEquals("2026-11-10", trimmed.earliest)
    assertEquals(setOf("2026-11-10"), trimmed.burns.keys)
  }

  @Test
  fun `topAnchorKey changes for both cross-day and same-day newly prepended meals`() {
    assertNull(StartupPolicy.topAnchorKey(emptyList()))

    val lunchOnly = MealGrouping.groupByDate(listOf(rec("lunch", "2026-11-25", "12:30:00")))
    val withDinner =
      MealGrouping.groupByDate(
        listOf(
          rec("lunch", "2026-11-25", "12:30:00"),
          rec("dinner", "2026-11-25", "18:30:00"),
        )
      )
    assertEquals("2026-11-25:lunch", StartupPolicy.topAnchorKey(lunchOnly))
    assertEquals("2026-11-25:dinner", StartupPolicy.topAnchorKey(withDinner))
  }
}
