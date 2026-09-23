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

// 侧拉状态（聊天窗口设置已迁移至设置 Tab）
const sessionsDrawerOpen = ref(false);

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

function formatSessionTime(t) {
  if (!t) return '';
  return t.replace('T', ' ').slice(0, 16);
}

// ── 工具执行步骤链（参考 LobeHub/Pi：过程折叠、产物留白）──────────
// 设计契约：
//   1. 每一次工具调用都是"过程"，收进默认折叠的步骤条里，标题优先用
//      模型给出的 intent（本次调用的目的），历史消息无 intent 时按工具
//      名 + 关键参数兜底，绝不把函数名直接甩给用户。
//   2. 只有"最终产物"才在步骤条下方单独渲染卡片：写操作永远展示；
//      查询类结果仅在本轮没有写操作时展示（否则它只是内部参考依据，
//      例如为确认未重复而回查今天、为对比份量而回查昨天）。
const TOOL_LABELS = {
  get_records_in_range: '查询餐食记录',
  get_intake_stats: '统计摄入情况',
  search_meals: '搜索餐食记录',
  get_decisions: '查看 AI 识别决策',
  edit_record: '修改餐食记录',
  add_record: '补记餐食记录',
  reanalyze_record: '重新分析餐食记录',
  request_delete_record: '请求删除餐食记录',
};

// 写操作：其结果卡片是用户真正关心的产物，必须展示
const WRITE_TOOLS = new Set([
  'add_record', 'edit_record', 'reanalyze_record', 'request_delete_record',
]);

const stepsOpen = ref({});        // 步骤条展开态，key = msg.id
const stepDetailOpen = ref({});   // 单步详情展开态，key = `${msg.id}:${idx}`

function toggleSteps(id) { stepsOpen.value[id] = !stepsOpen.value[id]; }
function toggleStepDetail(key) { stepDetailOpen.value[key] = !stepDetailOpen.value[key]; }

// 步骤标题：优先 intent，其次工具名兜底 + 参数线索
function stepTitle(tool) {
  const intent = (tool.args?.intent || '').trim();
  if (intent) return intent;

  const label = TOOL_LABELS[tool.name] || tool.name;
  const a = tool.args || {};
  if (tool.name === 'get_records_in_range') {
    const s = (a.start || '').slice(5);
    const e = (a.end || '').slice(5);
    if (s && e) return s === e ? `${label} (${s})` : `${label} (${s}~${e})`;
  } else if (tool.name === 'search_meals' && a.keyword) {
    return `${label}「${a.keyword}」`;
  } else if (tool.name === 'get_decisions' && a.date) {
    return `${label} (${a.date.slice(5)})`;
  }
  return label;
}

// 步骤右侧的轻量结果徽标（不铺开正文，只给一个量级）
function stepBadge(tool) {
  if (tool.name === 'get_records_in_range' || tool.name === 'search_meals') {
    const n = tool.result?.records?.length;
    return n ? `${n} 条` : '';
  }
  if (tool.name === 'get_intake_stats' && tool.result?.total) {
    return `${Math.round(tool.result.total.calories || 0)} kcal`;
  }
  if (tool.name === 'get_decisions') {
    const n = tool.result?.count ?? tool.result?.decisions?.length;
    return n ? `${n} 条` : '';
  }
  return '';
}

function stepParams(tool) {
  const a = { ...(tool.args || {}) };
  delete a.intent;                       // intent 已是标题，不重复展示
  return JSON.stringify(a);
}

function stepOutcome(tool) {
  const r = tool.result || {};
  if (tool.name === 'get_records_in_range' || tool.name === 'search_meals') {
    return `匹配 ${r.records?.length || 0} 条记录`;
  }
  if (tool.name === 'get_intake_stats') {
    return r.total ? `${Math.round(r.total.calories || 0)} kcal` : (r.error || '');
  }
  if (tool.name === 'get_decisions') {
    return `审计决策 ${r.count ?? (r.decisions?.length || 0)} 条`;
  }
  if (tool.name === 'add_record') {
    return r.record ? `新增「${r.record.meal}」${r.record.calories} kcal` : (r.error || '');
  }
  if (tool.name === 'edit_record' || tool.name === 'reanalyze_record') {
    return r.after ? `「${r.after.meal}」${r.after.calories} kcal` : (r.error || '');
  }
  if (tool.name === 'request_delete_record') {
    return r.confirm_card ? '已生成待确认删除卡' : (r.error || '');
  }
  return '';
}

