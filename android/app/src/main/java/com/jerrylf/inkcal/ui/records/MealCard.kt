package com.jerrylf.inkcal.ui.records

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
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
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.domain.ImageUrl
import com.jerrylf.inkcal.domain.TimeFmt
import com.jerrylf.inkcal.theme.MacroCarbs
import com.jerrylf.inkcal.theme.MacroFat
import com.jerrylf.inkcal.theme.MacroProtein
import kotlin.math.roundToInt

/**
 * 带长按菜单的餐卡。长按弹出：查看详情 / 重新分析… / 删除整餐…。
 *
 * 重新分析与删除都只是「转达」给外层，确认表单和两步确认由 RecordsTab 统一持有，
 * 日/周两个视图不用各写一份。
 */
@Composable
fun MealCardWithMenu(
  record: RecordDto,
  baseUrl: String,
  hasDecision: Boolean,
  onOpenDetail: () -> Unit,
  onReanalyze: () -> Unit,
  onDeleteMeal: () -> Unit,
  modifier: Modifier = Modifier,
) {
  var expanded by remember { mutableStateOf(false) }
  // 纯文本补录没有图，后端恒 502，与详情页同一规则：不给入口
  val canReanalyze =
    record.photos.any { it.thumbnailUrl.isNotBlank() } || record.replacementImage.isNotBlank()

  Box {
    MealCard(
      record = record,
      baseUrl = baseUrl,
      hasDecision = hasDecision,
      onClick = onOpenDetail,
      onLongClick = { expanded = true },
      modifier = modifier,
    )
    DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
      DropdownMenuItem(
        text = { Text("查看详情") },
        onClick = {
          expanded = false
          onOpenDetail()
        },
      )
      if (canReanalyze) {
        DropdownMenuItem(
          text = { Text("重新分析…") },
          onClick = {
            expanded = false
            onReanalyze()
          },
        )
      }
      DropdownMenuItem(
        text = { Text("删除整餐…", color = MaterialTheme.colorScheme.error) },
        onClick = {
          expanded = false
          onDeleteMeal()
        },
      )
    }
  }
}

/** 餐卡，对应 docs/android-app-spec.md §8.4。整卡可点，点击进详情；[onLongClick] 非空时长按可用。 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun MealCard(
  record: RecordDto,
  baseUrl: String,
  hasDecision: Boolean,
  onClick: () -> Unit,
  modifier: Modifier = Modifier,
  onLongClick: (() -> Unit)? = null,
) {
  Card(
    modifier =
      modifier.fillMaxWidth().combinedClickable(onClick = onClick, onLongClick = onLongClick)
  ) {
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
        Row(verticalAlignment = Alignment.CenterVertically) {
          Text(
            text = "${TimeFmt.clock(record.photoTime)} · ${sourceLabel(record)} · ${confidenceLabel(record.confidence)}",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
          )
          if (hasDecision) {
            // 有覆盖本组的 Luna 决策；无障碍读作「Luna 决策」，展开看明细请进详情
            Text(
              text = "  🤖",
              style = MaterialTheme.typography.labelSmall,
              modifier = Modifier.semantics { contentDescription = "Luna 决策" },
            )
          }
        }
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

/** P / C / F 用字母，配色与网页端一致；三者全 0 就不显示这一行。 */
@Composable
private fun MacroRow(record: RecordDto) {
  if (record.proteinG == 0.0 && record.carbsG == 0.0 && record.fatG == 0.0) return
  Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
    Macro("P", record.proteinG, MacroProtein)
    Macro("C", record.carbsG, MacroCarbs)
    Macro("F", record.fatG, MacroFat)
  }
}

@Composable
private fun Macro(letter: String, grams: Double, color: Color) {
  Row {
    Text(
      text = letter,
      style = MaterialTheme.typography.labelSmall,
      fontWeight = FontWeight.Bold,
      color = color,
    )
    Text(
      text = " ${grams.roundToInt()}",
      style = MaterialTheme.typography.labelSmall,
      color = color,
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
