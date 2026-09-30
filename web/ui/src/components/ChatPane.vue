<script setup>
import { ref, computed, nextTick, onMounted } from 'vue';
import { marked } from 'marked';
import ToolSteps from './ToolSteps.vue';
import ChatArtifact from './ChatArtifact.vue';
import SessionDrawer from './SessionDrawer.vue';
import { API } from '../utils/format.js';
import { touch, toast } from '../store.js';

marked.setOptions({
  breaks: true,
  gfm: true,
});

function renderMarkdown(text) {
  if (!text) return '';
  return marked.parse(text);
}

defineProps({
  isDesktop: { type: Boolean, default: false },
  chatCollapsed: { type: Boolean, default: false },
});

const emit = defineEmits(['toggle-chat', 'open']);

const scrollRef = ref(null);
const inputRef = ref(null);

const currentSessionId = ref(null);
const sessions = ref([]);
const messages = ref([]);
const loading = ref(false);
const sending = ref(false);
const inputText = ref('');

// 侧拉状态（聊天窗口设置已迁移至设置 Tab）
const sessionsDrawerOpen = ref(false);

const currentSessionTitle = computed(() =>
  sessions.value.find(s => s.id === currentSessionId.value)?.title || '');

// 快速提示语（无消息时展示）
const promptChips = [
  '今天摄入了多少热量？',
  '记一下昨天下午吃了包薯片',
  '帮我查查昨天的午餐',
  '最近吃过什么高蛋白食物？',
];

function scrollToBottom(smooth = false) {
  nextTick(() => {
    if (!scrollRef.value) return;
    scrollRef.value.scrollTo({
      top: scrollRef.value.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    });
  });
}

// ── 会话与消息管理 ──────────────────────────────────────────
const STORAGE_KEY_SESSION = 'inkcal_chat_session_id';

async function loadSessions() {
  try {
    const res = await fetch(`${API}/api/chat/sessions`);
    if (!res.ok) return;
    const data = await res.json();
    sessions.value = data.sessions || [];
  } catch (e) {
    console.error('Failed to load chat sessions:', e);
  }
}

async function loadMessages(sessionId = null) {
  loading.value = true;
  try {
    const saved = localStorage.getItem(STORAGE_KEY_SESSION);
    const targetId = sessionId !== null ? sessionId : (saved ? Number(saved) : null);
    const url = targetId
      ? `${API}/api/chat/messages?session_id=${targetId}`
      : `${API}/api/chat/messages`;
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    currentSessionId.value = data.session_id || null;
    if (currentSessionId.value) {
      localStorage.setItem(STORAGE_KEY_SESSION, String(currentSessionId.value));
    } else {
      localStorage.removeItem(STORAGE_KEY_SESSION);
    }
    messages.value = data.messages || [];
    scrollToBottom(false);
  } catch (e) {
    console.error('Failed to load messages:', e);
  } finally {
    loading.value = false;
  }
}

async function selectSession(sid) {
  if (sid === currentSessionId.value) {
    sessionsDrawerOpen.value = false;
    return;
  }
  sessionsDrawerOpen.value = false;
  await loadMessages(sid);
}

function createNewSession() {
  // 惰性新建：不往后端塞空 session 占位，只重置前端会话与本地消息
  currentSessionId.value = null;
  localStorage.removeItem(STORAGE_KEY_SESSION);
  messages.value = [];
  sessionsDrawerOpen.value = false;
  toast('已开启新会话');
  nextTick(() => inputRef.value?.focus());
}

