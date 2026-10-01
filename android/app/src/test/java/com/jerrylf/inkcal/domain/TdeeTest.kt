package com.jerrylf.inkcal.domain

import org.junit.Assert.assertEquals
import org.junit.Test

/** TDEE 三级降级（docs/android-app-spec.md §7）。 */
class TdeeTest {

  @Test
  fun `有 BMR 有当天消耗，用正式口径`() {
    assertEquals(1777.5 + 1092.0, Tdee.tdee(1777.5, 1092.0), 0.001)
  }

  @Test
  fun `有 BMR 但当天没同步消耗，只用 BMR`() {
    assertEquals(1777.5, Tdee.tdee(1777.5, null), 0.001)
  }

  @Test
  fun `没填体征退回 2500 兜底`() {
    assertEquals(2500.0, Tdee.tdee(null, 1092.0), 0.001)
    assertEquals(2500.0, Tdee.tdee(null, null), 0.001)
  }

  @Test
  fun `缺口正数是有缺口，负数表示超标`() {
    // BMR 1777.5 + 活动 1092 = 2869.5
    assertEquals(869.5, Tdee.deficit(2000.0, 1777.5, 1092.0), 0.001)
    assertEquals(-30.5, Tdee.deficit(2900.0, 1777.5, 1092.0), 0.001)
  }
}
