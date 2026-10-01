package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.PhotoDto
import com.jerrylf.inkcal.data.RecordDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MealGroupingTest {

  private fun record(assetId: String, photoTime: String, kcal: Double = 0.0) =
    RecordDto(
      assetId = assetId,
      photoTime = photoTime,
      meal = "餐 $assetId",
      calories = kcal,
      proteinG = kcal / 10,
      carbsG = kcal / 5,
      fatG = kcal / 20,
    )

  @Test
  fun `形态 A 判据：非主行且四项全零`() {
    val primary = PhotoDto(assetId = "p", calories = 500.0)
    val zeroRow = PhotoDto(assetId = "c", calories = 0.0, proteinG = 0.0, carbsG = 0.0, fatG = 0.0)
    val valuedRow = PhotoDto(assetId = "c", calories = 120.0)

    assertFalse("主行永远不是从行", MealGrouping.isMergedZeroRow(primary, "p"))
    assertTrue(MealGrouping.isMergedZeroRow(zeroRow, "p"))
    assertFalse(MealGrouping.isMergedZeroRow(valuedRow, "p"))
  }

  @Test
  fun `日内按拍摄时间倒序，相同按 asset_id 倒序`() {
    val sorted =
      MealGrouping.sortInDay(
        listOf(
          record("aaa", "2026-10-01T08:00:00+08:00"),
          record("zzz", "2026-10-01T12:00:00+08:00"),
          record("bbb", "2026-10-01T08:00:00+08:00"),
        )
      )
    assertEquals(listOf("zzz", "bbb", "aaa"), sorted.map { it.assetId })
  }

  @Test
  fun `分日倒序，汇总只对主记录求和`() {
    val groups =
      MealGrouping.groupByDate(
        listOf(
          record("a", "2026-09-30T12:00:00+08:00", 1000.0),
          record("b", "2026-10-01T09:00:00+08:00", 200.0),
          record("c", "2026-10-01T18:00:00+08:00", 800.0),
        )
      )

    assertEquals(listOf("2026-10-01", "2026-09-30"), groups.map { it.date })
    assertEquals(1000.0, groups[0].kcal, 0.001)
    assertEquals(1000.0, groups[1].kcal, 0.001)
    // 日内倒序：晚饭在午饭前面
    assertEquals(listOf("c", "b"), groups[0].records.map { it.assetId })
  }

  @Test
  fun `凌晨记录归当天而不是前一天`() {
    val groups = MealGrouping.groupByDate(listOf(record("x", "2026-10-01T00:30:00+08:00")))
    assertEquals("2026-10-01", groups.single().date)
  }

  @Test
  fun `详情画廊按拍摄时间升序，后端的主行在前不算全序`() {
    val rec =
      RecordDto(
        assetId = "primary",
        photoTime = "2026-10-01T12:00:00+08:00",
        photos =
          listOf(
            PhotoDto(assetId = "primary", photoTime = "2026-10-01T12:00:00+08:00"),
            PhotoDto(assetId = "later", photoTime = "2026-10-01T12:05:00+08:00"),
            PhotoDto(assetId = "earlier", photoTime = "2026-10-01T11:59:00+08:00"),
          ),
      )
    assertEquals(
      listOf("earlier", "primary", "later"),
      MealGrouping.sortedPhotos(rec).map { it.assetId },
    )
  }

  @Test
  fun `没有 photos 时用主记录自身合成一张，详情页不至于空着`() {
    val rec = RecordDto(assetId = "solo", photoTime = "2026-10-01T12:00:00+08:00", calories = 500.0)
    val photos = MealGrouping.sortedPhotos(rec)
    assertEquals(1, photos.size)
    assertEquals("solo", photos.single().assetId)
    assertEquals(500.0, photos.single().calories, 0.001)
  }
}
