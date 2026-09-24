<script setup>
import { ref, computed, onMounted, watch } from 'vue';
import { API, fmtDate, hktNow, tdeeOf } from '../utils/format.js';
import { store } from '../store.js';

const emit = defineEmits(['title', 'select']);

// compact：PC 左栏常驻日历模式（隐藏大标题/图例，格子紧凑，不占满主区）
const props = defineProps({
  compact: { type: Boolean, default: false },
});

const now0 = hktNow();
const cursor = ref(new Date(now0.getFullYear(), now0.getMonth(), 1));
const kcalByDay = ref({});   // { 'YYYY-MM-DD': kcal }
const burnByDay = ref({});   // { 'YYYY-MM-DD': burn 行（active_kcal/steps/source） }
const loading = ref(true);

const dayNames = ['一', '二', '三', '四', '五', '六', '日'];
const todayStr = fmtDate(hktNow());

const isCurrentMonth = computed(() => {
  const n = hktNow();
  return cursor.value.getFullYear() === n.getFullYear()
      && cursor.value.getMonth() === n.getMonth();
});

function shiftMonth(delta) {
  const m = new Date(cursor.value.getFullYear(), cursor.value.getMonth() + delta, 1);
  if (m > hktNow()) return;   // 不看未来月
  cursor.value = m;
  load();
}

async function load() {
  loading.value = true;
  try {
    const y = cursor.value.getFullYear(), m = cursor.value.getMonth();
    const start = fmtDate(new Date(y, m, 1));
    const end = fmtDate(new Date(y, m + 1, 0));
    const r = await fetch(`${API}/api/records?start=${start}&end=${end}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const map = {};
    for (const rec of data.records || []) {
      map[rec.date] = (map[rec.date] || 0) + (rec.calories || 0);
    }
    kcalByDay.value = map;
    burnByDay.value = data.burns || {};
    emitTitle();
  } catch { /* 保留旧数据 */ }
  finally { loading.value = false; }
}

function emitTitle() {
  if (props.compact) return;   // 左栏模式不向顶栏上报标题
  emit('title', {
    main: `${cursor.value.getFullYear()}年${cursor.value.getMonth() + 1}月`,
    sub: '',
  });
}

// 日历格子：周一起；每日热量环 = 当日 kcal / 当日 TDEE（无体征时退固定目标）
const cells = computed(() => {
  const y = cursor.value.getFullYear(), m = cursor.value.getMonth();
  const firstDow = (new Date(y, m, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(y, m + 1, 0).getDate();
  const out = [];
  for (let i = 0; i < firstDow; i++) out.push({ blank: true, key: 'b' + i });
  for (let d = 1; d <= daysInMonth; d++) {
    const ds = fmtDate(new Date(y, m, d));
    const kcal = kcalByDay.value[ds] || 0;
    const pct = kcal / tdeeOf(burnByDay.value[ds], store.bmr);
    out.push({
      key: ds, day: d, ds, kcal,
      today: ds === todayStr,
      ring: kcal > 0 ? {
        dash: (Math.min(pct, 1) * 97.4).toFixed(1),
        cls: pct > 1 ? 'over' : 'ok',   // 二值缺口语义：绿 = 有缺口，红 = 超消耗
      } : null,
    });
  }
  return out;
});

onMounted(load);
watch(() => store.bump, load);

defineExpose({ reload: load });
</script>

<template>
  <div class="scroll" :class="{ compact }">
    <div class="cal-head">
      <button @click="shiftMonth(-1)">‹</button>
      <div class="m">{{ cursor.getFullYear() }}年{{ cursor.getMonth() + 1 }}月</div>
      <button :disabled="isCurrentMonth" @click="shiftMonth(1)">›</button>
    </div>
    <div class="cal-grid">
      <div v-for="w in dayNames" :key="w" class="cal-wd">{{ w }}</div>
      <div
        v-for="c in cells"
        :key="c.key"
        class="cal-day"
        :class="{ dim: c.blank, today: c.today, filled: !!c.ring }"
        @click="!c.blank && emit('select', c.ds)"
      >
        <svg v-if="c.ring" class="ring" viewBox="0 0 36 36">
          <circle class="bg" cx="18" cy="18" r="15.5" fill="none" stroke-width="2.8"/>
          <circle
            :class="c.ring.cls" cx="18" cy="18" r="15.5" fill="none" stroke-width="2.8"
            :stroke-dasharray="c.ring.dash + ' 97.4'" stroke-linecap="round"
          />
        </svg>
        <span v-if="!c.blank" class="num">{{ c.day }}</span>
      </div>
    </div>
    <div v-if="!compact" class="cal-legend">
      <span><i style="background:#4cda8b"></i>有缺口</span>
      <span><i style="background:#ff6b6b"></i>超消耗</span>
    </div>
    <div v-if="loading" class="hint">加载中...</div>
  </div>
</template>

<style scoped>
.scroll { flex: 1; overflow-y: auto; padding: 0 14px 14px; scrollbar-width: none; }
.scroll::-webkit-scrollbar { display: none; }

.cal-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 4px; }
.cal-head .m { font-size: 14px; font-weight: 600; color: #e0e0e0; }
.cal-head button {
  background: none; border: none; color: #888; font-size: 18px;
  cursor: pointer; padding: 2px 10px; font-family: inherit;
}
.cal-head button:disabled { color: #3d3d3d; cursor: default; }

.cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; }
.cal-wd { text-align: center; font-size: 11px; color: #666; padding: 4px 0; }
.cal-day {
  aspect-ratio: 1; display: flex; align-items: center; justify-content: center;
  position: relative; border-radius: 10px; cursor: pointer; font-size: 13px; color: #ccc;
}
.cal-day:hover { background: #1e1e1e; }
.cal-day.dim { cursor: default; background: none; }
.cal-day.today .num { color: #2a6eff; font-weight: 700; }
.cal-day svg.ring {
  position: absolute; top: 50%; left: 50%;
  width: calc(100% - 4px); height: calc(100% - 4px);
  transform: translate(-50%, -50%) rotate(-90deg);
  pointer-events: none;
}
.ring .bg { stroke: #222; }
.ring .ok { stroke: #4cda8b; }
.ring .over { stroke: #ff6b6b; }

.cal-day .num {
  position: relative; z-index: 1; line-height: 1;
  display: inline-flex; align-items: center; justify-content: center;
  transform: translateY(-0.5px);
}

/* 有记录的格子：数字提亮加粗，与空格子拉开对比 */
.cal-day.filled .num { color: #e0e0e0; font-weight: 600; }

.cal-legend {
  display: flex; gap: 14px; justify-content: center;
  font-size: 11px; color: #777; padding: 12px 0 4px;
}
.cal-legend i {
  display: inline-block; width: 8px; height: 8px;
  border-radius: 50%; margin-right: 4px;
}

.hint { text-align: center; color: #888; font-size: 14px; padding: 20px 0; }

/* 左栏常驻日历（compact）：紧凑排版，无滚动占位 */
.scroll.compact { flex: none; overflow: visible; padding: 0; }
.scroll.compact .cal-head { padding: 2px 0 8px; }
.scroll.compact .cal-head .m { font-size: 13px; }
.scroll.compact .cal-grid { gap: 2px; }
.scroll.compact .cal-wd { font-size: 10px; padding: 2px 0; }
.scroll.compact .cal-day { aspect-ratio: 1; height: auto; min-height: unset; font-size: 12px; border-radius: 8px; }
.scroll.compact .hint { padding: 10px 0; }
</style>
