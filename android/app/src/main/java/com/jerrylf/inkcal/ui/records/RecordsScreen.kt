package com.jerrylf.inkcal.ui.records

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyItemScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jerrylf.inkcal.domain.Decisions
import com.jerrylf.inkcal.domain.TimeFmt

/** 日视图时间轴，对应 docs/android-app-spec.md §8.1；详情见 §8.4。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecordsScreen(viewModel: RecordsViewModel = viewModel()) {
  val state by viewModel.state.collectAsStateWithLifecycle()
  val bmr by viewModel.bmr.collectAsStateWithLifecycle()
  val baseUrl by viewModel.baseUrl.collectAsStateWithLifecycle()
  val detailAnchor by viewModel.detailAnchor.collectAsStateWithLifecycle()
  val decisionsByDate by viewModel.decisionsByDate.collectAsStateWithLifecycle()
  val busy by viewModel.busy.collectAsStateWithLifecycle()
  val toast by viewModel.toast.collectAsStateWithLifecycle()

  val listState = rememberLazyListState()
  val snackbarHostState = remember { SnackbarHostState() }
  val today = remember { TimeFmt.hktToday() }

  val allRecords = remember(state.groups) { state.groups.flatMap { it.records } }

  // 详情渲染的就是列表状态里的那份记录，所以写操作后重拉列表，详情自动跟着变
  val detailRecord = detailAnchor?.let { anchor -> allRecords.firstOrNull { it.assetId == anchor } }

  LaunchedEffect(toast) {
    toast?.let {
      snackbarHostState.showSnackbar(it)
      viewModel.consumeToast()
    }
  }

  // 组没了（整餐被删、或单张移除后只剩这张）就收起详情。
  // busy 期间不判：单张移除会把锚点切到晋升的新主行，那一刻它还没出现在列表里。
  LaunchedEffect(detailAnchor, allRecords, busy) {
    if (!busy && detailAnchor != null && detailRecord == null && allRecords.isNotEmpty()) {
      viewModel.closeDetail()
    }
  }

  // 每个日期头在扁平列表里的下标，用来把「第一个可见项」映射回日期
  val headerDates: List<Pair<Int, String>> =
    remember(state.groups) {
      var index = 0
      state.groups.map { group ->
        val at = index
        index += 1 + group.records.size
        at to group.date
      }
    }
  val topDate = headerDates.lastOrNull { it.first <= listState.firstVisibleItemIndex }?.second

  // 触底前 2 项就开始拉更早的分片
  val nearEnd by remember {
    derivedStateOf {
      val info = listState.layoutInfo
      val last = info.visibleItemsInfo.lastOrNull()?.index ?: return@derivedStateOf false
      last >= info.totalItemsCount - 2
    }
  }
  LaunchedEffect(nearEnd, state.atEnd, state.groups.size) {
    if (nearEnd && !state.atEnd && state.groups.isNotEmpty()) viewModel.loadMore()
  }

  Column(modifier = Modifier.fillMaxSize()) {
    TopAppBar(
      title = {
        Column {
          Text(
            text =
              when {
                topDate == null -> "记录"
                topDate == today -> "今天 · ${TimeFmt.shortDate(today)}"
                else -> TimeFmt.shortDate(topDate)
              },
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
          )
          if (topDate != null) {
            Text(
              text = TimeFmt.weekday(topDate),
              style = MaterialTheme.typography.labelSmall,
              color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
          }
        }
      },
    )

    Box(modifier = Modifier.weight(1f)) {
      PullToRefreshBox(
        isRefreshing = state.refreshing,
        onRefresh = viewModel::refresh,
        modifier = Modifier.fillMaxSize(),
      ) {
        LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
          state.error?.let { message ->
            item(key = "error") {
              ErrorBanner(message = message, onRetry = viewModel::refresh)
            }
          }

          when {
            state.groups.isEmpty() && state.initialLoading ->
              item(key = "initial-loading") {
                CenteredMessage { CircularProgressIndicator() }
              }

            state.groups.isEmpty() ->
              // 空态也放进列表，否则没数据时下拉刷新没法触发
              item(key = "empty") {
                CenteredMessage {
                  Text(
                    text = "还没有记录。\n拍照备份后会自动入库，也可以下拉刷新。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                  )
                }
              }

            else ->
              state.groups.forEach { group ->
                val dayDecisions = decisionsByDate[group.date].orEmpty()
                stickyHeader(key = "header-${group.date}") {
                  // 滚到这天就去取它的决策（每天只请求一次），供卡片角标与详情块使用
                  LaunchedEffect(group.date) { viewModel.ensureDecisions(group.date) }
                  DateSeparator(
                    date = group.date,
                    kcal = group.kcal,
                    protein = group.protein,
                    carbs = group.carbs,
                    fat = group.fat,
                    bmr = bmr,
                    activeKcal = state.burns[group.date]?.activeKcal,
                    isToday = group.date == today,
                  )
                }
                items(group.records, key = { it.assetId }) { record ->
                  MealCard(
                    record = record,
                    baseUrl = baseUrl,
                    hasDecision = Decisions.forRecord(record, dayDecisions).isNotEmpty(),
                    onClick = { viewModel.openDetail(record) },
                    modifier = Modifier.padding(horizontal = 4.dp, vertical = 3.dp),
                  )
                }
              }
          }

          if (state.loadingMore) {
            item(key = "loading-more") {
              LinearProgressIndicator(modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp))
            }
          }
          if (state.atEnd && state.groups.isNotEmpty()) {
            item(key = "end") {
              Text(
                text = "已经是最早的记录",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp),
              )
            }
          }
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
      onClose = viewModel::closeDetail,
      onDeleteMeal = { viewModel.delete(detailRecord.assetId, photoOnly = false) },
      onDeletePhoto = { assetId -> viewModel.delete(assetId, photoOnly = true) },
      onReanalyze = { notes -> viewModel.reanalyze(detailRecord.assetId, notes) },
    )
  }
}

/** 撑满视口并居中，用于 loading / 空态这类占位。 */
@Composable
private fun LazyItemScope.CenteredMessage(content: @Composable () -> Unit) {
  Box(
    modifier = Modifier.fillParentMaxSize(),
    contentAlignment = Alignment.Center,
  ) {
    content()
  }
}

/** 拉取失败时不清空已有数据，只在列表顶部提示并给个重试。 */
@Composable
private fun ErrorBanner(message: String, onRetry: () -> Unit) {
  Row(
    modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 4.dp),
    horizontalArrangement = Arrangement.spacedBy(8.dp),
    verticalAlignment = Alignment.CenterVertically,
  ) {
    Text(
      text = message,
      style = MaterialTheme.typography.labelSmall,
      color = MaterialTheme.colorScheme.error,
      modifier = Modifier.weight(1f),
    )
    TextButton(onClick = onRetry) { Text("重试") }
  }
}