// ── 消息发送 ───────────────────────────────────────────────
async function submitMessage() {
  const text = inputText.value.trim();
  if (!text || sending.value) return;

  const tempId = 'temp-' + Date.now();
  const userMsg = {
    id: tempId,
    role: 'user',
    content: text,
    created_at: new Date().toISOString(),
  };

  messages.value.push(userMsg);
  inputText.value = '';
  sending.value = true;
  scrollToBottom(true);

  try {
    const res = await fetch(`${API}/api/chat/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: currentSessionId.value,
        message: text,
      }),
    });

    const data = await res.json();

    if (!res.ok || !data.ok) {
      toast(data.error || '发送失败，请重试', 'error');
      inputText.value = text; // 恢复用户输入
      // 移除未成功的乐观消息
      const idx = messages.value.findIndex(m => m.id === tempId);
      if (idx !== -1) messages.value.splice(idx, 1);
      return;
    }

    currentSessionId.value = data.session_id;
    if (data.session_id) {
      localStorage.setItem(STORAGE_KEY_SESSION, String(data.session_id));
    }

    messages.value.push({
      id: 'reply-' + Date.now(),
      role: 'assistant',
      content: data.reply || '',
      tool_log: data.tool_log || [],
    });

    // 若工具执行了写操作（新增/修改/重分析），通知全局刷新视图
    const wroteData = (data.tool_log || []).some(
      t => (t.name === 'add_record' || t.name === 'edit_record' || t.name === 'reanalyze_record') && t.result?.ok
    );
    if (wroteData) {
      touch();
    }

    // 更新会话列表标题
    await loadSessions();
    scrollToBottom(true);
  } catch (e) {
    toast('网络异常，发送失败', 'error');
    inputText.value = text;
    const idx = messages.value.findIndex(m => m.id === tempId);
    if (idx !== -1) messages.value.splice(idx, 1);
  } finally {
    sending.value = false;
    nextTick(() => inputRef.value?.focus());
  }
}

function sendPrompt(prompt) {
  inputText.value = prompt;
  submitMessage();
}

onMounted(async () => {
  await loadSessions();
  await loadMessages();
});
</script>

<template>
  <section class="pane chat-pane">
    <!-- 顶部状态栏与操作 -->
    <div class="chat-top">
      <div class="chat-title">
        <div class="chat-name">Calo</div>
        <div v-if="currentSessionTitle" class="chat-subtitle" :title="currentSessionTitle">
          {{ currentSessionTitle }}
        </div>
      </div>
      <div class="chat-actions">
        <button
          type="button"
          class="act-btn"
          aria-label="历史会话"
          title="历史会话"
          @click="sessionsDrawerOpen = true"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
            <path d="M3 3v5h5"/>
            <path d="M12 7v5l4 2"/>
          </svg>
        </button>
        <button
          type="button"
          class="act-btn"
          aria-label="新建会话"
          title="新建会话"
          @click="createNewSession"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
        </button>
        <button
          v-if="isDesktop"
          type="button"
          class="act-btn"
          :aria-label="chatCollapsed ? '展开侧栏' : '收起侧栏'"
          :title="chatCollapsed ? '展开侧栏' : '收起侧栏'"
          @click="$emit('toggle-chat')"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline v-if="chatCollapsed" points="15 18 9 12 15 6"/>
            <polyline v-else points="9 18 15 12 9 6"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- 消息滚动区域 -->
    <div ref="scrollRef" class="chat-scroll">
      <!-- 载入中 -->
      <div v-if="loading && messages.length === 0" class="chat-status-hint">
        加载对话记录中…
      </div>

      <!-- 空会话引导卡 -->
      <div v-else-if="messages.length === 0" class="chat-empty">
        <div class="empty-icon">🍽️</div>
        <div class="empty-title">我是 Calo</div>
        <div class="empty-desc">
          你的饮食与热量摄入管理助手。你可以随时问我摄入统计、查询餐食记录，或直接对我说「记一下吃了什么零食」，让我帮你估算并记录。
        </div>
        <div class="prompt-chips">
          <button
            v-for="chip in promptChips"
            :key="chip"
            type="button"
            class="chip"
            @click="sendPrompt(chip)"
          >
            {{ chip }}
          </button>
        </div>
      </div>

      <!-- 消息列表 -->
      <template v-for="msg in messages" :key="msg.id">
        <!-- 用户消息 -->
        <div v-if="msg.role === 'user'" class="message user">
          {{ msg.content }}
        </div>

        <!-- Assistant 消息 -->
        <div v-else class="assistant-group">
          <!-- 过程：工具步骤链（默认折叠）；产物：最终结果卡片 -->
          <ToolSteps v-if="msg.tool_log && msg.tool_log.length" :tools="msg.tool_log" />
          <ChatArtifact
            v-for="(tool, tIdx) in (msg.tool_log || [])"
            :key="`art${tIdx}`"
            :tool="tool"
            :msg="msg"
            @open="$emit('open', $event)"
          />

          <!-- 回复文本内容（Markdown 渲染） -->
          <div v-if="msg.content" class="message calo">
            <div class="msg-content" v-html="renderMarkdown(msg.content)"></div>
          </div>
        </div>
      </template>

      <!-- 思考中气泡 -->
      <div v-if="sending" class="assistant-group">
        <div class="message calo thinking">
          <span class="pulse-dot"></span>
          <span class="pulse-dot"></span>
          <span class="pulse-dot"></span>
          <span class="thinking-text">Calo 正在思考…</span>
        </div>
      </div>
    </div>

    <!-- 底部输入框 -->
    <form class="chat-input" @submit.prevent="submitMessage">
      <input
        ref="inputRef"
        v-model="inputText"
        :disabled="sending"
        aria-label="和 Calo 对话"
        placeholder="和 Calo 说说这顿吃了什么…"
        @keydown.enter.prevent="submitMessage"
      />
      <button
        class="send-btn"
        type="submit"
        :disabled="sending || !inputText.trim()"
        aria-label="发送"
        title="发送"
      >
        ↑
      </button>
    </form>

    <SessionDrawer
      v-if="sessionsDrawerOpen"
      :sessions="sessions"
      :current-id="currentSessionId"
      @close="sessionsDrawerOpen = false"
      @create="createNewSession"
      @select="selectSession"
    />

  </section>
</template>

<style scoped>
.chat-pane {
  display: flex; flex-direction: column; height: 100%;
  background: #0d0d0d; position: relative; overflow: hidden;
}

/* 顶部栏 */
.chat-top {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 14px; border-bottom: 1px solid #1c1c1c; flex: none;
  background: #0d0d0d;
}
.chat-title { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.chat-name { font-size: 16px; font-weight: 700; color: #fff; letter-spacing: -0.2px; }
.chat-subtitle {
  font-size: 12px; color: #666; max-width: 160px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.chat-actions { display: flex; gap: 4px; align-items: center; flex: none; }
.act-btn {
  border: 0; background: transparent; color: #888; cursor: pointer;
  width: 32px; height: 32px; border-radius: 6px; padding: 0;
  display: inline-flex; align-items: center; justify-content: center;
  transition: color 0.15s, background 0.15s;
}
.act-btn:hover { color: #fff; background: #1f1f1f; }
.act-btn svg { display: block; flex: none; }

/* 消息流 */
.chat-scroll {
  flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column;
  gap: 12px; padding: 14px; scrollbar-width: none;
}
.chat-scroll::-webkit-scrollbar { display: none; }

.chat-status-hint {
  text-align: center; color: #666; font-size: 13px; margin: auto 0;
}

/* 空状态 */
.chat-empty {
  margin: auto 0; padding: 20px 10px; display: flex; flex-direction: column;
  align-items: center; text-align: center;
}
.empty-icon { font-size: 36px; margin-bottom: 8px; }
.empty-title { font-size: 16px; font-weight: 600; color: #e0e0e0; margin-bottom: 6px; }
.empty-desc {
  font-size: 13px; color: #777; line-height: 1.5; max-width: 300px; margin-bottom: 20px;
}
.prompt-chips { display: flex; flex-direction: column; gap: 8px; width: 100%; max-width: 280px; }
.chip {
  padding: 8px 12px; border-radius: 8px; font-size: 12px; color: #bbb;
  background: #181818; border: 1px solid #282828; cursor: pointer;
  text-align: left; transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.chip:hover { background: #222; border-color: #383838; color: #fff; }

/* 消息气泡 */
.message {
  max-width: 86%; padding: 10px 13px; border-radius: 12px;
  font-size: 14px; line-height: 1.55; word-break: break-word;
}
.message.user {
  align-self: flex-end; color: #fff; background: #2a6eff;
  border-bottom-right-radius: 3px;
}
.assistant-group {
  align-self: flex-start; display: flex; flex-direction: column;
  gap: 10px; max-width: 92%; width: 100%;
}
.message.calo {
  align-self: flex-start; color: #dedede; background: #1a1a1a;
  border: 1px solid #242424; border-bottom-left-radius: 3px;
}
.msg-content {
  color: #dedede;
  line-height: 1.55;
  font-size: 14px;
}
.msg-content :deep(p) {
  margin: 0 0 8px;
  line-height: 1.55;
}
.msg-content :deep(p:last-child) {
  margin-bottom: 0;
}
.msg-content :deep(strong) {
  color: #fff;
  font-weight: 600;
}
.msg-content :deep(em) {
  color: #ffd43b;
  font-style: normal;
}
.msg-content :deep(ul),
.msg-content :deep(ol) {
  margin: 6px 0 8px;
  padding-left: 18px;
}
.msg-content :deep(li) {
  margin-bottom: 3px;
  line-height: 1.5;
}
.msg-content :deep(li:last-child) {
  margin-bottom: 0;
}
.msg-content :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  background: #252525;
  color: #ffd43b;
  padding: 2px 4px;
  border-radius: 4px;
}
.msg-content :deep(pre) {
  background: #111;
  padding: 8px 10px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 6px 0;
}
.msg-content :deep(pre code) {
  background: transparent;
  padding: 0;
  color: #eee;
}
.msg-content :deep(blockquote) {
  margin: 6px 0;
  padding: 4px 10px;
  border-left: 3px solid #2a6eff;
  background: #141414;
  color: #aaa;
}
.msg-content :deep(a) {
  color: #2a6eff;
  text-decoration: none;
}
.msg-content :deep(a:hover) {
  text-decoration: underline;
}

/* 思考中动画 */
.message.thinking {
  display: flex; align-items: center; gap: 6px; padding: 10px 14px;
}
.pulse-dot {
  width: 6px; height: 6px; border-radius: 50%; background: #666;
  animation: pulse 1.4s infinite ease-in-out both;
}
.pulse-dot:nth-child(1) { animation-delay: -0.32s; }
.pulse-dot:nth-child(2) { animation-delay: -0.16s; }
@keyframes pulse {
  0%, 80%, 100% { transform: scale(0); opacity: 0.3; }
  40% { transform: scale(1); opacity: 1; }
}
.thinking-text { font-size: 12px; color: #888; margin-left: 4px; }

/* 底部输入框 */
.chat-input {
  display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid #1c1c1c;
  background: #0f0f0f; flex: none; align-items: center;
}
.chat-input input {
  min-width: 0; flex: 1; height: 38px; border: 1px solid #262626;
  border-radius: 19px; background: #161616; color: #eee; padding: 0 14px;
  font: inherit; font-size: 13px; outline: none; box-sizing: border-box;
  transition: border-color 0.15s;
}
.chat-input input:focus { border-color: #2a6eff; }
.chat-input input:disabled { opacity: 0.6; }
.send-btn {
  width: 36px; height: 36px; flex: none; border: 0; border-radius: 50%;
  background: #2a6eff; color: #fff; font-size: 16px; font-weight: 700;
  display: flex; align-items: center; justify-content: center; cursor: pointer;
  transition: opacity 0.15s;
}
.send-btn:disabled { opacity: 0.3; cursor: not-allowed; }
</style>
