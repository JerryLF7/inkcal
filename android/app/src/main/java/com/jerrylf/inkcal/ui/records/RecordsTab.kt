package com.jerrylf.inkcal.ui.records

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowLeft
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jerrylf.inkcal.domain.Periods
import com.jerrylf.inkcal.domain.TimeFmt

private enum class RecordsMode(val label: String) {
  Day("日"),
  Week("周"),
  Month("月"),
}

/**
 * 记录页外壳：日 / 周 / 月切换，对应 docs/android-app-spec.md §8.1–§8.3。
 *
 * 详情弹窗、Snackbar、删除与重分析都放在这一层，而不是各自塞进子视图——三个视图的
 * 卡片都要能进详情，写操作之后也要让当前视图重拉。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecordsTab(
  dayViewModel: RecordsViewModel = viewModel(),
  rangeViewModel: RangeViewModel = viewModel(),
) {
  val today = remember { TimeFmt.hktToday() }

  var mode by rememberSaveable { mutableStateOf(RecordsMode.Day) }
  var monday by rememberSaveable { mutableStateOf(Periods.mondayOf(TimeFmt.hktToday())) }
  var monthAnchor by rememberSaveable { mutableStateOf(Periods.monthStart(TimeFmt.hktToday())) }

  val baseUrl by dayViewModel.baseUrl.collectAsStateWithLifecycle()
  val dayState by dayViewModel.state.collectAsStateWithLifecycle()
  val rangeState by rangeViewModel.state.collectAsStateWithLifecycle()
  val decisionsByDate by dayViewModel.decisionsByDate.collectAsStateWithLifecycle()
  val busy by dayViewModel.busy.collectAsStateWithLifecycle()
  val toast by dayViewModel.toast.collectAsStateWithLifecycle()
  val detailAnchor by dayViewModel.detailAnchor.collectAsStateWithLifecycle()
  val scrollTarget by dayViewModel.scrollTarget.collectAsStateWithLifecycle()

  val snackbarHostState = remember { SnackbarHostState() }

  // 详情从「当前视图」的记录里查，所以周/月视图里点开的卡片一样能正确渲染
  val activeRecords = remember(mode, dayState.groups, rangeState.groups) {
    val groups = if (mode == RecordsMode.Day) dayState.groups else rangeState.groups
    groups.flatMap { it.records }
  }
  val detailRecord = detailAnchor?.let { anchor -> activeRecords.firstOrNull { it.assetId == anchor } }

  LaunchedEffect(toast) {
    toast?.let {
      snackbarHostState.showSnackbar(it)
      dayViewModel.consumeToast()
    }
  }

  // 组没了（整餐被删、或单张移除后只剩这张）就收起详情。
  // busy 期间不判：单张移除会把锚点切到晋升的新主行，那一刻它还没出现在列表里。
  LaunchedEffect(detailAnchor, activeRecords, busy) {
    if (!busy && detailAnchor != null && detailRecord == null && activeRecords.isNotEmpty()) {
      dayViewModel.closeDetail()
    }
  }

  Column(modifier = Modifier.fillMaxSize()) {
    SingleChoiceSegmentedButtonRow(
      modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)
    ) {
      RecordsMode.entries.forEachIndexed { index, item ->
        SegmentedButton(
          selected = mode == item,
          onClick = { mode = item },
          shape = SegmentedButtonDefaults.itemShape(index = index, count = RecordsMode.entries.size),
        ) {
          Text(item.label)
        }
      }
    }

    when (mode) {
      RecordsMode.Day -> {}
      RecordsMode.Week -> {
        ArrowHeader(
          title = if (Periods.isCurrentWeek(monday, today)) "本周" else Periods.weekLabel(monday),
          subtitle = Periods.weekLabel(monday),
          canGoForward = !Periods.isFuture(Periods.addWeeks(monday, 1), today),
          onPrev = { monday = Periods.addWeeks(monday, -1) },
          onNext = { monday = Periods.addWeeks(monday, 1) },
          onToday = if (Periods.isCurrentWeek(monday, today)) null else ({ monday = Periods.mondayOf(today) }),
        )
      }
      RecordsMode.Month -> {
        ArrowHeader(
          title = Periods.monthLabel(monthAnchor),
          subtitle = null,
          canGoForward = !Periods.isFuture(Periods.addMonths(monthAnchor, 1), today),
          onPrev = { monthAnchor = Periods.addMonths(monthAnchor, -1) },
          onNext = { monthAnchor = Periods.addMonths(monthAnchor, 1) },
          onToday = if (Periods.isCurrentMonth(monthAnchor, today)) null else ({
            monthAnchor = Periods.monthStart(today)
          }),
        )
      }
    }

    Box(modifier = Modifier.weight(1f)) {
      when (mode) {
        RecordsMode.Day ->
          RecordsScreen(
            viewModel = dayViewModel,
            scrollTarget = scrollTarget,
            onScrollHandled = dayViewModel::consumeScrollTarget,
            onOpenDetail = dayViewModel::openDetail,
          )

        RecordsMode.Week ->
          WeekView(
            viewModel = rangeViewModel,
            monday = monday,
            today = today,
            baseUrl = baseUrl,
            decisionsByDate = decisionsByDate,
            onEnsureDecisions = dayViewModel::ensureDecisions,
            onOpenDetail = dayViewModel::openDetail,
          )

        RecordsMode.Month ->
          Box(modifier = Modifier.fillMaxSize().padding(horizontal = 8.dp)) {
            MonthView(
              viewModel = rangeViewModel,
              monthAnchor = monthAnchor,
              today = today,
              // 点某天：切回日视图并滚到那天
              onPickDate = { date ->
                mode = RecordsMode.Day
                dayViewModel.jumpTo(date)
              },
            )
          }
      }

      SnackbarHost(
        hostState = snackbarHostState,
        modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 8.dp),
      )
    }
  }

  if (detailRecord != null) {
    MealDetailDialog(
      record = detailRecord,
      baseUrl = baseUrl,
      decisions = decisionsByDate[TimeFmt.dateOf(detailRecord.photoTime)].orEmpty(),
      busy = busy,
      onClose = dayViewModel::closeDetail,
      onDeleteMeal = {
        // 写操作后当前视图要重拉；区间视图靠 invalidate 让下次进入时重新取
        rangeViewModel.invalidate()
        dayViewModel.delete(detailRecord.assetId, photoOnly = false)
      },
      onDeletePhoto = { assetId ->
        rangeViewModel.invalidate()
        dayViewModel.delete(assetId, photoOnly = true)
      },
      onReanalyze = { notes ->
        rangeViewModel.invalidate()
        dayViewModel.reanalyze(detailRecord.assetId, notes)
      },
    )
  }
}

/** 周/月共用的标题栏：标题 + 前后箭头 +（不在本周/本月时）回到今天。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ArrowHeader(
  title: String,
  subtitle: String?,
  canGoForward: Boolean,
  onPrev: () -> Unit,
  onNext: () -> Unit,
  onToday: (() -> Unit)?,
) {
  Row(
    modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp),
    verticalAlignment = Alignment.CenterVertically,
  ) {
    IconButton(onClick = onPrev) {
      Icon(Icons.Filled.KeyboardArrowLeft, contentDescription = "上一页")
    }
    Column(modifier = Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
      Text(
        text = title,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.SemiBold,
      )
      if (subtitle != null) {
        Text(
          text = subtitle,
          style = MaterialTheme.typography.labelSmall,
          color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
      }
    }
    if (onToday != null) {
      TextButton(onClick = onToday) { Text("今天") }
    } else {
      Box(modifier = Modifier.padding(horizontal = 12.dp))
    }
    IconButton(onClick = onNext, enabled = canGoForward) {
      Icon(Icons.Filled.KeyboardArrowRight, contentDescription = "下一页")
    }
  }
}
