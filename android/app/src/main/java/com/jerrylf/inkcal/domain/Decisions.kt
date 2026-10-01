package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.DecisionDto
import com.jerrylf.inkcal.data.RecordDto

/**
 * Luna 批处理审计记录的匹配与文案（docs/android-app-spec.md §8.4 的 🤖 决策块）。
 *
 * 匹配范围是**组内全部 asset_id**（主行 + photos）再加上 decision 的 target_asset_id：
 * 一条 update 决策可能挂在这组任意一张照片上。
 */
object Decisions {

  fun groupAssetIds(record: RecordDto): Set<String> =
    (listOf(record.assetId) + record.photos.map { it.assetId })
      .filter { it.isNotBlank() }
      .toSet()

  fun forRecord(record: RecordDto, all: List<DecisionDto>): List<DecisionDto> {
    val ids = groupAssetIds(record)
    return all.filter { decision ->
      decision.assetIds.any { it in ids } || decision.targetAssetId?.let { it in ids } == true
    }
  }

  fun actionLabel(action: String): String =
    when (action) {
      "add" -> "新增"
      "update" -> "合并更新"
      "skip" -> "跳过"
      else -> action
    }

  fun relationLabel(relation: String): String =
    when (relation) {
      "new_meal" -> "新餐"
      "same_meal" -> "同餐"
      "rejected" -> "非食物"
      else -> relation
    }

  /** 「新增 · 新餐」；关系为空时只显示动作。 */
  fun headline(decision: DecisionDto): String {
    val action = actionLabel(decision.action)
    val relation = relationLabel(decision.relation)
    return if (relation.isBlank()) action else "$action · $relation"
  }
}
