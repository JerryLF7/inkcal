package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.PhotoDto
import com.jerrylf.inkcal.data.RecordDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DetailRefreshTest {

  private fun rec(
    id: String,
    kcal: Double = 500.0,
    photoIds: List<String> = listOf(id),
  ) =
    RecordDto(
      assetId = id,
      photoTime = "2026-11-23T12:00:00+08:00",
      meal = "午餐",
      calories = kcal,
      photos = photoIds.map { PhotoDto(assetId = it, photoTime = "2026-11-23T12:00:00+08:00") },
    )

  @Test
  fun `findGroup prefers promoted anchor first`() {
    val old = rec("a1", photoIds = listOf("a1", "a2"))
    val promoted = rec("a2", kcal = 0.0, photoIds = listOf("a2"))
    val other = rec("b1")

    val found =
      DetailRefresh.findGroup(
        dayRecords = listOf(other, promoted),
        preferredAnchor = "a2",
        previousKnownIds = DetailRefresh.knownAssetIds(old),
      )
    assertEquals("a2", found?.assetId)
    assertTrue(DetailRefresh.isZeroValueRecord(found!!))
  }

  @Test
  fun `findGroup falls back to intersecting known asset ids`() {
    val old = rec("a1", photoIds = listOf("a1", "a2", "a3"))
    val remaining = rec("a3", kcal = 420.0, photoIds = listOf("a3"))

    val found =
      DetailRefresh.findGroup(
        dayRecords = listOf(rec("x1"), remaining),
        preferredAnchor = "a1",
        previousKnownIds = DetailRefresh.knownAssetIds(old),
      )
    assertEquals("a3", found?.assetId)
    assertFalse(DetailRefresh.isZeroValueRecord(found!!))
  }

  @Test
  fun `findGroup returns null when group is gone`() {
    val old = rec("a1")
    val found =
      DetailRefresh.findGroup(
        dayRecords = listOf(rec("b1")),
        preferredAnchor = "a1",
        previousKnownIds = DetailRefresh.knownAssetIds(old),
      )
    assertNull(found)
  }
}
