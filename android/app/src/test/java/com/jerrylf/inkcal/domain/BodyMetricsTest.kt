package com.jerrylf.inkcal.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 校验范围必须和服务端 `web/server.py::api_settings` 一致，否则会出现
 * 「客户端说没问题、服务端 400」的死角。
 */
class BodyMetricsTest {

  @Test
  fun `留空表示这次不改，不算错误`() {
    assertNull(BodyMetrics.heightError(""))
    assertNull(BodyMetrics.weightError("  "))
    assertNull(BodyMetrics.birthdateError(""))
  }

  @Test
  fun `身高边界 50 与 260 合法，越界报错`() {
    assertNull(BodyMetrics.heightError("50"))
    assertNull(BodyMetrics.heightError("260"))
    assertNull(BodyMetrics.heightError("182"))
    assertNotNull(BodyMetrics.heightError("49.9"))
    assertNotNull(BodyMetrics.heightError("261"))
  }

  @Test
  fun `体重边界 20 与 300 合法，越界报错`() {
    assertNull(BodyMetrics.weightError("20"))
    assertNull(BodyMetrics.weightError("300"))
    assertNotNull(BodyMetrics.weightError("19"))
    assertNotNull(BodyMetrics.weightError("301"))
  }

  @Test
  fun `非数字给出可读提示而不是崩`() {
    assertEquals("身高要填数字", BodyMetrics.heightError("一米八"))
    assertEquals("体重要填数字", BodyMetrics.weightError("七十"))
  }

  @Test
  fun `生日要求 YYYY-MM-DD 且不能是未来`() {
    assertNull(BodyMetrics.birthdateError("1999-06-21"))
    assertNotNull(BodyMetrics.birthdateError("1999/06/21"))
    assertNotNull(BodyMetrics.birthdateError("1999-13-01"))
    assertNotNull(BodyMetrics.birthdateError("2099-01-01"))
  }

  @Test
  fun `firstError 返回第一条命中的错误`() {
    assertNull(BodyMetrics.firstError("182", "77", "1999-06-21"))
    assertEquals("身高需在 50–260 cm", BodyMetrics.firstError("999", "77", "1999-06-21"))
  }
}
