package com.jerrylf.inkcal.ui.records

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jerrylf.inkcal.data.DecisionDto
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.domain.DayGroup
import com.jerrylf.inkcal.domain.Decisions
import com.jerrylf.inkcal.domain.Periods
import com.jerrylf.inkcal.domain.Tdee
import com.jerrylf.inkcal.domain.TimeFmt
import com.jerrylf.inkcal.domain.WeekStats
import kotlin.math.roundToInt

private val WEEKDAY_LABELS = listOf("一", "二", "三", "四", "五", "六", "日")

/**
 * 周视图，对应 docs/android-app-spec.md §8.2。
 *
 * 上半部分是双层柱状图，下半部分是本周的餐卡时间轴（新日期在前，与日视图同规则）。
 */
@Composable
fun WeekView(
  viewModel: RangeViewModel,
  monday: String,
  today: String,
  baseUrl: String,
  decisionsByDate: Map<String, List<DecisionDto>>,
  onEnsureDecisions: (String) -> Unit,
  onOpenDetail: (RecordDto) -> Unit,
  modifier: Modifier = Modifier,
) {
  val state by viewModel.state.collectAsStateWithLifecycle()
  val bmr by viewModel.bmr.collectAsStateWithLifecycle()
  var selected by remember { mutableStateOf<WeekBar?>(null) }

  LaunchedEffect(monday) { viewModel.load(monday, Periods.weekEnd(monday)) }

  val byDate = remember(state.groups) { state.groups.associateBy { it.date } }
  val bars =
    remember(monday, state.groups, state.burns, bmr) {
      (0..6).map { offset ->
        val date = TimeFmt.plusDays(monday, offset.toLong())
        WeekBar(
          date = date,
          label = WEEKDAY_LABELS[offset],
          kcal = byDate[date]?.kcal ?: 0.0,
          tdee = Tdee.tdee(bmr, state.burns[date]?.activeKcal),
        )
      }
    }
  val stats = remember(state.groups, state.burns, bmr) {
    WeekStats.of(state.groups, state.burns, bmr)
  }

  Column(
    modifier = modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
    verticalArrangement = Arrangement.spacedBy(8.dp),
  ) {
    WeekChart(bars = bars, onBarClick = { selected = if (selected?.date == it.date) null else it })

    selected?.let { bar ->
      val intake = bar.kcal.roundToInt()
      val burn = bar.tdee.roundToInt()
      Text(
        text = "${TimeFmt.shortDate(bar.date)} · 摄入 $intake / 消耗 $burn kcal",
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
      )
    }

    Text(
      text =
        if (stats.recordedDays == 0) {
          "本周还没有记录"
        } else {
          "本周已记录 ${stats.recordedDays} 天 · 日均 ${stats.avgKcal.roundToInt()} kcal · " +
            (if (stats.totalDeficit >= 0) {
              "累计缺口 ${stats.totalDeficit.roundToInt()} kcal"
            } else {
              "累计超 ${(-stats.totalDeficit).roundToInt()} kcal"
            })
        },
      style = MaterialTheme.typography.bodyMedium,
    )

    if (state.loading) {
      Text("加载中…", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    state.error?.let {
      Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
    }

    HorizontalDivider()

    if (state.groups.isEmpty() && !state.loading) {
      Text(
        text = "本周没有记录",
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center,
        modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp),
      )
    }

    // 与日视图同规则：日期倒序、日内倒序
    state.groups.forEach { group ->
      val dayDecisions = decisionsByDate[group.date].orEmpty()
      LaunchedEffect(group.date) { onEnsureDecisions(group.date) }
      DaySection(
        group = group,
        bmr = bmr,
        activeKcal = state.burns[group.date]?.activeKcal,
        isToday = group.date == today,
        baseUrl = baseUrl,
        decisions = dayDecisions,
        onOpenDetail = onOpenDetail,
      )
    }
  }
}

/** 日期分隔线 + 该日的餐卡，周视图与月视图共用。 */
@Composable
internal fun DaySection(
  group: DayGroup,
  bmr: Double?,
  activeKcal: Double?,
  isToday: Boolean,
  baseUrl: String,
  decisions: List<DecisionDto>,
  onOpenDetail: (RecordDto) -> Unit,
) {
  DateSeparator(
    date = group.date,
    kcal = group.kcal,
    protein = group.protein,
    carbs = group.carbs,
    fat = group.fat,
    bmr = bmr,
    activeKcal = activeKcal,
    isToday = isToday,
  )
  group.records.forEach { record ->
    MealCard(
      record = record,
      baseUrl = baseUrl,
      hasDecision = Decisions.forRecord(record, decisions).isNotEmpty(),
      onClick = { onOpenDetail(record) },
      modifier = Modifier.padding(horizontal = 4.dp, vertical = 3.dp),
    )
  }
}
