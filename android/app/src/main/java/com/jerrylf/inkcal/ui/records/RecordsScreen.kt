package com.jerrylf.inkcal.ui.records

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jerrylf.inkcal.domain.TimeFmt

/** 日视图时间轴，对应 docs/android-app-spec.md §8.1。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecordsScreen(viewModel: RecordsViewModel = viewModel()) {
  val state by viewModel.state.collectAsStateWithLifecycle()
  val bmr by viewModel.bmr.collectAsStateWithLifecycle()
  val baseUrl by viewModel.baseUrl.collectAsStateWithLifecycle()
  val listState = rememberLazyListState()
  val today = remember { TimeFmt.hktToday() }

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

    when {
      state.groups.isEmpty() && state.loading ->
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
          CircularProgressIndicator()
        }

      state.groups.isEmpty() && state.error == null ->
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
          Text(
            text = "还没有记录。拍照备份后会自动入库。",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
          )
        }

      else ->
        LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
          state.error?.let { message ->
            item(key = "error") {
              ErrorBanner(message = message, onRetry = viewModel::refresh)
            }
          }

          state.groups.forEach { group ->
            stickyHeader(key = "header-${group.date}") {
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
                modifier = Modifier.padding(horizontal = 4.dp, vertical = 3.dp),
              )
            }
          }

          if (state.loading) {
            item(key = "loading") {
              LinearProgressIndicator(
                modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)
              )
            }
          }
          if (state.atEnd) {
            item(key = "end") {
              Text(
                text = "已经是最早的记录",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp),
              )
            }
          }
        }
    }
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
