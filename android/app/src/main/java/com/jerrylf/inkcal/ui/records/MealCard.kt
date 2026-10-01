package com.jerrylf.inkcal.ui.records

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.domain.ImageUrl
import com.jerrylf.inkcal.domain.TimeFmt
import kotlin.math.roundToInt

/** 餐卡，对应 docs/android-app-spec.md §8.4。 */
@Composable
fun MealCard(record: RecordDto, baseUrl: String, modifier: Modifier = Modifier) {
  Card(modifier = modifier.fillMaxWidth()) {
    Row(
      modifier = Modifier.padding(12.dp),
      horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
      MealThumb(record, baseUrl)

      Column(
        modifier = Modifier.weight(1f),
        verticalArrangement = Arrangement.spacedBy(3.dp),
      ) {
        // 主标题超长折行显示，不截断
        Text(
          text = record.meal.ifBlank { "未命名" },
          style = MaterialTheme.typography.titleSmall,
          fontWeight = FontWeight.SemiBold,
        )
        if (record.mealDetail.isNotBlank()) {
          Text(
            text = record.mealDetail,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
          )
        }
        Text(
          text = "${TimeFmt.clock(record.photoTime)} · ${sourceLabel(record)} · ${confidenceLabel(record.confidence)}",
          style = MaterialTheme.typography.labelSmall,
          color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
          MacroRow(record)
          Box(Modifier.weight(1f))
          Text(
            text = "${record.calories.roundToInt()} kcal",
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.Medium,
            color = MaterialTheme.colorScheme.onSurface,
          )
        }
      }
    }
  }
}

/** 缩略图 96dp；多图显示 ×N；无图时用 emoji 顶替餐盘。 */
@Composable
private fun MealThumb(record: RecordDto, baseUrl: String) {
  val url = ImageUrl.thumbnail(baseUrl, record.thumbnailUrl, record.replacementImage)

  BadgedBox(
    badge = {
      if (record.photos.size > 1) {
        Badge { Text("×${record.photos.size}") }
      }
    }
  ) {
    Box(
      modifier =
        Modifier.size(96.dp)
          .clip(RoundedCornerShape(8.dp))
          .background(MaterialTheme.colorScheme.surfaceVariant),
      contentAlignment = Alignment.Center,
    ) {
      if (url != null) {
        AsyncImage(
          model = url,
          contentDescription = null,
          contentScale = ContentScale.Crop,
          modifier = Modifier.fillMaxSize(),
        )
      } else {
        Text(
          text = record.emoji.ifBlank { "🍽️" },
          fontSize = emojiFontSize(record.emoji),
          maxLines = 1,
        )
      }
    }
  }
}

/** P / C / F 用字母，三者全 0 就不显示这一行。 */
@Composable
private fun MacroRow(record: RecordDto) {
  if (record.proteinG == 0.0 && record.carbsG == 0.0 && record.fatG == 0.0) return
  Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
    Macro("P", record.proteinG)
    Macro("C", record.carbsG)
    Macro("F", record.fatG)
  }
}

@Composable
private fun Macro(letter: String, grams: Double) {
  Row {
    Text(
      text = letter,
      style = MaterialTheme.typography.labelSmall,
      fontWeight = FontWeight.Bold,
      color = MaterialTheme.colorScheme.primary,
    )
    Text(
      text = " ${grams.roundToInt()}",
      style = MaterialTheme.typography.labelSmall,
      color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
  }
}

/** emoji 按字符数（码点）自适应字号，1 个字符最大。 */
private fun emojiFontSize(emoji: String): TextUnit {
  val count = if (emoji.isEmpty()) 0 else emoji.codePointCount(0, emoji.length)
  return when {
    count <= 1 -> 38.sp
    count == 2 -> 30.sp
    count == 3 -> 24.sp
    else -> 20.sp
  }
}

/** source_type 可能缺失：缺失时 asset_id 以 manual- 开头算手动，其余当 Immich。 */
private fun sourceLabel(record: RecordDto): String =
  when {
    record.sourceType == "manual" -> "手动"
    record.sourceType == "photoprism" -> "PhotoPrism"
    record.sourceType == "immich" -> "Immich"
    record.assetId.startsWith("manual-") -> "手动"
    else -> "Immich"
  }

private fun confidenceLabel(confidence: String): String =
  when (confidence) {
    "high" -> "置信度高"
    "medium" -> "置信度中"
    "low" -> "置信度低"
    else -> "置信度未知"
  }
