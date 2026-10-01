package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.DecisionDto
import com.jerrylf.inkcal.data.PhotoDto
import com.jerrylf.inkcal.data.RecordDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 决策块的匹配范围是组内全部 asset_id（主行 + photos）再加上 target_asset_id。
 * 一条 update 决策常常挂在组里某一张从行上，只比主行会漏掉。
 */
class DecisionsTest {

  private val record =
    RecordDto(
      assetId = "primary",
      photoTime = "2026-10-01T12:00:00+08:00",
      photos =
        listOf(
          PhotoDto(assetId = "primary"),
          PhotoDto(assetId = "second"),
        ),
    )

  private fun decision(
    assetIds: List<String> = emptyList(),
    target: String? = null,
    action: String = "add",
    relation: String = "new_meal",
  ) = DecisionDto(assetIds = assetIds, targetAssetId = target, action = action, relation = relation)

  @Test
  fun `命中主行`() {
    val d = decision(assetIds = listOf("primary"))
    assertEquals(listOf(d), Decisions.forRecord(record, listOf(d)))
  }

  @Test
  fun `命中组内从行`() {
    val d = decision(assetIds = listOf("second"))
    assertEquals(listOf(d), Decisions.forRecord(record, listOf(d)))
  }

  @Test
  fun `只命中 target_asset_id 也算`() {
    val d = decision(assetIds = listOf("other"), target = "second")
    assertEquals(listOf(d), Decisions.forRecord(record, listOf(d)))
  }

  @Test
  fun `别的组的决策不会串进来`() {
    val d = decision(assetIds = listOf("someone-else"), target = "another")
    assertTrue(Decisions.forRecord(record, listOf(d)).isEmpty())
  }

  @Test
  fun `文案映射`() {
    assertEquals("新增 · 新餐", Decisions.headline(decision()))
    assertEquals("合并更新 · 同餐", Decisions.headline(decision(action = "update", relation = "same_meal")))
    assertEquals("跳过 · 非食物", Decisions.headline(decision(action = "skip", relation = "rejected")))
    // 关系为空时只显示动作，不要留个孤零零的分隔符
    assertEquals("新增", Decisions.headline(decision(relation = "")))
  }
}
