package com.jerrylf.inkcal.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * data-version 指纹 → 数据概况。时间戳是 UTC，必须转 HKT 再显示（别差 8 小时）。
 */
class DataVersionTest {

  @Test
  fun `正常指纹取记录数与最新写入`() {
    // 7 段：n : created : updated : reanalyzed : burn数 : burn总 : burn更新
    val raw = "1245:2026-10-03 02:10:00:2026-10-03 04:10:00:2026-10-02 23:00:00:12:3400:2026-10-03 01:00:00"
    val summary = DataVersion.summarize(raw)
    assertEquals(1245, summary?.records)
    // 最新的是 records.updated_at 04:10 UTC → 12:10 HKT
    assertEquals("10-03 12:10", summary?.lastWrite)
  }

  @Test
  fun `burn 更新时间也能当最新写入`() {
    val raw = "10:2026-10-01 00:00:00:2026-10-01 00:00:00::5:900:2026-10-03 06:00:00"
    assertEquals("10-03 14:00", DataVersion.summarize(raw)?.lastWrite)
  }

  @Test
  fun `空库没有写入时间`() {
    val summary = DataVersion.summarize("0::::0:0:")
    assertEquals(0, summary?.records)
    assertNull(summary?.lastWrite)
  }

  @Test
  fun `时间格式变了只丢时间不影响条数`() {
    val summary = DataVersion.summarize("7:坏时间:坏时间:坏时间:0:0:坏时间")
    assertEquals(7, summary?.records)
    assertNull(summary?.lastWrite)
  }

  @Test
  fun `段数不对或首段非数字返回 null`() {
    assertNull(DataVersion.summarize(""))
    // 只有一段记录数 + 一个时间：不是完整指纹
    assertNull(DataVersion.summarize("1245:2026-10-03 02:10:00"))
    assertNull(DataVersion.summarize("abc:2026-10-03 02:10:00:2026-10-03 02:10:00::0:0:"))
  }
}
