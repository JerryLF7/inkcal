package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.BurnDto
import com.jerrylf.inkcal.data.RecordDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WeekStatsTest {

  private val bmr = 1777.5

  private fun group(date: String, kcal: Double) =
    DayGroup(
      date = date,
      records = listOf(RecordDto(assetId = "a-$date", photoTime = "${date}T12:00:00+08:00", calories = kcal)),
      kcal = kcal,
      protein = 0.0,
      carbs = 0.0,
      fat = 0.0,
    )

  private fun burn(date: String, active: Double) = BurnDto(date = date, activeKcal = active)

  @Test
  fun `只统计有记录的天，漏记不进分母也不虚增缺口`() {
    // 有记录的两天各 1000 kcal，其余五天完全漏记
    val groups = listOf(group("2026-09-28", 1000.0), group("2026-09-29", 1000.0))
    val burns = mapOf("2026-09-28" to burn("2026-09-28", 1000.0))
    val stats = WeekStats.of(groups, burns, bmr)

    assertEquals(2, stats.recordedDays)
    assertEquals(2000.0, stats.totalIntake, 0.001)
    assertEquals(1000.0, stats.avgKcal, 0.001)
    // 09-28: (1777.5+1000) - 1000 = 1777.5；09-29 无 burn: 1777.5 - 1000 = 777.5
    assertEquals(2555.0, stats.totalDeficit, 0.001)
  }

  @Test
  fun `一天都没记录时不除零`() {
    val stats = WeekStats.of(emptyList(), emptyMap(), bmr)
    assertEquals(0, stats.recordedDays)
    assertEquals(0.0, stats.avgKcal, 0.001)
    assertEquals(0.0, stats.totalDeficit, 0.001)
  }

  @Test
  fun `没填体征时走 2500 兜底算缺口`() {
    val stats = WeekStats.of(listOf(group("2026-09-28", 2000.0)), emptyMap(), null)
    assertEquals(500.0, stats.totalDeficit, 0.001)
  }

  @Test
  fun `超标时累计缺口为负`() {
    val stats = WeekStats.of(listOf(group("2026-09-28", 3000.0)), emptyMap(), bmr)
    assertTrue("超标应为负", stats.totalDeficit < 0)
    assertEquals(1777.5 - 3000.0, stats.totalDeficit, 0.001)
  }
}

class MonthGridTest {

  private val bmr = 2000.0

  private fun group(date: String, kcal: Double) =
    DayGroup(
      date = date,
      records = listOf(RecordDto(assetId = "a-$date", photoTime = "${date}T12:00:00+08:00", calories = kcal)),
      kcal = kcal,
      protein = 0.0,
      carbs = 0.0,
      fat = 0.0,
    )

  @Test
  fun `整月每天都有格子，没记录的天也要在`() {
    val cells = MonthGrid.build("2026-10-01", listOf(group("2026-10-03", 900.0)), emptyMap(), bmr)
    assertEquals(31, cells.size)
    assertEquals(1, cells.first().dayOfMonth)
    assertEquals(31, cells.last().dayOfMonth)
    assertFalse("没记录的天不算有记录", cells.first().hasRecords)
    assertTrue(cells[2].hasRecords)
  }

  @Test
  fun `二值语义：有记录未超标是绿环，超标是红环，没记录不画环`() {
    val cells =
      MonthGrid.build(
        "2026-10-01",
        listOf(
          group("2026-10-01", 1500.0), // 低于 TDEE -> 有缺口
          group("2026-10-02", 2500.0), // 高于 TDEE -> 超标
          group("2026-10-03", 2000.0), // 正好等于 -> 不算超标（判据是"大于"）
        ),
        emptyMap(),
        bmr,
      )

    assertEquals(MonthRing.DEFICIT, cells[0].ring)
    assertEquals(MonthRing.OVER, cells[1].ring)
    assertEquals(MonthRing.DEFICIT, cells[2].ring)
    assertEquals(MonthRing.NONE, cells[3].ring)
  }

  @Test
  fun `当天有 burn 时 TDEE 跟着变大，可能从超标变回有缺口`() {
    val groups = listOf(group("2026-10-01", 2600.0))
    val withoutBurn = MonthGrid.build("2026-10-01", groups, emptyMap(), bmr)
    val withBurn =
      MonthGrid.build("2026-10-01", groups, mapOf("2026-10-01" to BurnDto(date = "2026-10-01", activeKcal = 1000.0)), bmr)

    assertEquals(MonthRing.OVER, withoutBurn[0].ring)
    assertEquals(MonthRing.DEFICIT, withBurn[0].ring)
  }

  @Test
  fun `圆环进度封顶在 1`() {
    val cells = MonthGrid.build("2026-10-01", listOf(group("2026-10-01", 9999.0)), emptyMap(), bmr)
    assertEquals(1f, cells[0].progress, 0.001f)
    assertEquals(0f, MonthGrid.build("2026-10-01", emptyList(), emptyMap(), bmr)[0].progress, 0.001f)
  }
}