// 查询结果卡片只在本轮无写操作时展示（否则属内部参考步骤）
function recordsArtifactVisible(tool, msg) {
  if (!tool.result?.records?.length) return false;
  const hasWrite = (msg.tool_log || []).some(t => WRITE_TOOLS.has(t.name));
  return !hasWrite;
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
          <!-- ── ① 过程：工具执行步骤链（默认折叠，参考 LobeHub/Pi）── -->
          <div v-if="msg.tool_log && msg.tool_log.length" class="tool-steps">
            <button type="button" class="steps-head" @click="toggleSteps(msg.id)">
              <span class="steps-check">✓</span>
              <span class="steps-label">已执行 {{ msg.tool_log.length }} 步操作</span>
              <span class="steps-caret" :class="{ open: !!stepsOpen[msg.id] }">▾</span>
            </button>
            <div v-if="stepsOpen[msg.id]" class="steps-body">
              <div v-for="(tool, tIdx) in msg.tool_log" :key="tIdx" class="step">
                <button
                  type="button"
                  class="step-row"
                  @click="toggleStepDetail(`${msg.id}:${tIdx}`)"
                >
                  <span class="step-check">✓</span>
                  <span class="step-title">{{ stepTitle(tool) }}</span>
                  <span v-if="stepBadge(tool)" class="step-badge">{{ stepBadge(tool) }}</span>
                  <span
                    class="step-caret"
                    :class="{ open: !!stepDetailOpen[`${msg.id}:${tIdx}`] }"
                  >▸</span>
                </button>
                <div
                  v-if="stepDetailOpen[`${msg.id}:${tIdx}`]"
                  class="step-detail"
                >
                  <div class="step-line">
                    <span class="step-k">参数</span><code>{{ stepParams(tool) }}</code>
                  </div>
                  <div v-if="stepOutcome(tool)" class="step-line">
                    <span class="step-k">结果</span><code>{{ stepOutcome(tool) }}</code>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- ── ② 产物：仅渲染最终结果卡片（写操作 + 纯查询 + 统计）── -->
          <template v-for="(tool, tIdx) in (msg.tool_log || [])" :key="`art${tIdx}`">
            <!-- 1. 添加记录后展示记录卡 (add_record) -->
            <div
              v-if="tool.name === 'add_record' && tool.result?.record"
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

            <!-- 3. 删除确认卡 (request_delete_record) -->
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

            <!-- 4. 统计卡 (get_intake_stats)：本身就是答案，始终展示 -->
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

            <!-- 5. 查询/搜索结果卡：仅在本轮无写操作时展示（否则属内部参考步骤） -->
            <div
              v-else-if="(tool.name === 'get_records_in_range' || tool.name === 'search_meals') && recordsArtifactVisible(tool, msg)"
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

/* 工具与 Artifact */

/* ── 工具执行步骤链（默认折叠，参考 LobeHub/Pi 的过程展示）── */
.tool-steps {
  border: 1px solid #1f1f1f; border-radius: 10px;
  background: #121212; overflow: hidden; width: 100%;
}
.steps-head {
  width: 100%; display: flex; align-items: center; gap: 7px;
  padding: 8px 11px; background: none; border: 0; cursor: pointer;
  color: #9a9a9a; font: inherit; font-size: 12px; text-align: left;
  transition: background 0.15s;
}
.steps-head:hover { background: #181818; }
.steps-check { color: #51cf66; font-size: 11px; flex: none; line-height: 1; }
.steps-label { flex: 1; min-width: 0; }
.steps-caret {
  color: #555; font-size: 9px; flex: none; line-height: 1;
  transition: transform 0.18s ease;
}
.steps-caret.open { transform: rotate(180deg); }

.steps-body { border-top: 1px solid #1c1c1c; padding: 3px 0; }
.step + .step { border-top: 1px solid #191919; }
.step-row {
  width: 100%; display: flex; align-items: center; gap: 7px;
  padding: 7px 11px; background: none; border: 0; cursor: pointer;
  color: #b8b8b8; font: inherit; font-size: 12px; text-align: left;
  transition: background 0.15s;
}
.step-row:hover { background: #181818; }
.step-check { color: #51cf66; font-size: 11px; flex: none; line-height: 1; }
.step-title { flex: 1; min-width: 0; word-break: break-word; line-height: 1.4; }
.step-badge {
  flex: none; font-size: 10px; color: #808080; line-height: 1.6;
  background: #1f1f1f; border-radius: 6px; padding: 0 6px;
}
.step-caret {
  color: #4a4a4a; font-size: 8px; flex: none; line-height: 1;
  transition: transform 0.15s ease;
}
.step-caret.open { transform: rotate(90deg); }

.step-detail {
  display: flex; flex-direction: column; gap: 4px;
  padding: 0 11px 9px 29px;
}
.step-line { display: flex; gap: 8px; align-items: baseline; }
.step-k { flex: none; font-size: 10px; color: #555; }
.step-detail code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10.5px; color: #8a8a8a; line-height: 1.5;
  word-break: break-all;
}

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
</style>
