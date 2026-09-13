<script setup>
import { ref, computed, onMounted, watch } from 'vue';
import {
  API, DAILY_TARGET_KCAL, fmtDate, parseDate, hktNow, mondayOf, addDays,
  shortDate, weekdayLabel,
} from '../utils/format.js';
import { store } from '../store.js';
import MealCard from './MealCard.vue';

const emit = defineEmits(['open', 'title']);

const monday = ref(mondayOf(hktNow()));
const data = ref(null);
const loading = ref(true);

const dayNames = ['一', '二', '三', '四', '五', '六', '日'];

const isCurrentWeek = computed(() =>
  fmtDate(monday.value) >= fmtDate(mondayOf(hktNow()))
);

async function load() {
  loading.value = true;
  try {
    const r = await fetch(`${API}/api/week?start=${fmtDate(monday.value)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    data.value = await r.json();
    emitTitle();
  } catch { /* 保留旧数据 */ }
  finally { loading.value = false; }
}

function emitTitle() {
  if (!data.value) return;
  const s = parseDate(data.value.start);
  const e = parseDate(data.value.end);
  emit('title', {
    main: isCurrentWeek.value ? '本周' : shortDate(data.value.start),
    sub: `${s.getMonth() + 1}.${s.getDate()} – ${e.getMonth() + 1}.${e.getDate()}`,
  });
}

// 上一周 / 下一周（参考旧版 shiftWeek：不允许未来周）
function shiftWeek(delta) {
  const m = addDays(monday.value, delta * 7);
  if (m > mondayOf(hktNow())) return;
  monday.value = m;
  load();
}

const chartDays = computed(() => {
  if (!data.value) return [];
  const dates = Object.keys(data.value.by_day).sort();
  const vals = dates.map(d => data.value.by_day[d].summary.calories);
  const max = Math.max(DAILY_TARGET_KCAL * 1.15, ...vals, 1);
  return dates.map((d, i) => ({
    date: d,
    kcal: vals[i],
    label: dayNames[(parseDate(d).getDay() + 6) % 7],
    height: vals[i] > 0 ? Math.max((vals[i] / max) * 100, 2) : 0,
    over: vals[i] > DAILY_TARGET_KCAL,
    none: vals[i] === 0,
  }));
});

// 本周已记录天数 / 日均
const weekStats = computed(() => {
  if (!data.value) return { days: 0, avg: 0 };
  const dates = Object.keys(data.value.by_day);
  const recorded = dates.filter(d => data.value.by_day[d].records.length > 0);
  const total = data.value.summary.calories || 0;
  return {
    days: recorded.length,
    avg: recorded.length ? Math.round(total / recorded.length) : 0,
  };
});

// 餐卡时间轴：新日期在前，每日内最新记录在前
const timeline = computed(() => {
  if (!data.value) return [];
  return Object.keys(data.value.by_day)
    .filter(d => data.value.by_day[d].records.length > 0)
    .sort((a, b) => (a < b ? 1 : -1))
    .map(d => ({
      date: d,
      records: [...data.value.by_day[d].records].sort((a, b) =>
        (b.photo_time || '').localeCompare(a.photo_time || '') ||
        (b.asset_id || '').localeCompare(a.asset_id || '')
      ),
    }));
});

onMounted(load);
watch(() => store.bump, load);

// 回到当前周（左栏“本周”快捷键）
function resetToCurrentWeek() {
  monday.value = mondayOf(hktNow());
  load();
}

defineExpose({ reload: load, resetToCurrentWeek });
</script>

<template>
  <div class="scroll">
    <div v-if="loading && !data" class="hint">加载中...</div>
    <template v-else-if="data">
      <div class="week-chart">
        <div v-for="d in chartDays" :key="d.date" class="wbar">
          <div
            class="bar"
            :class="{ over: d.over, none: d.none }"
            :style="d.none ? {} : { height: d.height + '%' }"
          ></div>
          <div class="dl">{{ d.label }}</div>
        </div>
      </div>
      <div class="week-sum-row">
        <button class="wk-arrow" @click="shiftWeek(-1)">‹</button>
        <div class="week-sum">
          本周已记录 <b>{{ weekStats.days }}</b> 天 · 日均 <b>{{ weekStats.avg.toLocaleString() }}</b> kcal / 目标 {{ DAILY_TARGET_KCAL.toLocaleString() }}
        </div>
        <button class="wk-arrow" :disabled="isCurrentWeek" @click="shiftWeek(1)">›</button>
      </div>

      <div v-if="!timeline.length" class="hint">本周暂无记录</div>
      <template v-for="day in timeline" :key="day.date">
        <div class="date-sep">{{ shortDate(day.date) }} · {{ weekdayLabel(day.date) }}</div>
        <div class="week-timeline">
          <MealCard
            v-for="r in day.records"
            :key="r.asset_id"
            :record="r"
            @open="emit('open', $event)"
          />
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.scroll { flex: 1; overflow-y: auto; padding: 0 14px 14px; scrollbar-width: none; }
.scroll::-webkit-scrollbar { display: none; }

.week-chart {
  display: flex; align-items: flex-end; gap: 8px; height: 120px;
  background: #1a1a1a; border: 1px solid #242424; border-radius: 14px;
  padding: 14px 14px 8px; margin: 10px 0;
}
.wbar {
  flex: 1; display: flex; flex-direction: column; align-items: center;
  gap: 6px; height: 100%; justify-content: flex-end;
}
.wbar .bar { width: 60%; border-radius: 4px 4px 0 0; background: #2a6eff; }
.wbar .bar.over { background: #ff6b6b; }
.wbar .bar.none { background: #2a2a2a; height: 3px; }
.wbar .dl { font-size: 10px; color: #666; }

.week-sum-row { display: flex; align-items: center; gap: 4px; margin-bottom: 6px; }
.wk-arrow {
  background: none; border: none; color: #888; font-size: 18px;
  cursor: pointer; padding: 2px 10px; flex: none; font-family: inherit;
}
.wk-arrow:disabled { color: #3d3d3d; cursor: default; }
.week-sum { flex: 1; font-size: 12px; color: #888; text-align: center; }
.week-sum b { color: #e0e0e0; }

.date-sep {
  position: sticky; top: 0; z-index: 2;
  font-size: 12px; color: #888; padding: 10px 0 6px;
  background: linear-gradient(#0f0f0f 75%, transparent);
}
.hint { text-align: center; color: #888; font-size: 14px; padding: 40px 0; }
</style>
