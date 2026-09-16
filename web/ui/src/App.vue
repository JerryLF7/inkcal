<script setup>
import { ref, nextTick, onMounted, onBeforeUnmount } from 'vue';
import DayView from './components/DayView.vue';
import WeekView from './components/WeekView.vue';
import MonthView from './components/MonthView.vue';
import MealLightbox from './components/MealLightbox.vue';
import PhotoPicker from './components/PhotoPicker.vue';
import ChatPane from './components/ChatPane.vue';
import { store, startDataVersionPolling } from './store.js';
import { fmtDate, addDays, hktNow } from './utils/format.js';

// 双 pane：记录 / Calo 对话（原型 docs/prototypes/two-tab-proto.html）
const pane = ref('records');           // 'records' | 'chat'
const view = ref('day');               // 'day' | 'week'（PC 端月历常驻左栏，无月视图页）

// 各视图各自上报顶栏标题；切换时恢复该视图最近一次上报的标题
const titles = {
  day: ref({ main: '', sub: '' }),
  week: ref({ main: '', sub: '' }),
};
const title = ref({ main: '', sub: '' });

function onTitle(v, t) {
  titles[v].value = t;
  if (view.value === v) title.value = t;
}

function switchView(v) {
  view.value = v;
  title.value = titles[v].value.main ? titles[v].value : title.value;
}

const dayViewRef = ref(null);
const weekViewRef = ref(null);
const lightboxRecord = ref(null);
const photoPickerOpen = ref(false);

function openLightbox(r) { lightboxRecord.value = r; }
function openPhotoPicker() { photoPickerOpen.value = true; }

// 日历点日期 → 跳回日视图时间轴并定位
function onSelectDate(ds) {
  switchView('day');
  nextTick(() => { dayViewRef.value && dayViewRef.value.jumpTo(ds); });
}

// 左栏快捷键：今日 / 本周
function goToday() { onSelectDate(fmtDate(hktNow())); }
function goThisWeek() {
  switchView('week');
  nextTick(() => { weekViewRef.value && weekViewRef.value.resetToCurrentWeek(); });
}

// ── pane 切换（tab + 左右滑动）─────────────────────────────
function go(p) { pane.value = p; }

let sx = 0, sy = 0;
function onTouchStart(e) {
  sx = e.touches[0].clientX;
  sy = e.touches[0].clientY;
}
function onTouchEnd(e) {
  const dx = e.changedTouches[0].clientX - sx;
  const dy = e.changedTouches[0].clientY - sy;
  if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) {
    go(dx < 0 ? 'chat' : 'records');
  }
}

// ── PC 布局（≥1024px）：左导航栏 + 记录主区 + Luna 右侧栏 ─────
const mqDesktop = window.matchMedia('(min-width: 1024px)');
const isDesktop = ref(mqDesktop.matches);
const chatCollapsed = ref(false);     // PC 侧栏折叠状态（默认展开）

function onMqChange(e) {
  isDesktop.value = e.matches;
  if (!isDesktop.value) chatCollapsed.value = false;  // 回到手机布局时复位
}

onMounted(() => {
  mqDesktop.addEventListener('change', onMqChange);
  startDataVersionPolling();
});
onBeforeUnmount(() => mqDesktop.removeEventListener('change', onMqChange));

function toggleChat() { chatCollapsed.value = !chatCollapsed.value; }
</script>

