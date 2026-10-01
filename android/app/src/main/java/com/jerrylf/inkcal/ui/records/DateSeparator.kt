package com.jerrylf.inkcal.ui.records

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.jerrylf.inkcal.domain.Tdee
import com.jerrylf.inkcal.domain.TimeFmt
import kotlin.math.roundToInt

private val DeficitGreen = Color(0xFF4CAF50)

/**
 * 吸顶日期分隔线：左日期/星期，右当天汇总。
 *
 * 摄入与缺口都基于主记录求和（服务端已把形态 B 的值累加到主行），不从 photos 重算。
 */
@Composable
fun DateSeparator(
  date: String,
  kcal: Double,
  protein: Double,
  carbs: Double,
  fat: Double,
  bmr: Double?,
  activeKcal: Double?,
  isToday: Boolean,
) {
  // 今天只有半天数据，加 ~ 并弱化显示（已拍板：照显不隐藏）
  val dim = if (isToday) 0.65f else 1f
  val deficit = Tdee.deficit(kcal, bmr, activeKcal)
  val over = deficit < 0

  Surface(color = MaterialTheme.colorScheme.surface) {
    Row(
      modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 8.dp),
      verticalAlignment = Alignment.CenterVertically,
      horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
      Text(
        text = "${TimeFmt.shortDate(date)} ${TimeFmt.weekday(date)}",
        style = MaterialTheme.typography.labelLarge,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onSurface,
      )

      Row(
        modifier = Modifier.weight(1f),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
      ) {
        Text(
          text = if (isToday) "~${kcal.roundToInt()} kcal" else "${kcal.roundToInt()} kcal",
          style = MaterialTheme.typography.labelMedium,
          color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = dim),
        )
        if (protein > 0 || carbs > 0 || fat > 0) {
          Text(
            text =
              "P${protein.roundToInt()} C${carbs.roundToInt()} F${fat.roundToInt()}",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = dim),
          )
        }
      }

      val chipColor = if (over) MaterialTheme.colorScheme.error else DeficitGreen
      Surface(
        color = chipColor.copy(alpha = 0.18f),
        shape = RoundedCornerShape(6.dp),
      ) {
        Text(
          text =
            if (over) "超 ${(-deficit).roundToInt()}" else "缺口 ${deficit.roundToInt()}",
          style = MaterialTheme.typography.labelSmall,
          fontWeight = FontWeight.Medium,
          color = chipColor.copy(alpha = dim),
          modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
        )
      }
    }
  }
}
