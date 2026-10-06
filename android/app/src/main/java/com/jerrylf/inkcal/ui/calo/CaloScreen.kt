package com.jerrylf.inkcal.ui.calo

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.AssistChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jerrylf.inkcal.data.ChatMessageDto
import com.jerrylf.inkcal.data.ChatSessionDto
import com.jerrylf.inkcal.ui.records.MealDetailDialog

private val SUGGESTIONS =
  listOf(
    "今天摄入了多少热量？",
    "记一下昨天下午吃了包薯片",
    "帮我查查昨天的午餐",
    "最近吃过什么高蛋白食物？",
  )

/**
 * Calo 聊天页，对应 docs/android-app-spec.md §10。
 *
 * 写操作成功后通过 `AppContainer.dataSignal` 广播，记录页订阅后自己重拉。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CaloScreen(viewModel: ChatViewModel = viewModel()) {
  val state by viewModel.state.collectAsStateWithLifecycle()
  val baseUrl by viewModel.baseUrl.collectAsStateWithLifecycle()
  val detailRecord by viewModel.detailRecord.collectAsStateWithLifecycle()
  val busy by viewModel.busy.collectAsStateWithLifecycle()

  val listState = rememberLazyListState()
  val snackbarHostState = remember { SnackbarHostState() }
  var input by remember { mutableStateOf("") }

  LaunchedEffect(state.error) {
    state.error?.let {
      snackbarHostState.showSnackbar(it)
      viewModel.consumeError()
    }
  }

  // 发送失败时把文本放回输入框
  LaunchedEffect(state.draft) {
    if (state.draft.isNotEmpty() && input.isEmpty()) input = state.draft
  }

  // 新消息滚到底
  LaunchedEffect(state.messages.size, state.sending) {
    if (state.messages.isNotEmpty()) listState.animateScrollToItem(state.messages.lastIndex)
  }

  Column(modifier = Modifier.fillMaxSize().imePadding()) {
    // 外层 MainScaffold 已消化状态栏 inset，这里必须清零，否则 TopAppBar 会再垫一次
    TopAppBar(
      windowInsets = WindowInsets(0, 0, 0, 0),
      title = { Text("Calo") },
      actions = {
        IconButton(onClick = viewModel::toggleSessions) {
          Icon(Icons.AutoMirrored.Filled.List, contentDescription = "历史会话")
        }
        IconButton(onClick = viewModel::newSession) {
          Icon(Icons.Filled.Add, contentDescription = "新建会话")
        }
      },
    )

    Box(modifier = Modifier.weight(1f)) {
      if (state.messages.isEmpty() && !state.loading) {
        EmptyState(onPick = { viewModel.send(it) }, enabled = !state.sending)
      } else {
        LazyColumn(
          state = listState,
          modifier = Modifier.fillMaxSize().padding(horizontal = 12.dp),
          verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
          items(state.messages, key = { it.id }) { message ->
            if (message.role == "user") {
              UserBubble(message.content)
            } else {
              AssistantMessage(
                message = message,
                baseUrl = baseUrl,
                deleteState = state.deleteStates[message.id],
                deleting = message.id in state.deletingIds,
                onOpenRecord = viewModel::openDetail,
                onConfirmDelete = {
                  val assetId =
                    ChatToolsDeleteAssetId(message) ?: return@AssistantMessage
                  viewModel.confirmDelete(message.id, assetId)
                },
                onCancelDelete = { viewModel.cancelDelete(message.id) },
              )
            }
          }
          if (state.sending) {
            item(key = "thinking") {
              Text(
                text = "Calo 正在思考…",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(vertical = 8.dp),
              )
            }
          }
          if (state.loading) {
            item(key = "loading") { CircularProgressIndicator() }
          }
        }
      }

      SnackbarHost(
        hostState = snackbarHostState,
        modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 8.dp),
      )
    }

    HorizontalDivider()
    Row(
      modifier = Modifier.fillMaxWidth().padding(8.dp),
      verticalAlignment = Alignment.CenterVertically,
      horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
      OutlinedTextField(
        value = input,
        onValueChange = { input = it },
        placeholder = { Text("问 Calo 点什么…") },
        enabled = !state.sending,
        maxLines = 4,
        modifier = Modifier.weight(1f),
      )
      IconButton(
        onClick = {
          val text = input
          input = ""
          viewModel.send(text)
        },
        enabled = input.isNotBlank() && !state.sending,
      ) {
        Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "发送")
      }
    }
  }

  if (state.showSessions) {
    ModalBottomSheet(onDismissRequest = viewModel::toggleSessions) {
      SessionList(state.sessions, state.sessionId, viewModel::selectSession)
    }
  }

  detailRecord?.let { record ->
    MealDetailDialog(
      record = record,
      baseUrl = baseUrl,
      decisions = emptyList(),
      busy = busy,
      onClose = viewModel::closeDetail,
      onDeleteMeal = { viewModel.deleteFromDetail(record.assetId, photoOnly = false) },
      onDeletePhoto = { assetId -> viewModel.deleteFromDetail(assetId, photoOnly = true) },
      onReanalyze = { notes, done ->
        // 成功后整条详情会关闭（见 reanalyzeFromDetail），done 只是让表单同步复位
        viewModel.reanalyzeFromDetail(record.assetId, notes, onSuccess = done)
      },
    )
  }
}

/** 删除确认卡要删的是哪条记录——从该消息的 tool_log 里取。 */
private fun ChatToolsDeleteAssetId(message: ChatMessageDto): String? =
  com.jerrylf.inkcal.domain.ChatTools.artifacts(message.toolLog)
    .firstOrNull { it.kind == com.jerrylf.inkcal.domain.ArtifactKind.DELETE_CONFIRM }
    ?.confirmAssetId

