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
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.domain.Decisions
import com.jerrylf.inkcal.domain.TimeFmt

/**
 * 日视图时间轴，对应 docs/android-app-spec.md §8.1。
 *
 * 详情弹窗、Snackbar、写操作都在 [RecordsTab] 那一层——周/月视图的卡片也要能进详情，
 * 放在这里会让三个视图各需一份。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecordsScreen(
  viewModel: RecordsViewModel,
  scrollTarget: String?,
  onScrollHandled: () -> Unit,
  onOpenDetail: (RecordDto) -> Unit,
  onReanalyze: (RecordDto) -> Unit,
  onDeleteMeal: (RecordDto) -> Unit,
) {
  val state by viewModel.state.collectAsStateWithLifecycle()
  val bmr by viewModel.bmr.collectAsStateWithLifecycle()
  val baseUrl by viewModel.baseUrl.collectAsStateWithLifecycle()
  val decisionsByDate by viewModel.decisionsByDate.collectAsStateWithLifecycle()

  val listState = rememberLazyListState()
  val today = remember { TimeFmt.hktToday() }

  // 每个日期头在扁平列表里的下标，月视图跳转时按它定位
  val headerDates: List<Pair<Int, String>> =
    remember(state.groups) {
      var index = 0
      state.groups.map { group ->
        val at = index
        index += 1 + group.records.size
        at to group.date
      }
    }
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

  // 月视图点某天后滚到那一天。目标日期可能没有记录（点了空白天），
  // 那就退到不晚于它的最近一天；headerDates 是日期倒序，第一个命中的就是最近的。
  LaunchedEffect(scrollTarget, headerDates) {
    val target = scrollTarget ?: return@LaunchedEffect
    val index = headerDates.firstOrNull { it.second <= target }?.first ?: return@LaunchedEffect
    listState.scrollToItem(index)
    onScrollHandled()
  }

  Column(modifier = Modifier.fillMaxSize()) {
    // 没有标题栏（2026-10-04 拍板）：原先顶栏显示的日期与吸顶 DateSeparator 恒等——
    // 两者都取"首个可见项所属的日期组"，而 stickyHeader 保证只要该组还有卡片可见、
    // 那行日期就钉在顶部。分隔线还多带 kcal / PCF / 缺口 chip，所以顶栏纯冗余，
    // 删掉后列表直接顶到状态栏下方，也多出一段竖向空间。
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
                  MealCardWithMenu(
                    record = record,
                    baseUrl = baseUrl,
                    hasDecision = Decisions.forRecord(record, dayDecisions).isNotEmpty(),
                    onOpenDetail = { onOpenDetail(record) },
                    onReanalyze = { onReanalyze(record) },
                    onDeleteMeal = { onDeleteMeal(record) },
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
    }
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
