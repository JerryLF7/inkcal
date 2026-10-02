package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.BurnDto

/** 周汇总（docs/android-app-spec.md §8.2 的汇总行）。 */
data class WeekStats(
  val recordedDays: Int,
  val totalIntake: Double,
  /** 只对有记录的天求平均，漏记的天不进分母。 */
  val avgKcal: Double,
  /** 累计缺口，正数=有缺口。只统计有记录的天。 */
  val totalDeficit: Double,
) {
  companion object {
    /**
     * 累计缺口只算有记录的天：漏记会被算成「摄入 0」，那会虚增缺口（已拍板）。
     * 今天这种只有半天的记录照常算进分母。
     */
    fun of(groups: List<DayGroup>, burns: Map<String, BurnDto>, bmr: Double?): WeekStats {
      val recorded = groups.filter { it.records.isNotEmpty() }
      if (recorded.isEmpty()) return WeekStats(0, 0.0, 0.0, 0.0)

      val totalIntake = recorded.sumOf { it.kcal }
      val deficit =
        recorded.sumOf { group -> Tdee.deficit(group.kcal, bmr, burns[group.date]?.activeKcal) }

      return WeekStats(
        recordedDays = recorded.size,
        totalIntake = totalIntake,
        avgKcal = totalIntake / recorded.size,
        totalDeficit = deficit,
      )
    }
  }
}
