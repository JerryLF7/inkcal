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
const photoCount = computed(() => (r.value.photos || []).length);

// 根据 emoji 数量自适应字号，确保 1~3+ 个 emoji 在 96px 缩略图框内饱满且不溢出
const emojiFontSize = computed(() => {
  const e = (r.value?.emoji || '').trim();
  if (!e) return '36px';
  const len = Array.from(e).length;
  if (len <= 1) return '38px';
  if (len === 2) return '30px';
  if (len === 3) return '24px';
  return '20px';
});

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
    <div class="thumb-wrap">
      <img v-if="thumb" class="thumb" :src="thumb" loading="lazy" alt="" @error="retryImg">
      <div v-else class="thumb thumb-empty" :style="{ fontSize: emojiFontSize }">{{ r.emoji || '🍽️' }}</div>
      <span v-if="photoCount > 1" class="photo-badge" :title="photoCount + ' 张照片，已合并为一餐'">×{{ photoCount }}</span>
    </div>
    <div class="body">
      <div class="meal-name">{{ r.meal }}</div>
      <div v-if="r.meal_detail" class="meal-detail">{{ r.meal_detail }}</div>
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
  display: flex; gap: 14px; align-items: center;
  background: #1a1a1a; border: 1px solid #242424;
  border-radius: 14px; padding: 12px; margin-bottom: 10px;
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

.thumb-wrap { position: relative; width: 96px; height: 96px; flex: none; }
.thumb {
  width: 96px; height: 96px; border-radius: 10px; object-fit: cover;
  flex: none; background: #2a2a2a;
}
.photo-badge {
  position: absolute; bottom: 3px; right: 3px;
  background: rgba(0,0,0,0.7); color: #fff;
  font-size: 10px; font-weight: 600; line-height: 1;
  padding: 2px 5px; border-radius: 6px;
}
.thumb-empty {
  display: flex; align-items: center; justify-content: center;
  line-height: 1.2; text-align: center; padding: 6px;
  word-break: break-all; letter-spacing: 1px;
}

.body { flex: 1; min-width: 0; }
.meal-name {
  font-size: 15px; font-weight: 600; margin-bottom: 3px; color: #e0e0e0;
  white-space: normal; word-break: break-word;
}
.meal-detail {
  font-size: 12px; color: #999; line-height: 1.45; margin-bottom: 3px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; word-break: break-word;
}
.meal-meta { font-size: 11px; color: #666; }
.meal-meta .source { color: #555; }
.meal-meta .agent-mark { cursor: help; }
.macros { font-size: 11px; color: #777; margin-top: 3px; }
.macros span { white-space: nowrap; }
.macros .p { color: #51cf66; }
.macros .c { color: #ffd43b; }
.macros .f { color: #ff922b; }

.meal-right { flex: none; align-self: center; padding-right: 4px; }
.meal-cals { font-size: 18px; font-weight: 700; color: #fff; }
.meal-cals small { font-size: 11px; font-weight: 400; color: #888; }
</style>
