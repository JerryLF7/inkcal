package com.jerrylf.inkcal.ui.calo

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jerrylf.inkcal.data.AppContainer
import com.jerrylf.inkcal.data.ChatMessageDto
import com.jerrylf.inkcal.data.ChatSessionDto
import com.jerrylf.inkcal.data.ErrorDto
import com.jerrylf.inkcal.data.ApiFactory
import com.jerrylf.inkcal.data.RecordDto
import com.jerrylf.inkcal.domain.ChatTools
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.decodeFromString
import retrofit2.HttpException

/** 删除确认卡的状态。**只存本地**，历史消息重开时重新显示为待确认（与网页版一致）。 */
enum class DeleteState { PENDING, CONFIRMED, CANCELLED }

/** 乐观追加的用户消息用负数 id，和服务端的正数 id 不会撞。 */
private const val OPTIMISTIC_ID = -1

data class ChatUiState(
  val loading: Boolean = true,
  val sending: Boolean = false,
  val sessionId: Int? = null,
  val messages: List<ChatMessageDto> = emptyList(),
  val sessions: List<ChatSessionDto> = emptyList(),
  val showSessions: Boolean = false,
  val error: String? = null,
  val draft: String = "",
  val deleteStates: Map<Int, DeleteState> = emptyMap(),
  val deletingIds: Set<Int> = emptySet(),
)

/**
 * Calo 聊天，对应 docs/android-app-spec.md §10。
 *
 * 两条硬规则：
 *  1. 新建会话是**惰性**的——点「＋」只清本地状态，不调 POST /api/chat/sessions，
 *     首条消息发送时 session_id 为 null，由服务端建（避免空会话占位）。
 *  2. 删除**绝不能**由 tool_log 触发——只有用户在确认卡上点「确认删除」才发
 *     DELETE /api/record（AGENTS §4 的安全契约）。
 */
class ChatViewModel(app: Application) : AndroidViewModel(app) {

  private val container = AppContainer.of(app)
  private val repo = container.repository
  private val store = container.settingsStore

  private val _state = MutableStateFlow(ChatUiState())
  val state: StateFlow<ChatUiState> = _state.asStateFlow()

