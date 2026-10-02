package com.jerrylf.inkcal.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 周/月的日期算术。周一是一周起点，与前端的 hktNow/周视图一致。 */
class PeriodsTest {

  @Test
  fun `周一为一周起点，周日归到本周而非下周`() {
    // 2026-10-01 是周四
    assertEquals("2026-09-28", Periods.mondayOf("2026-10-01"))
    // 2026-10-04 是周日，仍属于 09-28 那一周
    assertEquals("2026-09-28", Periods.mondayOf("2026-10-04"))
    // 2026-10-05 是周一
    assertEquals("2026-10-05", Periods.mondayOf("2026-10-05"))
  }

  @Test
  fun `周区间与切周`() {
    val monday = Periods.mondayOf("2026-10-01")
    assertEquals("2026-10-04", Periods.weekEnd(monday))
    assertEquals("2026-09-21", Periods.addWeeks(monday, -1))
    assertEquals("2026-10-05", Periods.addWeeks(monday, 1))
  }

  @Test
  fun `周标签跨月也对`() {
    assertEquals("09.28 – 10.04", Periods.weekLabel("2026-09-28"))
    assertEquals("12.29 – 01.04", Periods.weekLabel("2025-12-29"))
  }

  @Test
  fun `月首月末与切月`() {
    assertEquals("2026-10-01", Periods.monthStart("2026-10-17"))
    assertEquals("2026-10-31", Periods.monthEnd("2026-10-17"))
    // 2 月与闰年
    assertEquals("2026-02-28", Periods.monthEnd("2026-02-15"))
    assertEquals("2028-02-29", Periods.monthEnd("2028-02-15"))
    assertEquals("2026-09-01", Periods.addMonths("2026-10-01", -1))
    assertEquals("2026-11-01", Periods.addMonths("2026-10-01", 1))
    // 跨年
    assertEquals("2027-01-01", Periods.addMonths("2026-12-01", 1))
    assertEquals("2025-12-01", Periods.addMonths("2026-01-01", -1))
  }

  @Test
  fun `月标签与天数`() {
    assertEquals("2026年10月", Periods.monthLabel("2026-10-15"))
    assertEquals("2026年1月", Periods.monthLabel("2026-01-05"))
    assertEquals(31, Periods.daysOfMonth("2026-10-15").size)
    assertEquals(30, Periods.daysOfMonth("2026-09-15").size)
    assertEquals(29, Periods.daysOfMonth("2028-02-15").size)
    assertEquals("2026-10-01", Periods.daysOfMonth("2026-10-15").first())
    assertEquals("2026-10-31", Periods.daysOfMonth("2026-10-15").last())
  }

  @Test
  fun `月首前面要空几格（周一起始）`() {
    // 2026-10-01 是周四 -> 前面空 3 格（一 二 三）
    assertEquals(3, Periods.leadingBlanks("2026-10-01"))
    // 2026-06-01 是周一 -> 不空
    assertEquals(0, Periods.leadingBlanks("2026-06-01"))
    // 2026-02-01 是周日 -> 空 6 格
    assertEquals(6, Periods.leadingBlanks("2026-02-01"))
  }

  @Test
  fun `今天所在周月判定与未来判定`() {
    assertTrue(Periods.isCurrentWeek("2026-09-28", "2026-10-01"))
    assertFalse(Periods.isCurrentWeek("2026-09-21", "2026-10-01"))
    assertTrue(Periods.isCurrentMonth("2026-10-01", "2026-10-01"))
    assertFalse(Periods.isCurrentMonth("2026-09-01", "2026-10-01"))

    assertTrue(Periods.isFuture("2026-10-05", "2026-10-01"))
    assertFalse(Periods.isFuture("2026-09-28", "2026-10-01"))
  }
}
