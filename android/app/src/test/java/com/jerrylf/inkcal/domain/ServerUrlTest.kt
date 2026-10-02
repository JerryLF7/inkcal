package com.jerrylf.inkcal.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * ServerUrl 是 Retrofit baseUrl 的前置条件（必须以 `/` 结尾），错了整个 App 一个请求都发不出去，
 * 所以在没有真机的情况下用这个自检兜底。
 */
class ServerUrlTest {

  @Test
  fun `补齐 scheme 与结尾斜杠`() {
    assertEquals("http://192.0.2.10:5800/", ServerUrl.normalize("192.0.2.10:5800"))
    assertEquals("http://example.com/", ServerUrl.normalize("http://example.com"))
    assertEquals("https://inkcal.example.com/", ServerUrl.normalize("https://inkcal.example.com/"))
  }

  @Test
  fun `去掉首尾空白，保留路径前缀`() {
    assertEquals("https://example.com/inkcal/", ServerUrl.normalize("  https://example.com/inkcal/  "))
  }

  @Test
  fun `空输入返回 null`() {
    assertNull(ServerUrl.normalize(""))
    assertNull(ServerUrl.normalize("   "))
    assertNull(ServerUrl.normalize("///"))
  }
}
