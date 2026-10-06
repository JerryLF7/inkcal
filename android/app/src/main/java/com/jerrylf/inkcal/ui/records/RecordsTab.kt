package com.jerrylf.inkcal.ui.records

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jerrylf.inkcal.data.AppContainer
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.domain.Periods
import com.jerrylf.inkcal.ui.picker.PhotoPickerScreen
import com.jerrylf.inkcal.domain.TimeFmt
import kotlinx.coroutines.launch

private enum class RecordsMode(val label: String) {
  Day("日"),
  Week("周"),
  Month("月"),
}

/**
 * 周/月 pager 的中点页码。page = CENTER 就是本周/本月，pageCount 只到 CENTER+1，
 * 所以不能滑进未来；CENTER 往前的页数足够覆盖任何实际使用（1000 周 ≈ 19 年）。
 */
private const val WEEK_CENTER = 1000
private const val MONTH_CENTER = 1200

/**
 * 记录页外壳：日 / 周 / 月切换，对应 docs/android-app-spec.md §8.1–§8.3。
 *
 * 详情弹窗、Snackbar、删除与重分析都放在这一层，而不是各自塞进子视图——三个视图的
 * 卡片都要能进详情，写操作之后也要让当前视图重拉。
 *
 * 周/月视图是 HorizontalPager：左右滑动切周/月（2026-10-04 起），标题栏的箭头
 * 和「今天」只是 pager 的遥控器。RangeViewModel 按区间缓存，相邻两页同屏时
 * 各显示各的数据。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecordsTab(
  dayViewModel: RecordsViewModel = viewModel(),
  rangeViewModel: RangeViewModel = viewModel(),
) {
  val today = remember { TimeFmt.hktToday() }
  val todayMonday = remember { Periods.mondayOf(today) }
  val todayMonth = remember { Periods.monthStart(today) }
  val scope = rememberCoroutineScope()

  var mode by rememberSaveable { mutableStateOf(RecordsMode.Day) }
  var showPicker by rememberSaveable { mutableStateOf(false) }

  // 旋转/进程重建后回到滑到的那一周/月
  var weekPage by rememberSaveable { mutableIntStateOf(WEEK_CENTER) }
  var monthPage by rememberSaveable { mutableIntStateOf(MONTH_CENTER) }
  val weekPager = rememberPagerState(initialPage = weekPage, pageCount = { WEEK_CENTER + 1 })
  val monthPager = rememberPagerState(initialPage = monthPage, pageCount = { MONTH_CENTER + 1 })
  LaunchedEffect(weekPager) {
    snapshotFlow { weekPager.settledPage }.collect { weekPage = it }
  }
  LaunchedEffect(monthPager) {
    snapshotFlow { monthPager.settledPage }.collect { monthPage = it }
  }

  val monday = Periods.addWeeks(todayMonday, (weekPager.currentPage - WEEK_CENTER).toLong())
  val monthAnchor = Periods.addMonths(todayMonth, (monthPager.currentPage - MONTH_CENTER).toLong())

  // 长按菜单的两个确认弹窗
  var reanalyzeTarget by remember { mutableStateOf<RecordDto?>(null) }
  var deleteTarget by remember { mutableStateOf<RecordDto?>(null) }
  var menuNotes by remember { mutableStateOf("") }

  val baseUrl by dayViewModel.baseUrl.collectAsStateWithLifecycle()
  val dayState by dayViewModel.state.collectAsStateWithLifecycle()
  val rangeState by rangeViewModel.state.collectAsStateWithLifecycle()
  val decisionsByDate by dayViewModel.decisionsByDate.collectAsStateWithLifecycle()
  val busy by dayViewModel.busy.collectAsStateWithLifecycle()
  val toast by dayViewModel.toast.collectAsStateWithLifecycle()
  val detailAnchor by dayViewModel.detailAnchor.collectAsStateWithLifecycle()
  val scrollTarget by dayViewModel.scrollTarget.collectAsStateWithLifecycle()

  val snackbarHostState = remember { SnackbarHostState() }

  // Calo 里补记/改/删成功、或 §8.6 轮询发现服务端有新数据，这里都要重拉
  val context = LocalContext.current
  val dataSignal = remember(context) { AppContainer.of(context).dataSignal }
  val dataTick by dataSignal.tick.collectAsStateWithLifecycle()
  LaunchedEffect(dataTick) {
    if (dataTick > 0) {
      // 新数据可能带新的 Luna 决策，角标要跟着更新
      dayViewModel.refreshDecisions()
      rangeViewModel.invalidate()
      dayViewModel.refresh()
    }
  }

  // 详情从「当前视图」的记录里查；区间数据按周/月分槽缓存，全部拼起来查最稳：
  // 在某一页点开详情后再滑走，原来的槽位还在，详情不会被误关。
  val activeRecords = remember(dayState.groups, rangeState.chunks) {
    (dayState.groups + rangeState.chunks.values.flatMap { it.groups })
      .flatMap { it.records }
      .distinctBy { it.assetId }
  }
  val detailRecord = detailAnchor?.let { anchor -> activeRecords.firstOrNull { it.assetId == anchor } }

  LaunchedEffect(toast) {
    toast?.let {
      // 详情是全屏 Dialog，SnackbarHost 会被它挡在后面看不见（2026-10-04 踩坑：
      // 在详情里重分析/删照片，列表确实更新了但用户什么提示都看不到）。
      // 详情打开期间改用系统 Toast——它是独立窗口层，压在 Dialog 上面。
      if (detailAnchor != null) {
        android.widget.Toast.makeText(context, it, android.widget.Toast.LENGTH_SHORT).show()
      } else {
        snackbarHostState.showSnackbar(it)
      }
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
    Row(
      modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
      verticalAlignment = Alignment.CenterVertically,
      horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
      SingleChoiceSegmentedButtonRow(modifier = Modifier.weight(1f)) {
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
      // 三个视图都要能进选择照片，所以放在这层而不是各自的标题栏里
      IconButton(onClick = { showPicker = true }) {
        Icon(Icons.Filled.Add, contentDescription = "选择照片")
      }
    }

    when (mode) {
      RecordsMode.Day -> {}
      RecordsMode.Week -> {
        ArrowHeader(
          title = if (Periods.isCurrentWeek(monday, today)) "本周" else Periods.weekLabel(monday),
          subtitle = Periods.weekLabel(monday),
          canGoForward = weekPager.currentPage < WEEK_CENTER,
          onPrev = { scope.launch { weekPager.animateScrollToPage(weekPager.currentPage - 1) } },
          onNext = { scope.launch { weekPager.animateScrollToPage(weekPager.currentPage + 1) } },
          onToday =
            if (Periods.isCurrentWeek(monday, today)) null
            else ({ scope.launch { weekPager.scrollToPage(WEEK_CENTER) } }),
        )
      }
      RecordsMode.Month -> {
        ArrowHeader(
          title = Periods.monthLabel(monthAnchor),
          subtitle = null,
          canGoForward = monthPager.currentPage < MONTH_CENTER,
          onPrev = { scope.launch { monthPager.animateScrollToPage(monthPager.currentPage - 1) } },
          onNext = { scope.launch { monthPager.animateScrollToPage(monthPager.currentPage + 1) } },
          onToday =
            if (Periods.isCurrentMonth(monthAnchor, today)) null
            else ({ scope.launch { monthPager.scrollToPage(MONTH_CENTER) } }),
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
            onReanalyze = { reanalyzeTarget = it },
            onDeleteMeal = { deleteTarget = it },
          )

        RecordsMode.Week ->
          HorizontalPager(state = weekPager, modifier = Modifier.fillMaxSize()) { page ->
            WeekView(
              viewModel = rangeViewModel,
              monday = Periods.addWeeks(todayMonday, (page - WEEK_CENTER).toLong()),
              today = today,
              baseUrl = baseUrl,
              decisionsByDate = decisionsByDate,
              onEnsureDecisions = dayViewModel::ensureDecisions,
              onOpenDetail = dayViewModel::openDetail,
              onReanalyze = { reanalyzeTarget = it },
              onDeleteMeal = { deleteTarget = it },
            )
          }

        RecordsMode.Month ->
          HorizontalPager(state = monthPager, modifier = Modifier.fillMaxSize().padding(horizontal = 8.dp)) { page ->
            MonthView(
              viewModel = rangeViewModel,
              monthAnchor = Periods.addMonths(todayMonth, (page - MONTH_CENTER).toLong()),
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
        modifier = Modifier.align(Alignment.BottomCenter),
      )
    }
  }

  detailRecord?.let { detailRecord ->
    MealDetailDialog(
      record = detailRecord,
      baseUrl = baseUrl,
      decisions = decisionsByDate[TimeFmt.dateOf(detailRecord.photoTime)].orEmpty(),
      busy = busy,
      onClose = dayViewModel::closeDetail,
      onDeleteMeal = {
        dayViewModel.delete(
          detailRecord.assetId,
          photoOnly = false,
          onSuccess = rangeViewModel::invalidate,
        )
      },
      onDeletePhoto = { assetId ->
        dayViewModel.delete(assetId, photoOnly = true, onSuccess = rangeViewModel::invalidate)
      },
      onReanalyze = { notes, done ->
        dayViewModel.reanalyze(
          detailRecord.assetId,
          notes,
          onSuccess = {
            rangeViewModel.invalidate()
            // 真正更新完才让详情关表单，失败时 notes 原样留在框里
            done()
          },
        )
      },
    )
  }

  // ── 长按菜单的确认弹窗 ────────────────────────────────────────

  reanalyzeTarget?.let { target ->
    AlertDialog(
      onDismissRequest = {
        if (!busy) {
          reanalyzeTarget = null
          menuNotes = ""
        }
      },
      title = { Text("重新分析") },
      text = {
        OutlinedTextField(
          value = menuNotes,
          onValueChange = { menuNotes = it },
          placeholder = { Text(REANALYZE_PLACEHOLDER) },
          minLines = 2,
          enabled = !busy,
        )
      },
      confirmButton = {
        TextButton(
          enabled = menuNotes.isNotBlank() && !busy,
          onClick = {
            dayViewModel.reanalyze(target.assetId, menuNotes, onSuccess = rangeViewModel::invalidate)
            reanalyzeTarget = null
            menuNotes = ""
          },
        ) {
          Text("确定")
        }
      },
      dismissButton = {
        TextButton(
          enabled = !busy,
          onClick = {
            reanalyzeTarget = null
            menuNotes = ""
          },
        ) {
          Text("取消")
        }
      },
    )
  }

  deleteTarget?.let { target ->
    AlertDialog(
      onDismissRequest = { if (!busy) deleteTarget = null },
      title = { Text("删除整餐？") },
      text = {
        Text(
          "「${target.meal.ifBlank { "未命名" }}」和它的照片都会被删除，照片之后不会再被同步。"
        )
      },
      confirmButton = {
        TextButton(
          enabled = !busy,
          onClick = {
            dayViewModel.delete(target.assetId, photoOnly = false, onSuccess = rangeViewModel::invalidate)
            deleteTarget = null
          },
        ) {
          Text("删除", color = MaterialTheme.colorScheme.error)
        }
      },
      dismissButton = {
        TextButton(enabled = !busy, onClick = { deleteTarget = null }) { Text("取消") }
      },
    )
  }

  if (showPicker) {
    PhotoPickerScreen(
      onDismiss = { showPicker = false },
      // 加完不关窗：可以接着选下一餐；时间轴在后台先刷新
      onAdded = {
        rangeViewModel.invalidate()
        dayViewModel.refresh()
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
      Icon(Icons.AutoMirrored.Filled.KeyboardArrowLeft, contentDescription = "上一页")
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
      Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = "下一页")
    }
  }
}
