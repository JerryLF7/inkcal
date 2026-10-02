package com.jerrylf.inkcal.ui.picker

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import coil3.compose.AsyncImage
import com.jerrylf.inkcal.data.AlbumDayDto
import com.jerrylf.inkcal.data.AlbumPhotoDto
import com.jerrylf.inkcal.domain.ImageUrl
import com.jerrylf.inkcal.domain.TimeFmt

private const val COLUMNS = 3

/**
 * 选择照片 / 本地上传，对应 docs/android-app-spec.md §8.5。
 *
 * 相册按天分页（服务端 7 天/页），SigLIP2 判为非食物的照片置灰不可选；
 * 「本地图片」走系统照片选择器，交给服务端读 EXIF 定日期。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PhotoPickerScreen(
  onDismiss: () -> Unit,
  onAdded: () -> Unit,
  viewModel: PickerViewModel = viewModel(),
) {
  val state by viewModel.state.collectAsStateWithLifecycle()
  val baseUrl by viewModel.baseUrl.collectAsStateWithLifecycle()
  val snackbarHostState = remember { SnackbarHostState() }
  var showDatePicker by remember { mutableStateOf(false) }

  val uploadLauncher =
    rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
      if (uri != null) viewModel.upload(uri, onAdded)
    }

  LaunchedEffect(state.message) {
    state.message?.let {
      snackbarHostState.showSnackbar(it)
      viewModel.consumeMessage()
    }
  }
  LaunchedEffect(state.error) {
    state.error?.let {
      snackbarHostState.showSnackbar(it)
      viewModel.consumeError()
    }
  }

  Dialog(
    onDismissRequest = onDismiss,
    properties = DialogProperties(usePlatformDefaultWidth = false),
  ) {
    Surface(modifier = Modifier.fillMaxSize()) {
      Column(modifier = Modifier.fillMaxSize()) {
        TopAppBar(
          title = { Text("选择照片") },
          navigationIcon = {
            IconButton(onClick = onDismiss) {
              Icon(Icons.Filled.Close, contentDescription = "关闭")
            }
          },
          actions = {
            TextButton(
              onClick = {
                uploadLauncher.launch(
                  PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                )
              },
              enabled = !state.submitting,
            ) {
              Text("本地图片")
            }
          },
        )

        Text(
          text = "已选 ${state.selectedCount} / $MAX_SELECTION" +
            if (state.overLimit) "（已达上限）" else " · 灰掉的是已判定为非食物的照片",
          style = MaterialTheme.typography.labelSmall,
          color = MaterialTheme.colorScheme.onSurfaceVariant,
          modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
        )

        Box(modifier = Modifier.weight(1f)) {
          LazyColumn(modifier = Modifier.fillMaxSize()) {
            state.days.forEach { day ->
              item(key = "day-${day.date}") {
                DayHeader(day)
                LaunchedEffect(day.date) { /* 占位：日期头进入可见区 */ }
              }
              items(day.photos.chunked(COLUMNS), key = { row -> "row-${row.first().assetId}" }) { row ->
                Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 2.dp)) {
                  row.forEach { photo ->
                    PhotoCell(
                      photo = photo,
                      baseUrl = baseUrl,
                      selected = photo.assetId in state.selected,
                      onToggle = { viewModel.toggle(photo) },
                      modifier = Modifier.weight(1f),
                    )
                  }
                  repeat(COLUMNS - row.size) { Box(modifier = Modifier.weight(1f)) {} }
                }
              }
            }

            item(key = "footer") {
              // 只在页脚被组合出来（即滚到底）时才拉下一页。**不能**把 days.size 当 key，
              // 否则每次追加都会重新触发，一路把整本相册拉完。
              LaunchedEffect(Unit) { viewModel.loadMore() }
              Box(
                modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp),
                contentAlignment = Alignment.Center,
              ) {
                when {
                  state.atEnd ->
                    Text(
                      "没有更多未处理的照片了",
                      style = MaterialTheme.typography.labelSmall,
                      color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                  state.loading -> CircularProgressIndicator(modifier = Modifier.size(24.dp))
                  // 内容不足一屏时页脚会一直可见、LaunchedEffect 不会重跑，留个手动出口
                  else -> TextButton(onClick = viewModel::loadMore) { Text("加载更多") }
                }
              }
            }
          }

          SnackbarHost(
            hostState = snackbarHostState,
            modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 72.dp),
          )
        }

        HorizontalDivider()
        Button(
          onClick = { viewModel.submit(onAdded) },
          enabled = state.selectedCount > 0 && !state.submitting,
          modifier = Modifier.fillMaxWidth().padding(16.dp),
        ) {
          Text(if (state.submitting) "分析中…" else "加入记录（${state.selectedCount}）")
        }

        if (state.submitting) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
      }
    }
  }

  // 本地图片没读到 EXIF：让用户确认或改期
  state.pendingDateFix?.let { pending ->
    AlertDialog(
      onDismissRequest = { viewModel.keepDate(onAdded) },
      title = { Text("没有拍摄时间") },
      text = { Text("这张图没有 EXIF 拍摄时间，暂时记在 ${pending.date}。要改到别的日期吗？") },
      confirmButton = {
        TextButton(onClick = { showDatePicker = true }) { Text("改日期") }
      },
      dismissButton = {
        TextButton(onClick = { viewModel.keepDate(onAdded) }) { Text("保持当天") }
      },
    )
  }

  if (showDatePicker) {
    val pickerState = rememberDatePickerState(initialSelectedDateMillis = TimeFmt.pickerMillis(state.pendingDateFix?.date ?: ""))
    DatePickerDialog(
      onDismissRequest = { showDatePicker = false },
      confirmButton = {
        TextButton(
          onClick = {
            pickerState.selectedDateMillis?.let { viewModel.fixDate(TimeFmt.dateFromPickerMillis(it), onAdded) }
            showDatePicker = false
          }
        ) {
          Text("确定")
        }
      },
      dismissButton = { TextButton(onClick = { showDatePicker = false }) { Text("取消") } },
    ) {
      DatePicker(state = pickerState)
    }
  }
}

