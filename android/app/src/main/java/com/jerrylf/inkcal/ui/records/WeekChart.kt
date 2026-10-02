package com.jerrylf.inkcal.ui.records

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/** 一天一根柱子：底层是当日 TDEE，上层是摄入。 */
data class WeekBar(
  val date: String,
  val label: String,
  val kcal: Double,
  val tdee: Double,
)

/** 与网页版一致的取色：灰底、蓝摄入、超标转红。 */
private val BarBase = Color(0xFF2C313A)
private val BarIntake = Color(0xFF5B8DEF)
private val BarOver = Color(0xFFE5484D)

/**
 * 双层柱状图，对应 docs/android-app-spec.md §8.2。这是全 App 唯一需要自绘的控件。
 *
 * 归一化：`max = max(各日 kcal 与 tdee 的最大值, 1)`，柱高按比例，有值时最低 2%
 * 保证「有记录但很小」也看得见。标签用普通 Text 排在下面，省掉 Canvas 里测文本。
 */
@Composable
fun WeekChart(
  bars: List<WeekBar>,
  onBarClick: (WeekBar) -> Unit,
  modifier: Modifier = Modifier,
) {
  Column(modifier = modifier) {
    Canvas(
      modifier =
        Modifier.fillMaxWidth()
          .height(170.dp)
          .pointerInput(bars) {
            detectTapGestures { offset ->
              if (bars.isEmpty()) return@detectTapGestures
              val slot = size.width.toFloat() / bars.size
              val index = (offset.x / slot).toInt().coerceIn(0, bars.size - 1)
              onBarClick(bars[index])
            }
          }
    ) {
      if (bars.isEmpty()) return@Canvas
      val slot = size.width / bars.size
      val maxValue = bars.maxOf { maxOf(it.kcal, it.tdee) }.coerceAtLeast(1.0)
      val minVisible = size.height * 0.02f

      bars.forEachIndexed { index, bar ->
        val centerX = slot * index + slot / 2

        // 底层：当日 TDEE（灰）
        val tdeeHeight = (bar.tdee / maxValue * size.height).toFloat()
        if (tdeeHeight > 0f) {
          drawRoundRect(
            color = BarBase,
            topLeft = Offset(centerX - slot * 0.35f, size.height - tdeeHeight),
            size = Size(slot * 0.7f, tdeeHeight),
            cornerRadius = CornerRadius(slot * 0.12f, slot * 0.12f),
          )
        }

        // 上层：摄入（蓝，超标转红）；没吃就不画
        if (bar.kcal > 0.0) {
          val intakeHeight = (bar.kcal / maxValue * size.height).toFloat().coerceAtLeast(minVisible)
          drawRoundRect(
            color = if (bar.kcal > bar.tdee) BarOver else BarIntake,
            topLeft = Offset(centerX - slot * 0.275f, size.height - intakeHeight),
            size = Size(slot * 0.55f, intakeHeight),
            cornerRadius = CornerRadius(slot * 0.1f, slot * 0.1f),
          )
        }
      }
    }

    Row(modifier = Modifier.fillMaxWidth().padding(top = 4.dp)) {
      bars.forEach { bar ->
        Text(
          text = bar.label,
          style = MaterialTheme.typography.labelSmall,
          color = MaterialTheme.colorScheme.onSurfaceVariant,
          textAlign = TextAlign.Center,
          modifier = Modifier.weight(1f),
        )
      }
    }
  }
}
