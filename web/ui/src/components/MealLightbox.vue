<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue';
import {
  API, SOURCE_LABELS, CONF_LABELS,
  fmtTimeHM, fmtPhotoTimeDetail, cardImageSrc, lightboxImageSrc, sourceTypeOf,
} from '../utils/format.js';
import {
  toast, touch, agentData, ensureDecisions,
  ACTION_LABELS, RELATION_LABELS,
} from '../store.js';

const props = defineProps({
  record: { type: Object, default: null },
});
const emit = defineEmits(['close', 'deleted']);

// ── 打开/重置：prop 拷贝进内部 rec，prop 只作打开信号 ────────────
// 单张移除后组会变（主行可能晋升），刷新由组件自己拉取并更新 rec。
const rec = ref(null);
const selectedId = ref('');

function open(r) {
  rec.value = r ? { ...r, photos: [...(r.photos || [])] } : null;
  selectedId.value = r ? r.asset_id : '';
  decisionOpen.value = false;
  disarmMeal();
  disarmPhoto();
  if (r && r.date) ensureDecisions(r.date);
}
watch(() => props.record, open);

// ── 照片列表：按拍摄时间排序（后端契约是主行在前，不是全序）──────
const photosList = computed(() => {
  if (!rec.value) return [];
  if (rec.value.photos?.length) {
    return [...rec.value.photos].sort((a, b) =>
      (a.photo_time || '').localeCompare(b.photo_time || ''));
  }
  // 防御：photos 缺失时退化为单图
  const r = rec.value;
  return [{
    asset_id: r.asset_id, thumbnail_url: r.thumbnail_url,
    photo_time: r.photo_time, meal: r.meal, calories: r.calories,
    protein_g: r.protein_g, carbs_g: r.carbs_g, fat_g: r.fat_g,
  }];
});

const currentIdx = computed(() =>
  photosList.value.findIndex(p => p.asset_id === selectedId.value));
const current = computed(() =>
  currentIdx.value >= 0 ? photosList.value[currentIdx.value] : null);
const isGroup = computed(() => photosList.value.length > 1);
const primaryId = computed(() => rec.value?.asset_id || '');
const imgSrc = computed(() => (current.value ? lightboxImageSrc(current.value) : ''));

const subLine = computed(() => {
  if (!rec.value) return '';
  const r = rec.value;
  const detailTime = fmtPhotoTimeDetail(r.photo_time);
  const confText = CONF_LABELS[r.confidence] || '';
  const t = sourceTypeOf(r);
  const srcLabel = SOURCE_LABELS[t] || t || '';
  return [detailTime, srcLabel, confText ? '置信度 ' + confText : ''].filter(Boolean).join(' · ');
});

// 形态判定：从行且数值全零 = 状态延续（8-29 事故教训：绝不显示 0 kcal）
function isFormA(p) {
  return p.asset_id !== primaryId.value &&
    !(p.calories || p.protein_g || p.carbs_g || p.fat_g);
}

// ── 导航：点选 / 步进 / 键盘 / 滑动 ──────────────────────────────
function select(p) { selectedId.value = p.asset_id; }

function step(d) {
  const n = photosList.value.length;
  if (n < 2) return;
  const i = currentIdx.value < 0 ? 0 : (currentIdx.value + d + n) % n;
  selectedId.value = photosList.value[i].asset_id;
}

function onKey(e) {
  if (!rec.value) return;
  if (e.key === 'Escape') emit('close');
  else if (e.key === 'ArrowLeft') step(-1);
  else if (e.key === 'ArrowRight') step(1);
}
onMounted(() => window.addEventListener('keydown', onKey));
onBeforeUnmount(() => window.removeEventListener('keydown', onKey));

let _sx = 0;
function onSwipeStart(e) { _sx = e.touches[0].clientX; }
function onSwipeEnd(e) {
  const dx = e.changedTouches[0].clientX - _sx;
  if (Math.abs(dx) > 40) step(dx < 0 ? 1 : -1);
}

function retryImg(e) {
  const img = e.target;
  if (img.dataset.retried) return;
  img.dataset.retried = '1';
  setTimeout(() => { img.src = img.src; }, 1000);
}