@Composable
private fun UserBubble(text: String) {
  Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
    Surface(
      color = MaterialTheme.colorScheme.primaryContainer,
      shape = RoundedCornerShape(12.dp),
      modifier = Modifier.padding(vertical = 4.dp),
    ) {
      Text(text = text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(10.dp))
    }
  }
}

@Composable
private fun EmptyState(onPick: (String) -> Unit, enabled: Boolean) {
  Column(
    modifier = Modifier.fillMaxSize().padding(24.dp),
    verticalArrangement = Arrangement.spacedBy(12.dp),
    horizontalAlignment = Alignment.CenterHorizontally,
  ) {
    Text("我是 Calo", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
    Text(
      text = "你的饮食助手。可以问我吃了多少、帮我补记一餐、改错的记录，或者查某天的摄入。",
      style = MaterialTheme.typography.bodyMedium,
      color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    SUGGESTIONS.forEach { text ->
      AssistChip(onClick = { if (enabled) onPick(text) }, label = { Text(text) })
    }
  }
}

@Composable
private fun SessionList(
  sessions: List<ChatSessionDto>,
  currentId: Int?,
  onSelect: (Int) -> Unit,
) {
  Column(modifier = Modifier.fillMaxWidth().padding(bottom = 24.dp)) {
    Text(
      text = "历史会话",
      style = MaterialTheme.typography.titleMedium,
      modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
    )
    if (sessions.isEmpty()) {
      Text(
        text = "还没有会话",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(16.dp),
      )
    }
    sessions.forEach { session ->
      TextButton(
        onClick = { onSelect(session.id) },
        modifier = Modifier.fillMaxWidth(),
      ) {
        Column(modifier = Modifier.fillMaxWidth()) {
          Text(
            text = session.title.ifBlank { "新会话" },
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = if (session.id == currentId) FontWeight.Bold else FontWeight.Normal,
          )
          Text(
            // 时间取 last_active 或 created_at 的前 16 位，T 换空格
            text = (session.lastActive ?: session.createdAt).take(16).replace('T', ' '),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
          )
        }
      }
    }
  }
}