@Composable
private fun DayHeader(day: AlbumDayDto) {
  Row(
    modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
    verticalAlignment = Alignment.CenterVertically,
  ) {
    Text(
      text = "${TimeFmt.shortDate(day.date)} ${TimeFmt.weekday(day.date)}",
      style = MaterialTheme.typography.labelLarge,
      fontWeight = FontWeight.SemiBold,
      modifier = Modifier.weight(1f),
    )
    val selectable = day.photos.count { !it.classifiedNonFood }
    Text(
      text = if (selectable == 0) "均不可选" else "$selectable 张可选",
      style = MaterialTheme.typography.labelSmall,
      color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
  }
}

@Composable
private fun PhotoCell(
  photo: AlbumPhotoDto,
  baseUrl: String,
  selected: Boolean,
  onToggle: () -> Unit,
  modifier: Modifier = Modifier,
) {
  val disabled = photo.classifiedNonFood
  Box(
    modifier =
      modifier
        .padding(2.dp)
        .aspectRatio(1f)
        .clip(RoundedCornerShape(6.dp))
        .background(MaterialTheme.colorScheme.surfaceVariant)
        .then(if (disabled) Modifier else Modifier.clickable(onClick = onToggle))
        .then(
          if (selected) {
            Modifier.border(3.dp, MaterialTheme.colorScheme.primary, RoundedCornerShape(6.dp))
          } else {
            Modifier
          }
        )
        .alpha(if (disabled) 0.35f else 1f),
    contentAlignment = Alignment.Center,
  ) {
    AsyncImage(
      model = ImageUrl.thumbnail(baseUrl, photo.thumbnailUrl),
      contentDescription = null,
      contentScale = ContentScale.Crop,
      modifier = Modifier.fillMaxSize(),
    )
    if (photo.photoTime.length >= 16) {
      Text(
        text = TimeFmt.clock(photo.photoTime),
        style = MaterialTheme.typography.labelSmall,
        color = Color.White,
        modifier =
          Modifier.align(Alignment.BottomEnd)
            .padding(4.dp)
            .background(Color.Black.copy(alpha = 0.45f), RoundedCornerShape(4.dp))
            .padding(horizontal = 4.dp),
      )
    }
    if (selected) {
      Box(
        modifier =
          Modifier.align(Alignment.TopEnd)
            .padding(4.dp)
            .size(20.dp)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.primary),
        contentAlignment = Alignment.Center,
      ) {
        Text("✓", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onPrimary)
      }
    }
    if (disabled) {
      Text(
        text = "非食物",
        style = MaterialTheme.typography.labelSmall,
        color = Color.White,
        modifier =
          Modifier.background(Color.Black.copy(alpha = 0.5f), RoundedCornerShape(4.dp))
            .padding(horizontal = 4.dp, vertical = 1.dp),
      )
    }
  }
}