// ── AI 决策区块：匹配范围 = 组内全部照片 ─────────────────────────
const decisionOpen = ref(false);
const decisions = computed(() => {
  if (!rec.value) return [];
  const ids = new Set(rec.value.photos?.map(p => p.asset_id) || [rec.value.asset_id]);
  return (agentData.decisions[rec.value.date] || []).filter(d =>
    (d.asset_ids || []).some(a => ids.has(a)) || ids.has(d.target_asset_id));
});

function decisionLabel(d) {
  const a = ACTION_LABELS[d.action] || d.action;
  const rel = RELATION_LABELS[d.relation] || d.relation || '';
  return rel ? `${a} · ${rel}` : a;
}

// ── 共享删除请求 ─────────────────────────────────────────────────
function apiDelete(asset_id, mode) {
  return fetch(`${API}/api/record`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ asset_id, mode }),
  }).then(async r => {
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      throw new Error(data.error || `HTTP ${r.status}`);
    }
    return r.json();
  });
}

// ── 整餐删除（两步确认，mode="meal"）────────────────────────────
const armedMeal = ref(false);
const deletingMeal = ref(false);
let _armTimer = null;

function disarmMeal() { clearTimeout(_armTimer); armedMeal.value = false; }

function onDeleteMeal() {
  if (!rec.value || deletingMeal.value) return;
  if (!armedMeal.value) {
    armedMeal.value = true;
    _armTimer = setTimeout(disarmMeal, 3000);
    return;
  }
  disarmMeal();
  deletingMeal.value = true;
  apiDelete(rec.value.asset_id, 'meal')
    .then(() => {
      emit('deleted');
      emit('close');
      touch();
      toast('已删除整餐，照片不会再被同步');
    })
    .catch(err => toast('删除失败: ' + (err.message || '请重试'), 'error'))
    .finally(() => { deletingMeal.value = false; });
}

// ── 单张移除（行内两步确认，mode="photo"）────────────────────────
const armedPhoto = ref('');       // 已武装的 asset_id
const removingPhoto = ref('');    // 请求进行中的 asset_id
let _photoArmTimer = null;

function disarmPhoto() { clearTimeout(_photoArmTimer); armedPhoto.value = ''; }

function onRemovePhoto(p) {
  if (!rec.value || removingPhoto.value) return;
  if (armedPhoto.value !== p.asset_id) {
    armedPhoto.value = p.asset_id;
    clearTimeout(_photoArmTimer);
    _photoArmTimer = setTimeout(disarmPhoto, 3000);
    return;
  }
  disarmPhoto();
  removingPhoto.value = p.asset_id;
  apiDelete(p.asset_id, 'photo')
    .then(data => refreshGroup(data.promoted))
    .catch(err => toast('移除失败: ' + (err.message || '请重试'), 'error'))
    .finally(() => { removingPhoto.value = ''; });
}

