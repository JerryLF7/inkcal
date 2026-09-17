<script setup>
import { ref, computed, nextTick, onMounted } from 'vue';
import { marked } from 'marked';
import MealCard from './MealCard.vue';
import { API, fmtTimeHM } from '../utils/format.js';
import { touch, toast } from '../store.js';

marked.setOptions({
  breaks: true,
  gfm: true,
});

function renderMarkdown(text) {
  if (!text) return '';
  return marked.parse(text);
}

const props = defineProps({
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

// 侧拉/弹窗状态
const sessionsDrawerOpen = ref(false);
const settingsModalOpen = ref(false);
const chatWindowSetting = ref(20);
const savingSettings = ref(false);

const currentSession = computed(() => {
  if (!currentSessionId.value) return null;
  return sessions.value.find(s => s.id === currentSessionId.value) || null;
});

const currentSessionTitle = computed(() => {
  return currentSession.value?.title || '';
});

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

// ── 规范化 record 对象供 MealCard / Lightbox 使用 ─────────────
function normalizeRecord(r) {
  if (!r) return {};
  const photoTime = r.photo_time || '';
  const date = photoTime ? photoTime.slice(0, 10) : '';
  return {
    ...r,
    date,
    confidence: r.confidence || 'low',
    photos: r.photos?.length ? r.photos : [{
      asset_id: r.asset_id,
      photo_time: r.photo_time,
      meal: r.meal,
      meal_detail: r.meal_detail,
      calories: r.calories,
      thumbnail_url: r.thumbnail_url,
      replacement_image: r.replacement_image,
      emoji: r.emoji,
    }],
  };
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

// ── 删除确认卡处理（Phase 5 约束：绝不越过用户确认直接删除）──
const deletingAssetId = ref('');

async function handleDeleteRecord(toolResult) {
  const card = toolResult?.confirm_card;
  if (!card || !card.asset_id || deletingAssetId.value) return;

  deletingAssetId.value = card.asset_id;
  try {
    const res = await fetch(`${API}/api/record`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        asset_id: card.asset_id,
        mode: 'meal',
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      toast(err.error || '删除失败', 'error');
      return;
    }

    toolResult._status = 'confirmed';
    touch();
    toast('已删除记录');
  } catch (e) {
    toast('网络异常，删除失败', 'error');
  } finally {
    deletingAssetId.value = '';
  }
}

function handleCancelDelete(toolResult) {
  toolResult._status = 'canceled';
}

// ── 聊天设置（/api/settings 中的 chat_window）────────────────
async function openSettings() {
  settingsModalOpen.value = true;
  try {
    const res = await fetch(`${API}/api/settings`);
    if (res.ok) {
      const data = await res.json();
      chatWindowSetting.value = data.chat_window || 20;
    }
  } catch (e) {
    console.error('Failed to load settings:', e);
  }
}

async function saveSettings() {
  savingSettings.value = true;
  try {
    const res = await fetch(`${API}/api/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_window: chatWindowSetting.value }),
    });
    if (res.ok) {
      toast('设置已保存');
      settingsModalOpen.value = false;
    } else {
      toast('保存失败', 'error');
    }
  } catch (e) {
    toast('保存失败', 'error');
  } finally {
    savingSettings.value = false;
  }
}

function formatSessionTime(t) {
  if (!t) return '';
  return t.replace('T', ' ').slice(0, 16);
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
          ◷
        </button>
        <button
          type="button"
          class="act-btn"
          aria-label="新建会话"
          title="新建会话"
          @click="createNewSession"
        >
          ＋
        </button>
        <button
          type="button"
          class="act-btn settings-btn"
          aria-label="设置"
          title="设置"
          @click="openSettings"
        >
          ⚙️
        </button>
        <button
          v-if="isDesktop"
          type="button"
          class="act-btn collapse-btn"
          :aria-label="chatCollapsed ? '展开侧栏' : '收起侧栏'"
          :title="chatCollapsed ? '展开侧栏' : '收起侧栏'"
          @click="$emit('toggle-chat')"
        >
          {{ chatCollapsed ? '◂' : '▸' }}
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
          <!-- 工具执行状态与 Artifact -->
          <template v-if="msg.tool_log && msg.tool_log.length">
            <div
              v-for="(tool, tIdx) in msg.tool_log"
              :key="tIdx"
              class="tool-wrap"
            >
              <!-- 1. 查询/搜索餐食记录列表 (get_records_in_range / search_meals) -->
              <div
                v-if="(tool.name === 'get_records_in_range' || tool.name === 'search_meals') && tool.result?.records?.length"
                class="artifact"
              >
                <div class="artifact-caption">
                  {{ tool.name === 'search_meals' ? `搜索「${tool.args?.keyword || ''}」找到 ${tool.result.records.length} 餐：` : `找到 ${tool.result.records.length} 餐：` }}
                </div>
                <div class="artifact-cards">
                  <MealCard
                    v-for="rec in tool.result.records"
                    :key="rec.asset_id || rec.id"
                    :record="normalizeRecord(rec)"
                    :interactive="true"
                    @open="$emit('open', normalizeRecord(rec))"
                  />
                </div>
              </div>

              <!-- 2. 编辑/重新分析记录后展示更新卡 (edit_record / reanalyze_record) -->
              <div
                v-else-if="(tool.name === 'edit_record' || tool.name === 'reanalyze_record') && tool.result?.after"
                class="artifact"
              >
                <div class="artifact-caption">
                  {{ tool.name === 'edit_record' ? '✏️ 已更新餐食记录：' : '🔄 已重新分析餐食记录：' }}
                </div>
                <MealCard
                  :record="normalizeRecord(tool.result.after)"
                  :interactive="true"
                  @open="$emit('open', normalizeRecord(tool.result.after))"
                />
              </div>

              <!-- 3. 添加记录后展示记录卡 (add_record) -->
              <div
                v-else-if="tool.name === 'add_record' && tool.result?.record"
                class="artifact"
              >
                <div class="artifact-caption">
                  📝 已添加餐食记录：
                </div>
                <MealCard
                  :record="normalizeRecord(tool.result.record)"
                  :interactive="true"
                  @open="$emit('open', normalizeRecord(tool.result.record))"
                />
              </div>

              <!-- 4. 删除确认卡 (request_delete_record) -->
              <div
                v-else-if="tool.name === 'request_delete_record' && tool.result?.confirm_card"
                class="confirm-card"
                :class="{
                  'confirmed': tool.result._status === 'confirmed',
                  'canceled': tool.result._status === 'canceled'
                }"
              >
                <template v-if="tool.result._status === 'confirmed'">
                  <div class="confirm-done">✅ 已删除该餐记录</div>
                </template>
                <template v-else-if="tool.result._status === 'canceled'">
                  <div class="confirm-canceled">已取消删除</div>
                </template>
                <template v-else>
                  <div class="confirm-text">
                    确认删除 <strong>{{ tool.result.confirm_card.meal || '该餐' }}</strong>（{{ fmtTimeHM(tool.result.confirm_card.photo_time) }}，{{ tool.result.confirm_card.calories }} kcal）吗？
                  </div>
                  <div class="confirm-actions">
                    <button
                      type="button"
                      class="confirm-btn danger"
                      :disabled="deletingAssetId === tool.result.confirm_card.asset_id"
                      @click="handleDeleteRecord(tool.result)"
                    >
                      {{ deletingAssetId === tool.result.confirm_card.asset_id ? '删除中…' : '确认删除' }}
                    </button>
                    <button
                      type="button"
                      class="confirm-btn cancel"
                      :disabled="deletingAssetId === tool.result.confirm_card.asset_id"
                      @click="handleCancelDelete(tool.result)"
                    >
                      取消
                    </button>
                  </div>
                </template>
              </div>

              <!-- 4. 统计卡 (get_intake_stats) -->
              <div
                v-else-if="tool.name === 'get_intake_stats' && tool.result?.total"
                class="stats-artifact"
              >
                <div class="stats-header">
                  📊 {{ tool.args?.start || '' }} 至 {{ tool.args?.end || '' }} 摄入汇总
                </div>
                <div class="stats-grid">
                  <div class="stat-cell">
                    <span class="stat-val">{{ Math.round(tool.result.total.calories || 0) }}</span>
                    <span class="stat-unit">kcal</span>
                    <span class="stat-label">总热量</span>
                  </div>
                  <div class="stat-cell">
                    <span class="stat-val">{{ tool.result.total.meals ?? tool.result.total.count ?? 0 }}</span>
                    <span class="stat-unit">餐</span>
                    <span class="stat-label">餐数</span>
                  </div>
                  <div class="stat-cell">
                    <span class="stat-val p">{{ Math.round(tool.result.total.protein ?? tool.result.total.protein_g ?? 0) }}</span>
                    <span class="stat-unit">g</span>
                    <span class="stat-label">蛋白质</span>
                  </div>
                  <div class="stat-cell">
                    <span class="stat-val c">{{ Math.round(tool.result.total.carbs ?? tool.result.total.carbs_g ?? 0) }}</span>
                    <span class="stat-unit">g</span>
                    <span class="stat-label">碳水</span>
                  </div>
                  <div class="stat-cell">
                    <span class="stat-val f">{{ Math.round(tool.result.total.fat ?? tool.result.total.fat_g ?? 0) }}</span>
                    <span class="stat-unit">g</span>
                    <span class="stat-label">脂肪</span>
                  </div>
                </div>
              </div>
            </div>
          </template>

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
      <button
        class="chat-plus"
        type="button"
        aria-label="聊天设置"
        title="聊天设置"
        @click="openSettings"
      >
        ⚙️
      </button>
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

    <!-- 历史会话抽屉 / 遮罩 -->
    <div v-if="sessionsDrawerOpen" class="drawer-mask" @click.self="sessionsDrawerOpen = false">
      <div class="drawer">
        <div class="drawer-header">
          <div class="drawer-title">历史会话</div>
          <button
            type="button"
            class="drawer-close"
            aria-label="关闭"
            @click="sessionsDrawerOpen = false"
          >
            ✕
          </button>
        </div>
        <div class="drawer-action">
          <button type="button" class="new-session-btn" @click="createNewSession">
            ＋ 新建会话
          </button>
        </div>
        <div class="session-list">
          <div
            v-if="sessions.length === 0"
            class="session-empty"
          >
            暂无历史会话
          </div>
          <div
            v-for="s in sessions"
            :key="s.id"
            class="session-item"
            :class="{ active: s.id === currentSessionId }"
            @click="selectSession(s.id)"
          >
            <div class="session-item-title">{{ s.title || '新会话' }}</div>
            <div class="session-item-time">{{ formatSessionTime(s.updated_at || s.created_at) }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 聊天设置弹窗 -->
    <div v-if="settingsModalOpen" class="drawer-mask" @click.self="settingsModalOpen = false">
      <div class="settings-dialog">
        <div class="drawer-header">
          <div class="drawer-title">聊天设置</div>
          <button
            type="button"
            class="drawer-close"
            aria-label="关闭"
            @click="settingsModalOpen = false"
          >
            ✕
          </button>
        </div>
        <div class="settings-body">
          <div class="setting-item">
            <div class="setting-label">
              <span>上下文滑动窗口</span>
              <span class="setting-val">{{ chatWindowSetting }} 轮</span>
            </div>
            <input
              v-model.number="chatWindowSetting"
              type="range"
              min="5"
              max="50"
              step="1"
              class="setting-range"
            />
            <div class="setting-desc">
              每轮向模型发送最近 N 轮对话历史（5～50 轮，默认 20）。调大可记住更长上下文，调小节省 Token 与提高响应速度。
            </div>
          </div>
        </div>
        <div class="settings-footer">
          <button
            type="button"
            class="btn-save"
            :disabled="savingSettings"
            @click="saveSettings"
          >
            {{ savingSettings ? '保存中…' : '保存设置' }}
          </button>
        </div>
      </div>
    </div>
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
  width: 32px; height: 32px; border-radius: 6px; font-size: 16px;
  display: flex; align-items: center; justify-content: center;
  transition: color 0.15s, background 0.15s;
}
.act-btn:hover { color: #fff; background: #1f1f1f; }
.settings-btn { font-size: 14px; }
.collapse-btn { font-size: 14px; }

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

/* 工具与 Artifact */
.tool-wrap { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.artifact {
  border: 1px solid #2a2a2a; border-radius: 10px; background: #141414;
  padding: 10px; width: 100%; box-sizing: border-box;
}
.artifact-caption {
  color: #888; font-size: 12px; font-weight: 500; margin-bottom: 8px;
}
.artifact-cards { display: flex; flex-direction: column; gap: 8px; }

/* 删除确认卡 */
.confirm-card {
  border: 1px solid #3d3525; border-radius: 10px; background: #1a1712;
  padding: 12px; width: 100%; box-sizing: border-box;
}
.confirm-card.confirmed { border-color: #243d25; background: #121a13; }
.confirm-card.canceled { border-color: #282828; background: #161616; opacity: 0.75; }
.confirm-text { color: #e6e6e6; font-size: 13px; line-height: 1.5; margin-bottom: 10px; }
.confirm-text strong { color: #ffd43b; }
.confirm-done { color: #51cf66; font-size: 13px; }
.confirm-canceled { color: #888; font-size: 13px; }
.confirm-actions { display: flex; gap: 8px; }
.confirm-btn {
  flex: 1; padding: 7px 12px; border-radius: 6px; font-size: 12px;
  cursor: pointer; border: 1px solid transparent; font-family: inherit;
}
.confirm-btn.danger { background: #ff6b6b; color: #fff; }
.confirm-btn.danger:hover { background: #fa5252; }
.confirm-btn.cancel { background: #262626; color: #ccc; border-color: #333; }
.confirm-btn.cancel:hover { background: #303030; }

/* 统计卡 */
.stats-artifact {
  border: 1px solid #282828; border-radius: 10px; background: #141414;
  padding: 12px; width: 100%; box-sizing: border-box;
}
.stats-header { font-size: 12px; color: #aaa; margin-bottom: 10px; font-weight: 500; }
.stats-grid { display: flex; gap: 8px; justify-content: space-between; }
.stat-cell {
  display: flex; flex-direction: column; align-items: center; flex: 1;
}
.stat-val { font-size: 16px; font-weight: 700; color: #fff; line-height: 1.1; }
.stat-val.p { color: #51cf66; }
.stat-val.c { color: #ffd43b; }
.stat-val.f { color: #ff922b; }
.stat-unit { font-size: 10px; color: #777; line-height: 1; margin-top: 2px; }
.stat-label { font-size: 11px; color: #666; margin-top: 4px; }

/* 底部输入框 */
.chat-input {
  display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid #1c1c1c;
  background: #0f0f0f; flex: none; align-items: center;
}
.chat-plus {
  width: 36px; height: 36px; flex: none; border: 1px solid #262626;
  border-radius: 50%; background: #181818; color: #888; font-size: 16px;
  display: flex; align-items: center; justify-content: center; cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.chat-plus:hover { background: #222; color: #fff; }
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

/* 抽屉与弹窗 */
.drawer-mask {
  position: absolute; inset: 0; background: rgba(0, 0, 0, 0.7);
  z-index: 50; display: flex; justify-content: flex-end;
}
.drawer {
  width: 280px; height: 100%; background: #141414; border-left: 1px solid #222;
  display: flex; flex-direction: column; box-sizing: border-box;
}
.drawer-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px; border-bottom: 1px solid #202020;
}
.drawer-title { font-size: 14px; font-weight: 600; color: #eee; }
.drawer-close {
  border: 0; background: transparent; color: #888; font-size: 15px;
  cursor: pointer; padding: 4px;
}
.drawer-close:hover { color: #fff; }
.drawer-action { padding: 10px 14px; border-bottom: 1px solid #1c1c1c; }
.new-session-btn {
  width: 100%; padding: 8px; border-radius: 6px; border: 1px solid #2a6eff;
  background: #2a6eff15; color: #2a6eff; font-size: 13px; font-weight: 500;
  cursor: pointer; transition: background 0.15s;
}
.new-session-btn:hover { background: #2a6eff28; }
.session-list { flex: 1; overflow-y: auto; padding: 8px 10px; }
.session-empty { text-align: center; color: #666; font-size: 12px; margin-top: 20px; }
.session-item {
  padding: 10px 12px; border-radius: 8px; cursor: pointer;
  margin-bottom: 6px; transition: background 0.15s;
}
.session-item:hover { background: #1c1c1c; }
.session-item.active { background: #222; border-left: 3px solid #2a6eff; }
.session-item-title {
  font-size: 13px; color: #ddd; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; margin-bottom: 3px;
}
.session-item-time { font-size: 11px; color: #666; }

/* 聊天设置弹窗 */
.settings-dialog {
  margin: auto; width: 90%; max-width: 320px; background: #161616;
  border: 1px solid #282828; border-radius: 12px; overflow: hidden;
  box-shadow: 0 10px 25px rgba(0,0,0,0.5);
}
.settings-body { padding: 16px; }
.setting-item { display: flex; flex-direction: column; gap: 8px; }
.setting-label {
  display: flex; justify-content: space-between; font-size: 13px; color: #ddd;
}
.setting-val { color: #2a6eff; font-weight: 600; }
.setting-range { width: 100%; accent-color: #2a6eff; }
.setting-desc { font-size: 11px; color: #777; line-height: 1.45; }
.settings-footer { padding: 12px 16px; border-top: 1px solid #222; display: flex; justify-content: flex-end; }
.btn-save {
  padding: 7px 16px; border-radius: 6px; border: 0; background: #2a6eff;
  color: #fff; font-size: 13px; cursor: pointer;
}
.btn-save:hover { background: #235cd6; }
.btn-save:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
