<script setup>
import { computed } from 'vue';
import {
  SOURCE_LABELS, CONF_TITLES,
  fmtTimeHM, cardImageSrc, sourceTypeOf,
} from '../utils/format.js';
import { decisionFor, ACTION_LABELS, RELATION_LABELS } from '../store.js';

const props = defineProps({
  record: { type: Object, required: true },
  // chat 变体：嵌在 Luna 对话 artifact 里，不响应点击
  interactive: { type: Boolean, default: true },
});
const emit = defineEmits(['open']);

const r = computed(() => props.record);
const conf = computed(() => r.value.confidence || 'low');
const srcLabel = computed(() => {
  const t = sourceTypeOf(r.value);
  return SOURCE_LABELS[t] || t;
});
const thumb = computed(() => cardImageSrc(r.value));
const hasMacros = computed(() => r.value.protein_g || r.value.carbs_g || r.value.fat_g);

// agent 记录的餐：🤖 角标（数据由 DayView/WeekView 按日期预取到 store）
const agentDecision = computed(() => decisionFor(r.value));
const agentMarkTitle = computed(() => {
  const d = agentDecision.value;
  if (!d) return '';
  const a = ACTION_LABELS[d.action] || d.action;
  const rel = RELATION_LABELS[d.relation] || d.relation || '';
  return `Luna 决策：${a}${rel ? ' · ' + rel : ''}`;
});

function retryImg(e) {
  const img = e.target;
  if (img.dataset.retried) return;
  img.dataset.retried = '1';
  setTimeout(() => { img.src = img.src; }, 1000);
}

function onClick() {
  if (props.interactive) emit('open', props.record);
}
</script>

<template>
  <div class="meal-card" :class="{ clickable: interactive }" @click="onClick">
    <div class="conf-indicator" :class="'conf-' + conf" :title="CONF_TITLES[conf] || ''"></div>
    <img v-if="thumb" class="thumb" :src="thumb" loading="lazy" alt="" @error="retryImg" @click.stop>
    <div v-else class="thumb thumb-empty">🍽️</div>
    <div class="body">
      <div class="meal-name">{{ r.meal }}</div>
      <div class="meal-meta">{{ fmtTimeHM(r.photo_time) }} <span class="source">· {{ srcLabel }}</span><span v-if="agentDecision" class="agent-mark" :title="agentMarkTitle"> · 🤖</span></div>
      <div v-if="hasMacros" class="macros">
        <span class="p">P {{ r.protein_g || 0 }}g</span> ·
        <span class="c">C {{ r.carbs_g || 0 }}g</span> ·
        <span class="f">F {{ r.fat_g || 0 }}g</span>
      </div>
    </div>
    <div class="meal-right">
      <div class="meal-cals">{{ r.calories || 0 }}<small> kcal</small></div>
    </div>
  </div>
</template>

<style scoped>
.meal-card {
  display: flex; gap: 12px; align-items: center;
  background: #1a1a1a; border: 1px solid #242424;
  border-radius: 14px; padding: 10px; margin-bottom: 10px;
  position: relative;
}
.meal-card.clickable { cursor: pointer; }
.meal-card.clickable:active { background: #222; }

.conf-indicator {
  position: absolute; top: 6px; right: 6px;
  width: 7px; height: 7px; border-radius: 50%;
}
.conf-high { background: #51cf66; }
.conf-medium { background: #ffd43b; }
.conf-low { background: #ff6b6b; }

.thumb {
  width: 64px; height: 64px; border-radius: 10px; object-fit: cover;
  flex: none; background: #2a2a2a;
}
.thumb-empty {
  display: flex; align-items: center; justify-content: center; font-size: 22px;
}

.body { flex: 1; min-width: 0; }
.meal-name {
  font-size: 14px; font-weight: 600; margin-bottom: 2px; color: #e0e0e0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.meal-meta { font-size: 11px; color: #666; }
.meal-meta .source { color: #555; }
.meal-meta .agent-mark { cursor: help; }
.macros { font-size: 11px; color: #777; margin-top: 3px; }
.macros .p { color: #51cf66; }
.macros .c { color: #ffd43b; }
.macros .f { color: #ff922b; }

.meal-right { flex: none; align-self: center; padding-right: 4px; }
.meal-cals { font-size: 18px; font-weight: 700; color: #fff; }
.meal-cals small { font-size: 11px; font-weight: 400; color: #888; }
</style>
