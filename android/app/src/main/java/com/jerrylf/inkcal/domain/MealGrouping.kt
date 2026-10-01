package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.PhotoDto
import com.jerrylf.inkcal.data.RecordDto

/** 一天的一组记录 + 当天汇总（按主记录求和，不从 photos 重算）。 */
data class DayGroup(
  val date: String,
  val records: List<RecordDto>,
  val kcal: Double,
  val protein: Double,
  val carbs: Double,
  val fat: Double,
)

object MealGrouping {

  /**
   * 形态 A 的从行（状态延续：同一食物吃前/吃后）：不是主行，且四个数值全为 0。
   * UI 必须显示「已并入整餐估算」，绝不能显示 0 kcal——2026-08-29 事故的教训。
   */
  fun isMergedZeroRow(photo: PhotoDto, primaryAssetId: String): Boolean =
    photo.assetId != primaryAssetId &&
      photo.calories == 0.0 &&
      photo.proteinG == 0.0 &&
      photo.carbsG == 0.0 &&
      photo.fatG == 0.0

  /** 日内按拍摄时间倒序，相同再按 asset_id 倒序（与网页版一致）。 */
  fun sortInDay(records: List<RecordDto>): List<RecordDto> =
    records.sortedWith(
      compareByDescending<RecordDto> { it.photoTime }.thenByDescending { it.assetId }
    )

  /**
   * 按 photoTime 前 10 位分日，日期倒序、日内倒序。
   *
   * 注意：区间接口返回的记录已按主记录分组，形态 B（独立条目）的值已由服务端累加到
   * 主行，所以这里直接对主记录求和即可，不要再对 photos 求和。
   */
  fun groupByDate(records: List<RecordDto>): List<DayGroup> =
    records
      .groupBy { TimeFmt.dateOf(it.photoTime) }
      .map { (date, rows) ->
        val sorted = sortInDay(rows)
        DayGroup(
          date = date,
          records = sorted,
          kcal = sorted.sumOf { it.calories },
          protein = sorted.sumOf { it.proteinG },
          carbs = sorted.sumOf { it.carbsG },
          fat = sorted.sumOf { it.fatG },
        )
      }
      .sortedByDescending { it.date }
}
