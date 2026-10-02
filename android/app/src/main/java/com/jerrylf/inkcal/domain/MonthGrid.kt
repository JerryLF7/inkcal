package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.BurnDto

/**
 * 月视图圆环的二值语义（已拍板，docs/android-app-spec.md §8.3）：
 * 有记录且没超消耗 = 绿环（有缺口），超消耗 = 红环，当天没记录 = 不画环。
 *
 * 数字保持中性色，颜色只由圆环承载，避免「数字红 + 环绿」这种双语义打架。
 */
enum class MonthRing {
  NONE,
  DEFICIT,
  OVER,
}

data class MonthCell(
  val date: String,
  val dayOfMonth: Int,
  val kcal: Double,
  /** 当日 TDEE，缺口/超标的分母。 */
  val tdee: Double,
  val ring: MonthRing,
  val hasRecords: Boolean,
) {
  /** CircularProgressIndicator 只要 0..1。 */
  val progress: Float
    get() = if (tdee <= 0.0) 0f else (kcal / tdee).coerceIn(0.0, 1.0).toFloat()
}

object MonthGrid {

  /**
   * 把整月铺成格子。**必须遍历月里每一天**：区间接口只会返回有记录的日期，
   * 没有记录的天在 groups 里根本不存在，直接映射会漏格子。
   */
  fun build(
    monthAnchor: String,
    groups: List<DayGroup>,
    burns: Map<String, BurnDto>,
    bmr: Double?,
  ): List<MonthCell> {
    val byDate = groups.associateBy { it.date }
    return Periods.daysOfMonth(monthAnchor).map { date ->
      val group = byDate[date]
      val kcal = group?.kcal ?: 0.0
      val tdee = Tdee.tdee(bmr, burns[date]?.activeKcal)
      MonthCell(
        date = date,
        dayOfMonth = dayOfMonthOf(date),
        kcal = kcal,
        tdee = tdee,
        ring =
          when {
            kcal <= 0.0 -> MonthRing.NONE
            kcal > tdee -> MonthRing.OVER
            else -> MonthRing.DEFICIT
          },
        hasRecords = group != null,
      )
    }
  }

  /** YYYY-MM-DD → 日号，不走 java.time，避免多一层时区风险。 */
  private fun dayOfMonthOf(date: String): Int =
    date.takeLast(2).trimStart('0').toIntOrNull() ?: 0
}
