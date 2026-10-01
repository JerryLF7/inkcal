package com.jerrylf.inkcal.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * TimeFmt 是日期归属铁律（AGENTS.md §1）的落点：全部靠字符串切片，绝不解析成
 * Instant 再按系统时区取日期。这些断言就是那条铁律的可执行版本。
 */
class TimeFmtTest {

  @Test
  fun `凌晨照片仍归当天，不因时区倒退一天`() {
    // 00:30+08:00 若是按 UTC 解析会变成前一天 16:30
    val photoTime = "2026-09-30T00:30:00+08:00"
    assertEquals("2026-09-30", TimeFmt.dateOf(photoTime))
    assertEquals("00:30", TimeFmt.clock(photoTime))
  }

  @Test
  fun `没有时区后缀也能切`() {
    assertEquals("2026-08-27", TimeFmt.dateOf("2026-08-27T12:34:56"))
    assertEquals("12:34", TimeFmt.clock("2026-08-27T12:34:56"))
  }

  @Test
  fun `空串与残缺串不炸`() {
    assertEquals("", TimeFmt.dateOf(""))
    assertEquals("", TimeFmt.clock(""))
    assertEquals("", TimeFmt.clock("2026-08-27"))
  }

  @Test
  fun `详情时间是分钟精度加时区，与网页版 fmtPhotoTimeDetail 一致`() {
    assertEquals("2026-08-27 12:34 +08:00", TimeFmt.detailTime("2026-08-27T12:34:56+08:00"))
    assertEquals("2026-08-27 12:34", TimeFmt.detailTime("2026-08-27T12:34:00"))
  }

  @Test
  fun `星期与日期文案`() {
    assertEquals("周四", TimeFmt.weekday("2026-10-01"))
    assertEquals("10月1日", TimeFmt.shortDate("2026-10-01"))
    assertEquals("2026年10月01日", TimeFmt.longDate("2026-10-01"))
  }

  @Test
  fun `日期加减`() {
    assertEquals("2026-09-24", TimeFmt.minusDays("2026-10-01", 7))
    assertEquals("2026-09-30", TimeFmt.minusDays("2026-10-01", 1))
    assertEquals("2026-09-30", TimeFmt.minusDays("2026-10-25", 25))
  }
}
