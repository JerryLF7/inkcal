package com.jerrylf.inkcal.domain

/**
 * 热量缺口：`TDEE = BMR + 当日活动消耗`，`缺口 = TDEE − 摄入`。
 *
 * 三级降级（docs/android-app-spec.md §7）：
 *   有 BMR 且有当天 burn -> BMR + active_kcal（正式口径）
 *   有 BMR 但没有 burn   -> 仅 BMR（历史日期常态，偏保守）
 *   没填体征             -> 固定 2500（纯兜底常量，不是目标值）
 *
 * BMR 一律由服务端算，客户端不自己算。
 */
object Tdee {

  const val FALLBACK_KCAL = 2500.0

  fun tdee(bmr: Double?, activeKcal: Double?): Double =
    if (bmr != null) bmr + (activeKcal ?: 0.0) else FALLBACK_KCAL

  /** 正数=有缺口，负数=超标。 */
  fun deficit(intake: Double, bmr: Double?, activeKcal: Double?): Double =
    tdee(bmr, activeKcal) - intake
}
