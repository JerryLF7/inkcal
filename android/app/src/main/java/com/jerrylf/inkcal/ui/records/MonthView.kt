package com.jerrylf.inkcal.ui.records

import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jerrylf.inkcal.domain.MonthCell
import com.jerrylf.inkcal.domain.MonthGrid
import com.jerrylf.inkcal.domain.MonthRing
import com.jerrylf.inkcal.domain.Periods

private val RingDeficit = Color(0xFF4CAF50)
private val RingOver = Color(0xFFE5484D)

/**
 * 月视图，对应 docs/android-app-spec.md §8.3。
 *
 * 二值语义：有记录且没超消耗 = 绿环，超消耗 = 红环，没记录不画环；数字保持中性色，
 * 颜色只由圆环承载。点某天跳回日视图。
 *
 * 42 个格子用普通 Column/Row 铺就够了，不必上 LazyVerticalGrid——反而会和外层
 * 滚动嵌套。
 */
@Composable
fun MonthView(
  viewModel: RangeViewModel,
  monthAnchor: String,
  today: String,
  onPickDate: (String) -> Unit,
  modifier: Modifier = Modifier,
) {
  val state by viewModel.state.collectAsStateWithLifecycle()
  val bmr by viewModel.bmr.collectAsStateWithLifecycle()

  LaunchedEffect(monthAnchor) {
    viewModel.load(Periods.monthStart(monthAnchor), Periods.monthEnd(monthAnchor))
  }

  // 只读自己这一月的槽位：pager 里相邻两月同时在屏，不能共享一份状态
  val chunk = state.chunk(Periods.monthStart(monthAnchor), Periods.monthEnd(monthAnchor))

  val cells = remember(monthAnchor, chunk.groups, chunk.burns, bmr) {
    MonthGrid.build(monthAnchor, chunk.groups, chunk.burns, bmr)
  }
  val blanks = remember(monthAnchor) { Periods.leadingBlanks(monthAnchor) }
  val slots: List<MonthCell?> = remember(cells, blanks) { List(blanks) { null } + cells }

  Column(
    modifier = modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
    verticalArrangement = Arrangement.spacedBy(4.dp),
  ) {
    Row(modifier = Modifier.fillMaxWidth()) {
      listOf("一", "二", "三", "四", "五", "六", "日").forEach { label ->
        Text(
          text = label,
          style = MaterialTheme.typography.labelSmall,
          color = MaterialTheme.colorScheme.onSurfaceVariant,
          textAlign = TextAlign.Center,
          modifier = Modifier.weight(1f),
        )
      }
    }

    slots.chunked(7).forEach { week ->
      Row(modifier = Modifier.fillMaxWidth()) {
        week.forEach { cell ->
          Box(modifier = Modifier.weight(1f)) {
            if (cell != null) {
              MonthDayCell(cell = cell, isToday = cell.date == today, onPick = onPickDate)
            }
          }
        }
        // 最后一周补齐，保持列宽一致
        repeat(7 - week.size) { Box(modifier = Modifier.weight(1f)) {} }
      }
    }

    Row(
      modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
      horizontalArrangement = Arrangement.spacedBy(16.dp),
      verticalAlignment = Alignment.CenterVertically,
    ) {
      LegendItem(RingDeficit, "有缺口")
      LegendItem(RingOver, "超消耗")
    }

    chunk.error?.let {
      Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
    }
  }
}

@Composable
private fun MonthDayCell(cell: MonthCell, isToday: Boolean, onPick: (String) -> Unit) {
  Box(
    modifier =
      Modifier.aspectRatio(1f)
        .padding(3.dp)
        .clip(CircleShape)
        .clickable { onPick(cell.date) }
        .then(if (isToday) Modifier.border(2.dp, MaterialTheme.colorScheme.primary, CircleShape) else Modifier),
    contentAlignment = Alignment.Center,
  ) {
    if (cell.ring != MonthRing.NONE) {
      CircularProgressIndicator(
        progress = { cell.progress },
        color = if (cell.ring == MonthRing.OVER) RingOver else RingDeficit,
        trackColor = MaterialTheme.colorScheme.surfaceVariant,
        strokeWidth = 3.dp,
        modifier = Modifier.fillMaxSize().padding(3.dp),
      )
    }
    Text(
      text = "${cell.dayOfMonth}",
      style = MaterialTheme.typography.labelMedium,
      fontWeight = if (cell.hasRecords) FontWeight.Bold else FontWeight.Normal,
    )
  }
}

@Composable
private fun LegendItem(color: Color, label: String) {
  Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
    Box(modifier = Modifier.size(10.dp).clip(CircleShape).border(2.dp, color, CircleShape))
    Text(
      text = label,
      style = MaterialTheme.typography.labelSmall,
      color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
  }
}
