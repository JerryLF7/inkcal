package com.jerrylf.inkcal.ui.records

import com.jerrylf.inkcal.data.RecordDto

/** 卡片与详情共用的文案映射。 */

/** source_type 可能缺失：缺失时 asset_id 以 manual- 开头算手动，其余当 Immich。 */
internal fun sourceLabel(record: RecordDto): String =
  when {
    record.sourceType == "manual" -> "手动"
    record.sourceType == "photoprism" -> "PhotoPrism"
    record.sourceType == "immich" -> "Immich"
    record.assetId.startsWith("manual-") -> "手动"
    else -> "Immich"
  }

internal fun confidenceLabel(confidence: String): String =
  when (confidence) {
    "high" -> "置信度高"
    "medium" -> "置信度中"
    "low" -> "置信度低"
    else -> "置信度未知"
  }