<template>
  <div class="app" :class="{ desktop: isDesktop, 'chat-hidden': chatCollapsed }">
    <!-- PC 左侧导航栏：品牌、选择照片、视图切换、常驻日历、快捷键 -->
    <aside v-if="isDesktop" class="nav-rail">
      <div class="rail-brand">inkcal</div>
      <button class="photo-button rail-photo" type="button" @click="openPhotoPicker">选择照片</button>
      <div class="rail-section">
        <div class="seg rail-seg">
          <button
            v-for="v in [['day', '日'], ['week', '周']]"
            :key="v[0]"
            :class="{ active: view === v[0] }"
            @click="switchView(v[0])"
          >{{ v[1] }}</button>
        </div>
      </div>
      <div class="rail-section rail-calendar">
        <MonthView compact @select="onSelectDate" />
      </div>
      <div class="rail-section rail-quick">
        <button class="quick-link" type="button" @click="goToday">今日</button>
        <button class="quick-link" type="button" @click="goThisWeek">本周</button>
      </div>
    </aside>

    <div
      class="panes" :class="{ 'show-chat': pane === 'chat' }"
      @touchstart.passive="onTouchStart" @touchend.passive="onTouchEnd"
    >
      <!-- 主区：记录 -->
      <section class="pane records-pane">
        <div class="topbar">
          <div class="sticky-date">{{ title.main }}<small>{{ title.sub }}</small></div>
          <div class="record-actions">
            <template v-if="!isDesktop">
              <button class="photo-button" type="button" aria-label="选择照片" @click="openPhotoPicker">选择照片</button>
              <div class="seg">
                <button
                  v-for="v in [['day', '日'], ['week', '周'], ['month', '月']]"
                  :key="v[0]"
                  :class="{ active: view === v[0] }"
                  @click="switchView(v[0])"
                >{{ v[1] }}</button>
              </div>
            </template>
          </div>
        </div>

        <DayView
          v-show="view === 'day'" ref="dayViewRef"
          @open="openLightbox" @title="t => onTitle('day', t)"
        />
        <WeekView
          v-show="view === 'week'" ref="weekViewRef"
          @open="openLightbox" @title="t => onTitle('week', t)"
        />
        <MonthView
          v-if="!isDesktop" v-show="view === 'month'"
          @select="onSelectDate" @title="() => {}"
        />
      </section>

      <!-- Calo 对话：手机端为第二 pane；PC 端为右侧栏（可折叠） -->
      <ChatPane
        :is-desktop="isDesktop"
        :chat-collapsed="chatCollapsed"
        @toggle-chat="toggleChat"
        @open="openLightbox"
      />
    </div>

    <!-- PC 折叠后的唤出把手 -->
    <button v-if="isDesktop && chatCollapsed" class="chat-restorer" type="button" aria-label="打开 Calo 侧栏" title="打开 Calo 侧栏" @click="toggleChat">◂</button>

    <nav v-if="!isDesktop" class="tabbar">
      <button :class="{ active: pane === 'records' }" @click="go('records')">
        <span class="ico">📖</span>记录
      </button>
      <button :class="{ active: pane === 'chat' }" @click="go('chat')">
        <span class="ico">💬</span>Calo
      </button>
    </nav>

    <MealLightbox :record="lightboxRecord" @close="lightboxRecord = null" />
    <PhotoPicker v-if="photoPickerOpen" @close="photoPickerOpen = false" />

    <div v-if="store.toastMsg" class="toast" :class="store.toastType">{{ store.toastMsg }}</div>
  </div>
</template>

<style>
/* 全局（非 scoped）：body 背景与字体 */
html, body {
  background: #000; margin: 0;
  font-family: -apple-system, "PingFang SC", "Noto Sans SC", sans-serif;
  -webkit-tap-highlight-color: transparent;
}
</style>

