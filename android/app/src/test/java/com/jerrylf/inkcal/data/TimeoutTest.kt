package com.jerrylf.inkcal.data

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 按接口分超时（spec §3.3）。映射写错会静默退回 20 秒，症状是「服务端已经写完记录、
 * 客户端却报失败」——用户看到失败、回去刷新发现记录在，很难归因。所以这里钉死。
 */
class TimeoutTest {

  @Test
  fun `慢接口拿到足够的超时`() {
    assertEquals(120L, readTimeoutSecondsFor("/api/reanalyze"))
    assertEquals(300L, readTimeoutSecondsFor("/api/chat/send"))
    assertEquals(600L, readTimeoutSecondsFor("/api/analyze-album-photo"))
    assertEquals(300L, readTimeoutSecondsFor("/api/manual-upload"))
  }

  @Test
  fun `普通接口用默认 20 秒`() {
    assertEquals(20L, readTimeoutSecondsFor("/api/records"))
    assertEquals(20L, readTimeoutSecondsFor("/api/decisions"))
    assertEquals(20L, readTimeoutSecondsFor("/api/image"))
    assertEquals(20L, readTimeoutSecondsFor("/api/data-version"))
  }

  @Test
  fun `Base URL 带子路径时（反代挂在子目录）也要匹配上`() {
    assertEquals(120L, readTimeoutSecondsFor("/inkcal/api/reanalyze"))
    assertEquals(600L, readTimeoutSecondsFor("/x/y/api/analyze-album-photo"))
  }

  @Test
  fun `不是被这些路径前缀骗到`() {
    // 只按后缀匹配，别把别的接口误判成慢接口
    assertEquals(20L, readTimeoutSecondsFor("/api/reanalyze-log"))
    assertEquals(20L, readTimeoutSecondsFor("/api/not-reanalyze"))
  }
}
