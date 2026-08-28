<script setup>
import { ref, nextTick, onMounted } from 'vue';
import DayView from './components/DayView.vue';
import WeekView from './components/WeekView.vue';
import MonthView from './components/MonthView.vue';
import MealLightbox from './components/MealLightbox.vue';
import PhotoPicker from './components/PhotoPicker.vue';
import { store, startDataVersionPolling } from './store.js';

// 双 pane：记录 / Luna 对话（原型 docs/prototypes/two-tab-proto.html）
const pane = ref('records');           // 'records' | 'chat'
const view = ref('day');               // 'day' | 'week' | 'month'

// 各视图各自上报顶栏标题；切换时恢复该视图最近一次上报的标题
const titles = {
  day: ref({ main: '', sub: '' }),
  week: ref({ main: '', sub: '' }),
  month: ref({ main: '', sub: '' }),
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
const lightboxRecord = ref(null);
const photoPickerOpen = ref(false);

function openLightbox(r) { lightboxRecord.value = r; }
function openPhotoPicker() { photoPickerOpen.value = true; }

// 月视图点日期 → 跳回日视图时间轴并定位
function onSelectDate(ds) {
  switchView('day');
  nextTick(() => { dayViewRef.value && dayViewRef.value.jumpTo(ds); });
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

onMounted(() => startDataVersionPolling());
</script>

<template>
  <div class="app">
    <div
      class="panes" :class="{ 'show-chat': pane === 'chat' }"
      @touchstart.passive="onTouchStart" @touchend.passive="onTouchEnd"
    >
      <!-- 左 pane：记录 -->
      <section class="pane">
        <div class="topbar">
          <div class="sticky-date">{{ title.main }}<small>{{ title.sub }}</small></div>
          <div class="record-actions">
            <button class="photo-button" type="button" aria-label="选择照片" @click="openPhotoPicker">选择照片</button>
            <div class="seg">
              <button
                v-for="v in [['day', '日'], ['week', '周'], ['month', '月']]"
                :key="v[0]"
                :class="{ active: view === v[0] }"
                @click="switchView(v[0])"
              >{{ v[1] }}</button>
            </div>
          </div>
        </div>

        <DayView
          v-show="view === 'day'" ref="dayViewRef"
          @open="openLightbox" @title="t => onTitle('day', t)"
        />
        <WeekView
          v-show="view === 'week'"
          @open="openLightbox" @title="t => onTitle('week', t)"
        />
        <MonthView
          v-show="view === 'month'"
          @select="onSelectDate" @title="t => onTitle('month', t)"
        />
      </section>

      <!-- 右 pane：Luna 对话（视觉按已交付原型落地；后端接线留待 Phase 5） -->
      <section class="pane">
        <div class="chat-top">
          <div class="sticky-date">Luna</div>
          <div class="chat-actions">
            <button type="button" aria-label="历史会话" title="历史会话">◷</button>
            <button type="button" aria-label="新建会话" title="新建会话">＋</button>
          </div>
        </div>
        <div class="chat-scroll">
          <div class="message luna">早。昨天中午的两张照片我判断为同一餐，已经合并记录：</div>
          <div class="meal-artifact">
            <div class="artifact-caption">8月26日 · 午餐</div>
            <div class="artifact-card">
              <div class="artifact-thumb"></div>
              <div class="artifact-body">
                <div class="artifact-meal">轻食三明治（两张合并）</div>
                <div class="artifact-calories">720 <small>kcal</small></div>
                <div class="artifact-macros"><span class="p">P 28g</span> · <span class="c">C 74g</span> · <span class="f">F 22g</span></div>
              </div>
            </div>
          </div>
          <div class="message user">比我前天中午吃的呢？</div>
          <div class="message luna">前天午餐是麻辣烫，约 680 kcal。昨天这餐碳水更高、脂肪更低，总热量接近。</div>
          <div class="confirm-card">
            <p>你说“删掉周一那顿麻辣烫”。确认删除 8月25日 19:10 的记录吗？</p>
            <div class="confirm-actions">
              <button type="button" class="confirm">确认删除</button>
              <button type="button">取消</button>
            </div>
          </div>
        </div>
        <form class="chat-input" @submit.prevent>
          <button class="chat-plus" type="button" aria-label="添加照片或附件">＋</button>
          <input aria-label="和 Luna 对话" placeholder="和 Luna 说说这顿吃了什么…">
        </form>
      </section>
    </div>

    <nav class="tabbar">
      <button :class="{ active: pane === 'records' }" @click="go('records')">
        <span class="ico">📖</span>记录
      </button>
      <button :class="{ active: pane === 'chat' }" @click="go('chat')">
        <span class="ico">💬</span>Luna
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

.chat-top {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px; border-bottom: 1px solid #1c1c1c; flex: none;
}
.chat-actions { display: flex; gap: 4px; }
.chat-actions button, .chat-plus {
  border: 0; background: transparent; color: #999; cursor: pointer; font: inherit;
}
.chat-actions button { width: 32px; height: 32px; font-size: 19px; }
.chat-scroll {
  flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column;
  gap: 12px; padding: 14px; scrollbar-width: none;
}
.chat-scroll::-webkit-scrollbar { display: none; }
.message {
  max-width: 82%; padding: 10px 13px; border-radius: 8px;
  font-size: 14px; line-height: 1.55;
}
.message.luna { align-self: flex-start; color: #dedede; background: #1a1a1a; border: 1px solid #242424; }
.message.user { align-self: flex-end; color: #fff; background: #2a6eff; }
.meal-artifact, .confirm-card {
  align-self: flex-start; width: min(88%, 360px); border: 1px solid #303030;
  border-radius: 8px; background: #1a1a1a; padding: 10px;
}
.artifact-caption { color: #777; font-size: 11px; margin-bottom: 8px; }
.artifact-card { display: flex; gap: 10px; }
.artifact-thumb { width: 60px; height: 60px; flex: none; border-radius: 6px; background: #30445f; }
.artifact-body { min-width: 0; }
.artifact-meal { color: #e4e4e4; font-size: 13px; font-weight: 600; }
.artifact-calories { color: #fff; font-size: 18px; font-weight: 700; margin-top: 3px; }
.artifact-calories small { color: #888; font-size: 11px; font-weight: 400; }
.artifact-macros { color: #777; font-size: 11px; margin-top: 3px; }
.p { color: #51cf66; } .c { color: #ffd43b; } .f { color: #ff922b; }
.confirm-card { border-color: #3a3a2a; }
.confirm-card p { margin: 0 0 10px; color: #d6d6d6; font-size: 13px; line-height: 1.5; }
.confirm-actions { display: flex; gap: 8px; }
.confirm-actions button {
  flex: 1; padding: 7px; border: 1px solid #3a3a3a; border-radius: 6px;
  background: #252525; color: #d0d0d0; font: inherit; font-size: 12px;
}
.confirm-actions .confirm { color: #fff; background: #2a6eff; border-color: #2a6eff; }
.chat-input {
  display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid #1c1c1c; background: #0f0f0f;
}
.chat-plus { width: 38px; height: 38px; flex: none; border: 1px solid #2a2a2a; border-radius: 50%; background: #1a1a1a; font-size: 20px; }
.chat-input input { min-width: 0; flex: 1; border: 1px solid #2a2a2a; border-radius: 19px; background: #1a1a1a; color: #ddd; padding: 0 14px; font: inherit; font-size: 13px; outline: none; }
.chat-input input:focus { border-color: #2a6eff; }

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

.toast {
  position: fixed; left: 50%; bottom: 84px; transform: translateX(-50%);
  background: #2a2a2a; color: #e0e0e0; font-size: 13px;
  padding: 10px 18px; border-radius: 20px; z-index: 300;
  max-width: 80%; text-align: center;
}
.toast.error { background: #4a1f1f; color: #ff8787; }
</style>
