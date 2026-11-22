package com.jerrylf.inkcal.domain

import com.jerrylf.inkcal.data.RecordDto

/**
 * 详情页原地刷新分组的纯逻辑（docs/android-app-spec.md §8.4 `refreshGroup`）。
 *
 * 删除单张或组级重新分析后，服务端返回的当天列表里，原先的主行 asset_id 可能已被晋升替换：
 * 优先按 `preferredAnchor`（删主行时的 `promoted`，否则原主行）找；
 * 找不到则按原先已知的组内全部 `asset_id` 集合做交集兜底；都找不到视为整组已消失。
 */
object DetailRefresh {

  fun knownAssetIds(record: RecordDto): Set<String> =
    (listOf(record.assetId) + record.photos.map { it.assetId })
      .filter { it.isNotBlank() }
      .toSet()

  fun findGroup(
    dayRecords: List<RecordDto>,
    preferredAnchor: String,
    previousKnownIds: Set<String>,
  ): RecordDto? {
    dayRecords.firstOrNull { it.assetId == preferredAnchor }?.let { return it }
    if (previousKnownIds.isEmpty()) return null
    return dayRecords.firstOrNull { rec ->
      rec.assetId in previousKnownIds || rec.photos.any { it.assetId in previousKnownIds }
    }
  }

  /** 形态 A 删掉主照片后晋升上来的旧从行四项数值全 0，需提示用户重新估算。 */
  fun isZeroValueRecord(record: RecordDto): Boolean =
    record.calories == 0.0 &&
      record.proteinG == 0.0 &&
      record.carbsG == 0.0 &&
      record.fatG == 0.0
}
