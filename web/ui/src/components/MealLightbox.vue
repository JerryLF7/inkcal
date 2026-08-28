<script setup>
import { computed, ref, watch } from 'vue';
import {
  API, SOURCE_LABELS, CONF_LABELS,
  fmtPhotoTimeDetail, lightboxImageSrc, sourceTypeOf,
} from '../utils/format.js';
import {
  toast, touch, agentData, ensureDecisions,
  ACTION_LABELS, RELATION_LABELS,
} from '../store.js';

const props = defineProps({
  record: { type: Object, default: null },
});
const emit = defineEmits(['close', 'deleted']);

const imgSrc = computed(() => (props.record ? lightboxImageSrc(props.record) : ''));

// ── AI 决策区块：覆盖该记录的全部 agent 决策（审计透明化）────────
const decisions = computed(() => {
  if (!props.record) return [];
  const list = agentData.decisions[props.record.date] || [];
  return list.filter(d =>
    (d.asset_ids || []).includes(props.record.asset_id) ||
    d.target_asset_id === props.record.asset_id
  );
});
const decisionOpen = ref(false);

watch(() => props.record, (r) => {
  decisionOpen.value = false;
  if (r && r.date) ensureDecisions(r.date);
});

function decisionLabel(d) {
  const a = ACTION_LABELS[d.action] || d.action;
  const rel = RELATION_LABELS[d.relation] || d.relation || '';
  return rel ? `${a} · ${rel}` : a;
}

const subLine = computed(() => {
  if (!props.record) return '';
  const r = props.record;
  const detailTime = fmtPhotoTimeDetail(r.photo_time);
  const confText = CONF_LABELS[r.confidence] || '';
  const t = sourceTypeOf(r);
  const srcLabel = SOURCE_LABELS[t] || t || '';
  return [detailTime, srcLabel, confText ? '置信度 ' + confText : ''].filter(Boolean).join(' · ');
});

// ── 两步确认删除（参考旧版 deleteRecord）──────────────────────
const armed = ref(false);
const deleting = ref(false);
let _armTimer = null;

watch(() => props.record, () => disarm());

function disarm() {
  clearTimeout(_armTimer);
  armed.value = false;
}

function onDelete() {
  if (!props.record || deleting.value) return;
  if (!armed.value) {
    armed.value = true;
    _armTimer = setTimeout(disarm, 3000);
    return;
  }
  disarm();
  deleting.value = true;
  fetch(`${API}/api/record`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ asset_id: props.record.asset_id }),
  })
    .then(async r => {
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${r.status}`);
      }
      return r.json();
    })
    .then(data => {
      if (data.ok) {
        emit('close');
        touch();
        toast('已删除，该照片不会再被同步');
      }
    })
    .catch(err => {
      toast('删除失败: ' + (err.message || '请重试'), 'error');
    })
    .finally(() => { deleting.value = false; });
}
</script>

<template>
  <div v-if="record" class="lightbox" @click="emit('close')">
    <div class="lightbox-close" @click="emit('close')">✕</div>
    <img v-if="imgSrc" class="lightbox-img" :src="imgSrc" alt="" @click.stop>
    <div class="lightbox-meta" @click.stop>
      <div class="lb-meal">{{ record.meal }}</div>
      <div class="lb-stats">
        <span class="lb-cal">{{ record.calories || 0 }}<small> kcal</small></span>
        <span class="p">P {{ record.protein_g || 0 }}g</span>
        <span class="c">C {{ record.carbs_g || 0 }}g</span>
        <span class="f">F {{ record.fat_g || 0 }}g</span>
      </div>
      <div class="lb-sub">{{ subLine }}</div>
      <div v-if="decisions.length" class="ai-decision">
        <button class="ai-toggle" @click="decisionOpen = !decisionOpen">
          🤖 AI 决策 {{ decisionOpen ? '▾' : '▸' }}
        </button>
        <div v-if="decisionOpen" class="ai-body">
          <div v-for="d in decisions" :key="d.id" class="ai-item">
            <div class="ai-head">{{ decisionLabel(d) }}</div>
            <div v-if="d.reasoning" class="ai-reasoning">{{ d.reasoning }}</div>
            <div v-if="d.prompt_for_gemini" class="ai-prompt">
              <span class="ai-prompt-label">给 Gemini 的提示词</span>
              {{ d.prompt_for_gemini }}
            </div>
          </div>
        </div>
      </div>
      <div class="lb-actions">
        <button class="lb-delete" :class="{ armed }" :disabled="deleting" @click="onDelete">
          {{ deleting ? '删除中...' : armed ? '确认删除？' : '删除' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lightbox {
  position: fixed; inset: 0; z-index: 210;
  background: rgba(0,0,0,0.92);
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 20px;
}
.lightbox-close {
  position: absolute; top: 14px; right: 16px;
  color: #aaa; font-size: 22px; cursor: pointer; padding: 6px;
}
.lightbox-img {
  max-width: 100%; max-height: 62vh; border-radius: 12px; object-fit: contain;
}
.lightbox-meta { width: 100%; max-width: 420px; margin-top: 16px; }
.lb-meal { font-size: 17px; font-weight: 600; color: #e0e0e0; margin-bottom: 6px; }
.lb-stats { display: flex; gap: 12px; align-items: baseline; font-size: 13px; }
.lb-cal { font-size: 22px; font-weight: 700; color: #fff; }
.lb-cal small { font-size: 12px; font-weight: 400; color: #888; }
.lb-stats .p { color: #51cf66; }
.lb-stats .c { color: #ffd43b; }
.lb-stats .f { color: #ff922b; }
.lb-sub { font-size: 12px; color: #777; margin-top: 6px; }

.ai-decision { margin-top: 10px; }
.ai-toggle {
  background: none; border: none; color: #888; font-size: 12px;
  cursor: pointer; padding: 0; font-family: inherit;
}
.ai-body {
  margin-top: 8px; background: #141414; border: 1px solid #242424;
  border-radius: 10px; padding: 10px 12px;
}
.ai-item + .ai-item { margin-top: 10px; padding-top: 10px; border-top: 1px solid #242424; }
.ai-head { font-size: 12px; color: #2a6eff; margin-bottom: 4px; }
.ai-reasoning { font-size: 12px; color: #bbb; line-height: 1.6; white-space: pre-wrap; }
.ai-prompt { font-size: 11px; color: #777; line-height: 1.6; margin-top: 6px; white-space: pre-wrap; }
.ai-prompt-label {
  display: block; font-size: 10px; color: #555; margin-bottom: 2px;
}

.lb-actions { margin-top: 14px; display: flex; justify-content: flex-end; }
.lb-delete {
  background: none; border: 1px solid #ff6b6b33; color: #ff6b6b;
  border-radius: 8px; padding: 8px 16px; font-size: 13px;
  cursor: pointer; font-family: inherit;
}
.lb-delete.armed { background: #ff6b6b; border-color: #ff6b6b; color: #fff; }
.lb-delete:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