<style scoped>
.app {
  display: flex; flex-direction: column;
  height: 100dvh; max-width: 480px; margin: 0 auto;
  background: #0f0f0f; color: #e0e0e0;
  overflow: hidden; position: relative;
}
@media (min-width: 520px) {
  .app { border-left: 1px solid #1c1c1c; border-right: 1px solid #1c1c1c; }
}

.panes {
  flex: 1; display: flex; width: 200%;
  transition: transform .28s ease;
  transform: translateX(0);
  overflow: hidden;
  min-height: 0;
}
.panes.show-chat { transform: translateX(-50%); }
.pane { width: 50%; height: 100%; display: flex; flex-direction: column; overflow: hidden; }

.topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 14px 10px; border-bottom: 1px solid #1c1c1c; flex: none;
}
.sticky-date { font-size: 15px; font-weight: 600; color: #e0e0e0; }
.sticky-date small { color: #888; font-weight: 400; margin-left: 4px; }

.seg {
  display: flex; background: #1a1a1a; border: 1px solid #2a2a2a;
  border-radius: 8px; padding: 2px; gap: 2px;
}
.record-actions { display: flex; align-items: center; gap: 8px; }
.photo-button {
  border: 1px solid #2a6eff; border-radius: 6px; background: #2a6eff;
  color: #fff; font: inherit; font-size: 12px; padding: 6px 8px; cursor: pointer;
  white-space: nowrap;
}
.photo-button:active { background: #1a5aee; }
.seg button {
  border: none; background: none; color: #888; font-size: 12px;
  padding: 4px 12px; border-radius: 7px; cursor: pointer; font-family: inherit;
}
.seg button.active { background: #2a6eff22; color: #2a6eff; }

.tabbar {
  flex: none; display: flex; border-top: 1px solid #1c1c1c; background: #0d0d0d;
  padding: 6px 0 calc(14px + env(safe-area-inset-bottom));
}
.tabbar button {
  flex: 1; background: none; border: none; color: #666; font-size: 12px;
  cursor: pointer; font-family: inherit; padding: 6px 0;
  display: flex; flex-direction: column; align-items: center; gap: 3px;
}
.tabbar button .ico { font-size: 18px; }
.tabbar button.active { color: #2a6eff; }

/* ── PC 布局（≥1024px）：左导航栏 + 记录主区 + Calo 右侧栏 ───── */
@media (min-width: 1024px) {
  .app { max-width: none; border-left: none; border-right: none; }

  /* 关键：手机布局是纵向 flex，桌面改为横向，左栏才能与主区并列 */
  .app.desktop { flex-direction: row; }
  .chat-pane { border-left: 1px solid #1c1c1c; }

  /* 左侧导航栏（参考旧版桌面布局）：品牌 + 选择照片 + 日/周切换 + 常驻日历 + 快捷键 */
  .nav-rail {
    flex: none; width: 264px; height: 100%;
    display: flex; flex-direction: column; gap: 14px;
    padding: 18px 16px; overflow-y: auto; scrollbar-width: none;
    border-right: 1px solid #1c1c1c; background: #0d0d0d;
  }
  .nav-rail::-webkit-scrollbar { display: none; }
  .rail-brand { font-size: 17px; font-weight: 700; color: #e0e0e0; }
  .rail-photo { width: 100%; font-size: 13px; padding: 9px 8px; }
  .rail-section { display: flex; flex-direction: column; gap: 6px; }
  .rail-seg button { flex: 1; padding: 6px 0; }
  .rail-quick { flex-direction: row; }
  .quick-link {
    flex: 1; border: 1px solid #2a2a2a; border-radius: 8px; background: #1a1a1a;
    color: #ccc; font: inherit; font-size: 12px; padding: 7px 0; cursor: pointer;
  }
  .quick-link:hover { background: #222; }
  .rail-calendar { border-top: 1px solid #1c1c1c; padding-top: 12px; }

  /* 手机滑动布局 → 三栏 grid；panes 宽度归 100%，关掉 transform */
  .panes {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 400px;
    width: 100%; transform: none !important; transition: none;
  }
  .panes.show-chat { transform: none; }
  .pane { width: auto; }
  .records-pane { grid-column: 1; }

  /* 折叠：聊天 pane 收为 0 宽并隐藏，主区占满 */
  .app.chat-hidden .panes { grid-template-columns: minmax(0, 1fr) 0px; }
  .app.chat-hidden .chat-pane { visibility: hidden; }

  /* 折叠/展开把手 */
  .chat-restorer {
    position: fixed; right: 0; top: 50%; transform: translateY(-50%);
    width: 26px; height: 64px; border: 1px solid #2a2a2a; border-right: none;
    border-radius: 8px 0 0 8px; background: #1a1a1a; color: #999;
    font: inherit; font-size: 15px; cursor: pointer; z-index: 90;
  }
  .chat-restorer:hover { color: #e0e0e0; }

  /* 主区内容限宽居中，避免超宽屏拉伸 */
  .records-pane > .topbar { max-width: 1080px; width: 100%; margin: 0 auto; }
  .records-pane > .scroll {
    max-width: 1080px; width: 100%; margin: 0 auto;
    padding: 0 20px 20px;
  }

  /* 桌面：日/周时间轴卡片双列排布（参考旧版 PC 布局） */
  .records-pane > .scroll :deep(.day-group),
  .records-pane > .scroll :deep(.week-timeline) {
    display: grid; grid-template-columns: 1fr 1fr; gap: 0 10px;
  }
  .records-pane > .scroll :deep(.day-group > .meal-card),
  .records-pane > .scroll :deep(.week-timeline > .meal-card) { margin-bottom: 10px; }
  /* 单卡日期也保持同样列宽，不留半行空白 */
  .records-pane > .scroll :deep(.day-group > .meal-card:last-child:nth-child(odd)),
  .records-pane > .scroll :deep(.week-timeline > .meal-card:last-child:nth-child(odd)) {
    grid-column: auto; width: auto;
  }
  /* 日期分隔线不属于 day-group，保持单列横贯：无调整 */
}
</style>