  /** 聊天里的餐卡缩略图仍要经服务端代理取。 */
  val baseUrl: StateFlow<String> =
    store.baseUrl.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "")

  /** baseUrl 变了（换服务器）要重新载入。 */
  private var loadedBaseUrl: String? = null

  init {
    viewModelScope.launch {
      val base = store.currentBaseUrl()
      loadedBaseUrl = base
      val saved = store.currentChatSessionId()
      _state.update { it.copy(sessionId = saved) }
      loadMessages(saved)
      refreshSessions()
    }
  }

  // ── 会话 ───────────────────────────────────────────────────────

  /** 重新载入当前会话的消息（服务端给最新会话时也会回填 session_id）。 */
  fun loadMessages(sessionId: Int? = _state.value.sessionId) {
    viewModelScope.launch {
      _state.update { it.copy(loading = true) }
      try {
        val resp = repo.chatMessages(sessionId)
        _state.update {
          it.copy(
            loading = false,
            sessionId = resp.sessionId,
            messages = resp.messages,
            // 服务端回填的 id 也要落盘，否则下次进来又回到"最新会话"
            deleteStates = emptyMap(),
          )
        }
        if (resp.sessionId != sessionId) store.setChatSessionId(resp.sessionId)
      } catch (e: Exception) {
        _state.update { it.copy(loading = false, error = friendly(e)) }
      }
    }
  }

  fun refreshSessions() {
    viewModelScope.launch {
      runCatching { repo.chatSessions() }
        .onSuccess { list -> _state.update { it.copy(sessions = list) } }
    }
  }

  fun toggleSessions() = _state.update { it.copy(showSessions = !it.showSessions) }

  fun selectSession(id: Int) {
    viewModelScope.launch {
      store.setChatSessionId(id)
      _state.update { it.copy(sessionId = id, showSessions = false, messages = emptyList()) }
      loadMessages(id)
    }
  }

  /** 惰性新建：只清本地状态与保存的 id，不落库。 */
  fun newSession() {
    viewModelScope.launch {
      store.setChatSessionId(null)
      _state.update {
        it.copy(
          sessionId = null,
          messages = emptyList(),
          showSessions = false,
          deleteStates = emptyMap(),
          error = null,
        )
      }
    }
  }

  // ── 发送 ───────────────────────────────────────────────────────

  fun setDraft(text: String) = _state.update { it.copy(draft = text) }

  fun consumeError() = _state.update { it.copy(error = null) }

  fun send(text: String = _state.value.draft) {
    val message = text.trim()
    if (message.isEmpty() || _state.value.sending) return

    val optimistic = ChatMessageDto(id = OPTIMISTIC_ID, role = "user", content = message)
    _state.update {
      it.copy(sending = true, draft = "", error = null, messages = it.messages + optimistic)
    }

    val sessionId = _state.value.sessionId
    viewModelScope.launch {
      try {
        val resp = repo.chatSend(sessionId, message)
        if (!resp.ok && resp.reply.isBlank()) {
          // 502：保留 tool_log 让失败步骤也能看到，但正文用错误提示
          rollback(optimistic, message, resp.error ?: "发送失败，请重试")
          return@launch
        }
        val assistant =
          ChatMessageDto(
            id = OPTIMISTIC_ID - 1,
            role = "assistant",
            content = resp.reply,
            toolLog = resp.toolLog,
          )
        _state.update { it.copy(sending = false, messages = it.messages + assistant) }

        resp.sessionId?.let { sid ->
          if (sid != sessionId) store.setChatSessionId(sid)
          _state.update { it.copy(sessionId = sid) }
        }
        refreshSessions()

        // 只有真正写成功才联动刷新时间轴
        if (ChatTools.hasSuccessfulWrite(resp.toolLog)) {
          container.dataSignal.bump()
        }
      } catch (e: Exception) {
        rollback(optimistic, message, messageFor(e))
      }
    }
  }

  private fun rollback(optimistic: ChatMessageDto, text: String, error: String) {
    _state.update {
      it.copy(
        sending = false,
        messages = it.messages.filterNot { m -> m.id == optimistic.id },
        draft = text,
        error = error,
      )
    }
  }

  private fun messageFor(e: Exception): String =
    if (e is HttpException) {
      runCatching {
          val body = e.response()?.errorBody()?.string().orEmpty()
          ApiFactory.json.decodeFromString<ErrorDto>(body).error.ifBlank { "HTTP ${e.code()}" }
        }
        .getOrDefault("HTTP ${e.code()}")
    } else {
      "网络异常，发送失败"
    }

  // ── 删除确认卡 ─────────────────────────────────────────────────

  fun cancelDelete(messageId: Int) =
    _state.update { it.copy(deleteStates = it.deleteStates + (messageId to DeleteState.CANCELLED)) }

  /**
   * 只有这里会真的发删除请求。**别把它接到 tool_log 上**——那等于让模型直接删数据。
   */
  fun confirmDelete(messageId: Int, assetId: String) {
    if (assetId.isBlank() || messageId in _state.value.deletingIds) return
    _state.update { it.copy(deletingIds = it.deletingIds + messageId) }
    viewModelScope.launch {
      try {
        repo.deleteRecord(assetId, mode = "meal")
        _state.update {
          it.copy(
            deletingIds = it.deletingIds - messageId,
            deleteStates = it.deleteStates + (messageId to DeleteState.CONFIRMED),
          )
        }
        container.dataSignal.bump()
      } catch (e: Exception) {
        // 卡片保持可重试
        _state.update { it.copy(deletingIds = it.deletingIds - messageId, error = "删除失败：${messageFor(e)}") }
      }
    }
  }

  private fun friendly(e: Exception) = e.message ?: e.javaClass.simpleName

  // ── 聊天里的餐卡 → §8.4 详情 ───────────────────────────────────

  private val _detailRecord = MutableStateFlow<RecordDto?>(null)
  val detailRecord: StateFlow<RecordDto?> = _detailRecord.asStateFlow()

  private val _busy = MutableStateFlow(false)
  val busy: StateFlow<Boolean> = _busy.asStateFlow()

  fun openDetail(record: RecordDto) {
    _detailRecord.value = record
  }

  fun closeDetail() {
    _detailRecord.value = null
  }

  /**
   * 详情里的删除。走的是和记录页同一条业务路径（`DELETE /api/record`），
   * 只是这里只更新聊天的状态。
   */
  fun deleteFromDetail(assetId: String, photoOnly: Boolean) {
    if (_busy.value) return
    viewModelScope.launch {
      _busy.value = true
      try {
        repo.deleteRecord(assetId, if (photoOnly) "photo" else "meal")
        _detailRecord.value = null
        container.dataSignal.bump()
        _state.update { it.copy(error = "已删除记录") }
      } catch (e: Exception) {
        _state.update { it.copy(error = "删除失败：${messageFor(e)}") }
      }
      _busy.value = false
    }
  }

  fun reanalyzeFromDetail(assetId: String, notes: String) {
    if (_busy.value) return
    viewModelScope.launch {
      _busy.value = true
      try {
        repo.reanalyze(assetId, notes)
        _detailRecord.value = null
        container.dataSignal.bump()
        _state.update { it.copy(error = "已重新分析") }
      } catch (e: Exception) {
        _state.update { it.copy(error = "重新分析失败：${messageFor(e)}") }
      }
      _busy.value = false
    }
  }
}