// ── 原地刷新：移除后按新主行锚点重拉当天分组 ─────────────────────
async function refreshGroup(promoted) {
  const anchor = promoted || rec.value.asset_id;
  const knownIds = new Set(rec.value.photos.map(p => p.asset_id));
  try {
    const r = await fetch(`${API}/api/records?date=${rec.value.date}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    const groups = d.records || [];
    const g = groups.find(x => x.asset_id === anchor) ||
              groups.find(x => (x.photos || []).some(p => knownIds.has(p.asset_id)));
    if (!g) {                       // 边界：组已不存在（防御）
      emit('deleted');
      emit('close');
      touch();
      toast('已移除，该餐没有剩余照片');
      return;
    }
    rec.value = g;
    selectedId.value = g.asset_id;
    touch();
    // 形态 A 删主行 → 晋升行是 0 值，这餐变 0 kcal，提示用户重估
    const zeroed = promoted && !(g.calories || g.protein_g || g.carbs_g || g.fat_g);
    toast(zeroed
      ? '已移除主照片，这餐数值需要重新估算（可让 Luna 重分析）'
      : '已移除照片，记录已更新');
  } catch {
    toast('已移除，但刷新失败——关闭后页面会自动更新', 'error');
  }
}
</script>

<template>
  <div v-if="rec" class="lightbox" @click="emit('close')">
    <button class="lb-close" type="button" aria-label="关闭" @click="emit('close')">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none"
           stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <line x1="6" y1="6" x2="18" y2="18"/>
        <line x1="18" y1="6" x2="6" y2="18"/>
      </svg>
    </button>
    <div class="lb-inner" @click.stop>

      <!-- 图区：移动端在上，桌面端在左 -->
      <div class="lb-figure">
        <div class="lb-stage"
             @touchstart.passive="onSwipeStart" @touchend.passive="onSwipeEnd">
          <img v-if="imgSrc" class="lb-img" :src="imgSrc" alt="">
          <span v-if="isGroup && currentIdx >= 0" class="lb-count">
            {{ currentIdx + 1 }} / {{ photosList.length }}
          </span>
        </div>
        <div v-if="isGroup" class="lb-strip">
          <button v-for="p in photosList" :key="p.asset_id" type="button"
                  class="strip-thumb" :class="{ active: p.asset_id === selectedId }"
                  @click="select(p)">
            <img :src="cardImageSrc(p)" loading="lazy" alt="" @error="retryImg">
          </button>
        </div>
      </div>

      <!-- 信息栏：移动端在下，桌面端在右 400px -->
      <div class="lb-panel">
        <div class="lb-meal">{{ rec.meal }}</div>
        <div v-if="rec.meal_detail" class="lb-meal-detail">{{ rec.meal_detail }}</div>
        <div class="lb-stats">
          <span class="lb-cal">{{ rec.calories || 0 }}<small> kcal</small></span>
          <span class="p">P {{ rec.protein_g || 0 }}g</span>
          <span class="c">C {{ rec.carbs_g || 0 }}g</span>
          <span class="f">F {{ rec.fat_g || 0 }}g</span>
        </div>
        <div class="lb-sub">{{ subLine }}</div>

        <!-- 分行明细：仅多照片组显示 -->
        <div v-if="isGroup" class="lb-details">
          <div class="lb-details-title">照片明细</div>
          <div v-for="p in photosList" :key="p.asset_id"
               class="lb-row" :class="{ active: p.asset_id === selectedId }"
               @click="select(p)">
            <img class="row-thumb" :src="cardImageSrc(p)" loading="lazy" alt="" @error="retryImg">
            <div class="row-body">
              <div class="row-time">{{ fmtTimeHM(p.photo_time) }}</div>
              <div v-if="isFormA(p)" class="row-merged">已并入整餐估算</div>
              <template v-else>
                <div class="row-name">{{ p.meal || '?' }}</div>
                <div v-if="p.meal_detail" class="row-detail">{{ p.meal_detail }}</div>
                <div class="row-values">
                  {{ p.calories || 0 }} kcal ·
                  <span class="p">P{{ p.protein_g || 0 }}</span>
                  <span class="c">C{{ p.carbs_g || 0 }}</span>
                  <span class="f">F{{ p.fat_g || 0 }}</span>
                </div>
              </template>
            </div>
            <button class="row-remove" type="button"
                    :class="{ armed: armedPhoto === p.asset_id }"
                    :disabled="!!removingPhoto"
                    @click.stop="onRemovePhoto(p)">
              {{ removingPhoto === p.asset_id ? '…' : armedPhoto === p.asset_id ? '确认?' : '✕' }}
            </button>
          </div>
        </div>

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
          <button class="lb-delete" :class="{ armed: armedMeal }" :disabled="deletingMeal" @click="onDeleteMeal">
            {{ deletingMeal ? '删除中…' : armedMeal ? '确认删除整餐？' : '删除整餐' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lightbox {
  position: fixed; inset: 0; z-index: 210;
  background: rgba(0,0,0,0.92);
  overflow-y: auto;
  display: flex; justify-content: center;
  padding: 20px;
}
.lb-close {
  position: fixed; top: 14px; right: 16px; z-index: 1;
  width: 34px; height: 34px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  border: 1px solid #2a2a2a; background: rgba(26,26,26,0.85);
  color: #999; cursor: pointer; padding: 0; font: inherit;
}
.lb-close:hover { color: #e0e0e0; background: #222; }
.lb-inner {
  width: 100%; max-width: 420px;
  display: flex; flex-direction: column; gap: 14px;
}

/* ── 图区 ── */
.lb-stage { position: relative; display: flex; justify-content: center; }
.lb-img {
  max-width: 100%; max-height: 62vh; border-radius: 12px; object-fit: contain;
}
.lb-count {
  position: absolute; bottom: 10px; right: 10px;
  background: rgba(0,0,0,0.6); color: #ccc;
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
}
.lb-strip { display: flex; gap: 6px; overflow-x: auto; }
.strip-thumb {
  width: 48px; height: 48px; flex: none; padding: 0;
  border: 2px solid transparent; border-radius: 10px;
  background: #222; cursor: pointer; overflow: hidden;
}
.strip-thumb.active { border-color: #fff; }
.strip-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }

/* ── 信息栏 ── */
.lb-meal { font-size: 17px; font-weight: 600; color: #e0e0e0; margin-bottom: 6px; }
.lb-meal-detail {
  font-size: 13px; color: #999; line-height: 1.55;
  margin: -2px 0 8px; word-break: break-word;
}
.lb-stats { display: flex; gap: 12px; align-items: baseline; font-size: 13px; }
.lb-cal { font-size: 22px; font-weight: 700; color: #fff; }
.lb-cal small { font-size: 12px; font-weight: 400; color: #888; }
.lb-stats .p { color: #51cf66; }
.lb-stats .c { color: #ffd43b; }
.lb-stats .f { color: #ff922b; }
.lb-sub { font-size: 12px; color: #777; margin-top: 6px; }

/* 分行明细 */
.lb-details { margin-top: 4px; }
.lb-details-title { font-size: 11px; color: #666; margin-bottom: 6px; }
.lb-row {
  display: flex; gap: 10px; align-items: center;
  background: #141414; border: 1px solid #242424; border-radius: 10px;
  padding: 8px; margin-bottom: 6px; cursor: pointer;
}
.lb-row.active { border-color: #2a6eff; }
.row-thumb {
  width: 40px; height: 40px; border-radius: 8px;
  object-fit: cover; flex: none; background: #222;
}
.row-body { flex: 1; min-width: 0; }
.row-time { font-size: 10px; color: #777; margin-bottom: 2px; }
.row-name { font-size: 13px; color: #ddd; }
.row-detail {
  font-size: 11px; color: #888; line-height: 1.4; margin-top: 1px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; word-break: break-word;
}
.row-merged { font-size: 12px; color: #888; }
.row-values { font-size: 11px; color: #999; margin-top: 2px; }
.row-values .p { color: #51cf66; }
.row-values .c { color: #ffd43b; }
.row-values .f { color: #ff922b; }
.row-remove {
  flex: none; margin-left: auto;
  width: 28px; height: 28px; border-radius: 8px;
  background: none; border: 1px solid #333; color: #888;
  font-size: 12px; cursor: pointer; white-space: nowrap;
  font-family: inherit;
}
.row-remove.armed { background: #ff6b6b; border-color: #ff6b6b; color: #fff; }
.row-remove:disabled { opacity: 0.6; cursor: not-allowed; }

/* AI 决策 */
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

/* ── 桌面端：左图右栏 ── */
@media (min-width: 1024px) {
  .lightbox { overflow: hidden; padding: 0; }
  .lb-close { position: absolute; }
  .lb-inner {
    flex-direction: row;            /* 主轴翻转：图左、栏右 */
    max-width: 1280px; width: 100%; height: 100%;
    align-items: stretch; gap: 32px;
    padding: 48px 56px;
  }
  .lb-figure {
    flex: 1 1 auto; min-width: 0;
    display: flex; flex-direction: column; justify-content: center; gap: 12px;
  }
  .lb-img { max-height: calc(100vh - 160px); }
  .lb-panel { width: 400px; flex: none; overflow-y: auto; }
}
</style>
