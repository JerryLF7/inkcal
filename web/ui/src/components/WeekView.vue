<script setup>
import { ref, computed, onMounted, watch } from 'vue';
import {
  API, fmtDate, parseDate, hktNow, mondayOf, addDays,
  shortDate, weekdayLabel, tdeeOf, deficitOf,
} from '../utils/format.js';
import { store } from '../store.js';
import MealCard from './MealCard.vue';

const emit = defineEmits(['open', 'title']);

const monday = ref(mondayOf(hktNow()));
const data = ref(null);
const loading = ref(true);

const dayNames = ['一', '二', '三', '四', '五', '六', '日'];
const todayStr = fmtDate(hktNow());

function hasMacros(s) {
  return s && (s.protein || s.carbs || s.fat);
}

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

// 双层柱状图：底层 = 当日总消耗 TDEE，上层 = 摄入；摄入超过 TDEE 变红
const chartDays = computed(() => {
  if (!data.value) return [];
  const dates = Object.keys(data.value.by_day).sort();
  const rows = dates.map(d => {
    const day = data.value.by_day[d];
    const kcal = day.summary.calories;
    const burn = tdeeOf(day.burn, store.bmr);
    return { date: d, kcal, burn };
  });
  const max = Math.max(...rows.map(r => Math.max(r.kcal, r.burn)), 1);
  return rows.map(r => ({
    ...r,
    label: dayNames[(parseDate(r.date).getDay() + 6) % 7],
    height: r.kcal > 0 ? Math.max((r.kcal / max) * 100, 2) : 0,
    burnHeight: Math.max((r.burn / max) * 100, 2),
    over: r.kcal > r.burn,
    none: r.kcal === 0,
  }));
});

// 本周已记录天数 / 日均 / 累计缺口（仅统计有记录的天，未记录视为漏记不计入）
const weekStats = computed(() => {
  if (!data.value) return { days: 0, avg: 0, deficit: 0 };
  const dates = Object.keys(data.value.by_day);
  const recorded = dates.filter(d => data.value.by_day[d].records.length > 0);
  const total = data.value.summary.calories || 0;
  const deficit = recorded.reduce((s, d) => {
    const day = data.value.by_day[d];
    return s + deficitOf(day.summary.calories, day.burn, store.bmr);
  }, 0);
  return {
    days: recorded.length,
    avg: recorded.length ? Math.round(total / recorded.length) : 0,
    deficit: Math.round(deficit),
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
      summary: data.value.by_day[d].summary,
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
        <div v-for="d in chartDays" :key="d.date" class="wbar" :title="`${shortDate(d.date)} · 摄入 ${Math.round(d.kcal).toLocaleString()} / 消耗 ${Math.round(d.burn).toLocaleString()} kcal`">
          <div class="bars">
            <div class="burn" :style="{ height: d.burnHeight + '%' }"></div>
            <div
              class="bar"
              :class="{ over: d.over, none: d.none }"
              :style="d.none ? {} : { height: d.height + '%' }"
            ></div>
          </div>
          <div class="dl">{{ d.label }}</div>
        </div>
      </div>
      <div class="week-sum-row">
        <button class="wk-arrow" @click="shiftWeek(-1)">‹</button>
        <div class="week-sum">
          本周已记录 <b>{{ weekStats.days }}</b> 天 · 日均 <b>{{ weekStats.avg.toLocaleString() }}</b> kcal ·
          <template v-if="weekStats.days">
            累计<b class="def-num" :class="{ neg: weekStats.deficit < 0 }">{{ weekStats.deficit < 0 ? '盈余' : '缺口' }} {{ Math.abs(weekStats.deficit).toLocaleString() }}</b> kcal
          </template>
        </div>
        <button class="wk-arrow" :disabled="isCurrentWeek" @click="shiftWeek(1)">›</button>
      </div>

      <div v-if="!timeline.length" class="hint">本周暂无记录</div>
      <template v-for="day in timeline" :key="day.date">
        <div class="date-sep">
          <div class="sep-date">
            {{ day.date === todayStr ? '今天 · ' + weekdayLabel(day.date) : shortDate(day.date) + ' · ' + weekdayLabel(day.date) }}
          </div>
          <div class="sep-summary">
            <span v-if="hasMacros(day.summary)" class="sep-macros">
              <span class="p">P {{ Math.round(day.summary.protein) }}</span> ·
              <span class="c">C {{ Math.round(day.summary.carbs) }}</span> ·
              <span class="f">F {{ Math.round(day.summary.fat) }}</span>
            </span>
            <span class="sep-cals" :class="{ over: day.summary.calories > tdeeOf(data.by_day[day.date].burn, store.bmr) }">
              {{ Math.round(day.summary.calories).toLocaleString() }}<small> kcal</small>
            </span>
          </div>
        </div>
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
.wbar .bars {
  position: relative; width: 100%; flex: 1;
  display: flex; align-items: flex-end; justify-content: center;
}
.wbar .burn {
  position: absolute; bottom: 0; left: 0; right: 0;
  background: #2c313a; border-radius: 4px 4px 0 0;
}
.wbar .bar { position: relative; width: 55%; border-radius: 4px 4px 0 0; background: #2a6eff; }
.wbar .bar.over { background: #ff6b6b; }
.wbar .bar.none { background: #2a2a2a; height: 3px; }
.wbar .dl { font-size: 10px; color: #666; }

.week-sum .def-num { color: #4cda8b; }
.week-sum .def-num.neg { color: #ff6b6b; }

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
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 10px 0 6px;
  background: linear-gradient(#0f0f0f 75%, transparent);
}

.sep-date {
  font-size: 12px; color: #888; font-weight: 500;
}

.sep-summary {
  display: flex; align-items: baseline; gap: 8px;
}

.sep-macros {
  font-size: 11px; color: #777;
}
.sep-macros .p { color: #51cf66; }
.sep-macros .c { color: #ffd43b; }
.sep-macros .f { color: #ff922b; }

.sep-cals {
  font-size: 13px; font-weight: 700; color: #e0e0e0;
}
.sep-cals small {
  font-size: 10px; font-weight: 400; color: #888;
}
.sep-cals.over {
  color: #ff6b6b;
}
.hint { text-align: center; color: #888; font-size: 14px; padding: 40px 0; }
</style>
