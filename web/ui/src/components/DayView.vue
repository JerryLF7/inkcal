<script setup>
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue';
import {
  API, fmtDate, parseDate, hktNow, addDays,
  shortDate, weekdayLabel,
} from '../utils/format.js';
import { store } from '../store.js';
import MealCard from './MealCard.vue';

const emit = defineEmits(['open', 'title']);

const CHUNK_DAYS = 7;

const days = ref([]);          // [{ date, records, summary }]，新的在前
const loadedUntil = ref('');   // 已加载范围的最旧日期（含）
const minDate = ref('');       // /api/dates 里最早的日期
const loading = ref(false);
const initialLoading = ref(true);
const exhausted = ref(false);
const currentDate = ref(fmtDate(hktNow()));

const scrollEl = ref(null);
const sentinelEl = ref(null);

const todayStr = fmtDate(hktNow());

function groupRecords(recordList) {
  const byDate = new Map();
  for (const r of recordList) {
    if (!byDate.has(r.date)) byDate.set(r.date, []);
    byDate.get(r.date).push(r);
  }
  return [...byDate.entries()]
    .map(([date, records]) => ({
      date,
      records,
      summary: records.reduce((s, r) => s + (r.calories || 0), 0),
    }))
    .sort((a, b) => (a.date < b.date ? 1 : -1));
}

async function fetchRange(start, end) {
  const r = await fetch(`${API}/api/records?start=${start}&end=${end}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function loadAvailableDates() {
  try {
    const r = await fetch(`${API}/api/dates`);
    if (!r.ok) return;
    const dates = await r.json();
    minDate.value = dates.length ? dates[dates.length - 1] : '';
  } catch { /* 静默 */ }
}

async function loadChunk() {
  if (loading.value || exhausted.value) return;
  loading.value = true;
  try {
    const end = loadedUntil.value
      ? fmtDate(addDays(parseDate(loadedUntil.value), -1))
      : todayStr;
    if (minDate.value && end < minDate.value) { exhausted.value = true; return; }
    const start = fmtDate(addDays(parseDate(end), -(CHUNK_DAYS - 1)));
    const data = await fetchRange(start, end);
    days.value = days.value.concat(groupRecords(data.records || []));
    loadedUntil.value = start;
    if (minDate.value && loadedUntil.value <= minDate.value) exhausted.value = true;
  } catch { /* 下次滚动到底再试 */ }
  finally {
    loading.value = false;
    initialLoading.value = false;
    await nextTick();
    setupGroupObserver();
  }
}

async function reload() {
  // 重新拉取当前已加载的整个范围（data-version 变化 / 上传 / 删除后）
  if (!loadedUntil.value) { await loadChunk(); return; }
  try {
    const data = await fetchRange(loadedUntil.value, todayStr);
    days.value = groupRecords(data.records || []);
    await nextTick();
    setupGroupObserver();
  } catch { /* 保留旧数据 */ }
}

// 月视图点日期跳转：确保该日期所在范围已加载，然后滚动定位
async function jumpTo(ds) {
  let guard = 0;
  while ((!loadedUntil.value || loadedUntil.value > ds) && !exhausted.value && guard < 60) {
    await loadChunk();
    guard++;
  }
  await nextTick();
  const el = scrollEl.value && scrollEl.value.querySelector(`[data-group-date="${ds}"]`);
  if (el) {
    scrollEl.value.scrollTop = el.offsetTop - 8;
  } else {
    scrollEl.value && (scrollEl.value.scrollTop = 0);
  }
  currentDate.value = ds;
  emitTitle(ds);
}

// ── 顶栏日期：IntersectionObserver 监听日期组（分隔线只渲染在组间）──
let groupObserver = null;
const intersecting = new Set();

function setupGroupObserver() {
  if (groupObserver) groupObserver.disconnect();
  intersecting.clear();
  if (!scrollEl.value) return;
  groupObserver = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const ds = e.target.dataset.groupDate;
      if (e.isIntersecting) intersecting.add(ds);
      else intersecting.delete(ds);
    }
    // 取排序最前（最新）的相交组作为顶栏日期
    for (const day of days.value) {
      if (intersecting.has(day.date)) {
        if (day.date !== currentDate.value) {
          currentDate.value = day.date;
          emitTitle(day.date);
        }
        return;
      }
    }
  }, {
    root: scrollEl.value,
    rootMargin: '0px 0px -92% 0px',
    threshold: 0,
  });
  scrollEl.value.querySelectorAll('[data-group-date]').forEach(el => groupObserver.observe(el));
}

function emitTitle(ds) {
  const prefix = ds === todayStr ? '今天 · ' : '';
  emit('title', { main: prefix + shortDate(ds), sub: weekdayLabel(ds) });
}

// ── 触底加载更早 ─────────────────────────────────────────────
let sentinelObserver = null;

onMounted(async () => {
  await loadAvailableDates();
  await loadChunk();
  emitTitle(currentDate.value);
  sentinelObserver = new IntersectionObserver((entries) => {
    if (entries.some(e => e.isIntersecting)) loadChunk();
  }, { root: scrollEl.value, rootMargin: '200px' });
  if (sentinelEl.value) sentinelObserver.observe(sentinelEl.value);
});

onBeforeUnmount(() => {
  if (groupObserver) groupObserver.disconnect();
  if (sentinelObserver) sentinelObserver.disconnect();
});

watch(() => store.bump, async () => {
  await loadAvailableDates();
  await reload();
});

defineExpose({ jumpTo, reload });

const isEmpty = computed(() => !initialLoading.value && days.value.length === 0);
</script>

<template>
  <div ref="scrollEl" class="scroll">
    <div v-if="initialLoading" class="hint">加载中...</div>
    <div v-else-if="isEmpty" class="hint empty-hint">
      <div class="icon">🍽️</div>
      <p>暂无记录</p>
      <p class="sub">拍照后会自动同步，也可以手动选择照片</p>
    </div>

    <template v-for="day in days" :key="day.date">
      <div v-if="day.date !== todayStr" class="date-sep">{{ shortDate(day.date) }} · {{ weekdayLabel(day.date) }}</div>
      <div :data-group-date="day.date" class="day-group">
        <MealCard
          v-for="r in day.records"
          :key="r.asset_id"
          :record="r"
          @open="emit('open', $event)"
        />
      </div>
    </template>

    <div ref="sentinelEl" class="sentinel">
      <span v-if="loading">加载中...</span>
      <span v-else-if="exhausted && days.length">没有更早的记录了</span>
    </div>
  </div>
</template>

<style scoped>
.scroll {
  flex: 1; overflow-y: auto; padding: 0 14px 14px;
  scrollbar-width: none;
}
.scroll::-webkit-scrollbar { display: none; }

.date-sep {
  position: sticky; top: 0; z-index: 2;
  font-size: 12px; color: #888; padding: 10px 0 6px;
  background: linear-gradient(#0f0f0f 75%, transparent);
}

.hint { text-align: center; color: #888; font-size: 14px; padding: 40px 0; }
.empty-hint .icon { font-size: 40px; margin-bottom: 10px; }
.empty-hint p { margin: 4px 0; }
.empty-hint .sub { font-size: 12px; color: #666; }

.sentinel {
  text-align: center; color: #666; font-size: 12px; padding: 14px 0 6px;
  min-height: 20px;
}
</style>
