<script setup>
import { ref } from 'vue';
import MealCard from './MealCard.vue';
import { API, fmtTimeHM } from '../utils/format.js';
import { touch, toast } from '../store.js';

// 产物层：单个工具调用的最终结果卡片。
// 写操作永远展示；统计本身就是答案；查询结果仅在本轮无写操作时展示。
const props = defineProps({
  tool: { type: Object, required: true },
  msg: { type: Object, required: true },
});
const emit = defineEmits(['open']);

// ── 规范化 record 对象供 MealCard / Lightbox 使用 ─────────────
function normalizeRecord(r) {
  if (!r) return {};
  const photoTime = r.photo_time || '';
  const date = photoTime ? photoTime.slice(0, 10) : '';
  return {
    ...r,
    date,
    confidence: r.confidence || 'low',
    photos: r.photos?.length ? r.photos : [{
      asset_id: r.asset_id,
      photo_time: r.photo_time,
      meal: r.meal,
      meal_detail: r.meal_detail,
      calories: r.calories,
      thumbnail_url: r.thumbnail_url,
      replacement_image: r.replacement_image,
      emoji: r.emoji,
    }],
  };
}

// 写操作：其结果卡片是用户真正关心的产物，必须展示
const WRITE_TOOLS = new Set([
  'add_record', 'edit_record', 'reanalyze_record', 'request_delete_record',
]);

// 查询结果卡片只在本轮无写操作时展示（否则属内部参考步骤）
function recordsArtifactVisible() {
  if (!props.tool.result?.records?.length) return false;
  return !(props.msg.tool_log || []).some(t => WRITE_TOOLS.has(t.name));
}

// ── 删除确认卡处理（Phase 5 约束：绝不越过用户确认直接删除）──
const deletingAssetId = ref('');

async function handleDeleteRecord(toolResult) {
  const card = toolResult?.confirm_card;
  if (!card || !card.asset_id || deletingAssetId.value) return;

  deletingAssetId.value = card.asset_id;
  try {
    const res = await fetch(`${API}/api/record`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        asset_id: card.asset_id,
        mode: 'meal',
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      toast(err.error || '删除失败', 'error');
      return;
    }

    toolResult._status = 'confirmed';
    touch();
    toast('已删除记录');
  } catch (e) {
    toast('网络异常，删除失败', 'error');
  } finally {
    deletingAssetId.value = '';
  }
}

function handleCancelDelete(toolResult) {
  toolResult._status = 'canceled';
}
</script>

<template>
  <!-- 1. 添加记录后展示记录卡 (add_record) -->
  <div
    v-if="tool.name === 'add_record' && tool.result?.record"
    class="artifact"
  >
    <div class="artifact-caption">
      📝 已添加餐食记录：
    </div>
    <MealCard
      :record="normalizeRecord(tool.result.record)"
      :interactive="true"
      @open="emit('open', normalizeRecord(tool.result.record))"
    />
  </div>

  <!-- 2. 编辑/重新分析记录后展示更新卡 (edit_record / reanalyze_record) -->
  <div
    v-else-if="(tool.name === 'edit_record' || tool.name === 'reanalyze_record') && tool.result?.after"
    class="artifact"
  >
    <div class="artifact-caption">
      {{ tool.name === 'edit_record' ? '✏️ 已更新餐食记录：' : '🔄 已重新分析餐食记录：' }}
    </div>
    <MealCard
      :record="normalizeRecord(tool.result.after)"
      :interactive="true"
      @open="emit('open', normalizeRecord(tool.result.after))"
    />
  </div>

  <!-- 3. 删除确认卡 (request_delete_record) -->
  <div
    v-else-if="tool.name === 'request_delete_record' && tool.result?.confirm_card"
    class="confirm-card"
    :class="{
      'confirmed': tool.result._status === 'confirmed',
      'canceled': tool.result._status === 'canceled'
    }"
  >
    <template v-if="tool.result._status === 'confirmed'">
      <div class="confirm-done">✅ 已删除该餐记录</div>
    </template>
    <template v-else-if="tool.result._status === 'canceled'">
      <div class="confirm-canceled">已取消删除</div>
    </template>
    <template v-else>
      <div class="confirm-text">
        确认删除 <strong>{{ tool.result.confirm_card.meal || '该餐' }}</strong>（{{ fmtTimeHM(tool.result.confirm_card.photo_time) }}，{{ tool.result.confirm_card.calories }} kcal）吗？
      </div>
      <div class="confirm-actions">
        <button
          type="button"
          class="confirm-btn danger"
          :disabled="deletingAssetId === tool.result.confirm_card.asset_id"
          @click="handleDeleteRecord(tool.result)"
        >
          {{ deletingAssetId === tool.result.confirm_card.asset_id ? '删除中…' : '确认删除' }}
        </button>
        <button
          type="button"
          class="confirm-btn cancel"
          :disabled="deletingAssetId === tool.result.confirm_card.asset_id"
          @click="handleCancelDelete(tool.result)"
        >
          取消
        </button>
      </div>
    </template>
  </div>

  <!-- 4. 统计卡 (get_intake_stats)：本身就是答案，始终展示 -->
  <div
    v-else-if="tool.name === 'get_intake_stats' && tool.result?.total"
    class="stats-artifact"
  >
    <div class="stats-header">
      📊 {{ tool.args?.start || '' }} 至 {{ tool.args?.end || '' }} 摄入汇总
    </div>
    <div class="stats-grid">
      <div class="stat-cell">
        <span class="stat-val">{{ Math.round(tool.result.total.calories || 0) }}</span>
        <span class="stat-unit">kcal</span>
        <span class="stat-label">总热量</span>
      </div>
      <div class="stat-cell">
        <span class="stat-val">{{ tool.result.total.meals ?? tool.result.total.count ?? 0 }}</span>
        <span class="stat-unit">餐</span>
        <span class="stat-label">餐数</span>
      </div>
      <div class="stat-cell">
        <span class="stat-val p">{{ Math.round(tool.result.total.protein ?? tool.result.total.protein_g ?? 0) }}</span>
        <span class="stat-unit">g</span>
        <span class="stat-label">蛋白质</span>
      </div>
      <div class="stat-cell">
        <span class="stat-val c">{{ Math.round(tool.result.total.carbs ?? tool.result.total.carbs_g ?? 0) }}</span>
        <span class="stat-unit">g</span>
        <span class="stat-label">碳水</span>
      </div>
      <div class="stat-cell">
        <span class="stat-val f">{{ Math.round(tool.result.total.fat ?? tool.result.total.fat_g ?? 0) }}</span>
        <span class="stat-unit">g</span>
        <span class="stat-label">脂肪</span>
      </div>
    </div>
  </div>

  <!-- 5. 查询/搜索结果卡：仅在本轮无写操作时展示（否则属内部参考步骤） -->
  <div
    v-else-if="(tool.name === 'get_records_in_range' || tool.name === 'search_meals') && recordsArtifactVisible()"
    class="artifact"
  >
    <div class="artifact-caption">
      {{ tool.name === 'search_meals' ? `搜索「${tool.args?.keyword || ''}」找到 ${tool.result.records.length} 餐：` : `找到 ${tool.result.records.length} 餐：` }}
    </div>
    <div class="artifact-cards">
      <MealCard
        v-for="rec in tool.result.records"
        :key="rec.asset_id || rec.id"
        :record="normalizeRecord(rec)"
        :interactive="true"
        @open="emit('open', normalizeRecord(rec))"
      />
    </div>
  </div>
</template>

<style scoped>
.artifact {
  border: 1px solid #2a2a2a; border-radius: 10px; background: #141414;
  padding: 10px; width: 100%; box-sizing: border-box;
}
.artifact-caption {
  color: #888; font-size: 12px; font-weight: 500; margin-bottom: 8px;
}
.artifact-cards { display: flex; flex-direction: column; gap: 8px; }

/* 删除确认卡 */
.confirm-card {
  border: 1px solid #3d3525; border-radius: 10px; background: #1a1712;
  padding: 12px; width: 100%; box-sizing: border-box;
}
.confirm-card.confirmed { border-color: #243d25; background: #121a13; }
.confirm-card.canceled { border-color: #282828; background: #161616; opacity: 0.75; }
.confirm-text { color: #e6e6e6; font-size: 13px; line-height: 1.5; margin-bottom: 10px; }
.confirm-text strong { color: #ffd43b; }
.confirm-done { color: #51cf66; font-size: 13px; }
.confirm-canceled { color: #888; font-size: 13px; }
.confirm-actions { display: flex; gap: 8px; }
.confirm-btn {
  flex: 1; padding: 7px 12px; border-radius: 6px; font-size: 12px;
  cursor: pointer; border: 1px solid transparent; font-family: inherit;
}
.confirm-btn.danger { background: #ff6b6b; color: #fff; }
.confirm-btn.danger:hover { background: #fa5252; }
.confirm-btn.cancel { background: #262626; color: #ccc; border-color: #333; }
.confirm-btn.cancel:hover { background: #303030; }

/* 统计卡 */
.stats-artifact {
  border: 1px solid #282828; border-radius: 10px; background: #141414;
  padding: 12px; width: 100%; box-sizing: border-box;
}
.stats-header { font-size: 12px; color: #aaa; margin-bottom: 10px; font-weight: 500; }
.stats-grid { display: flex; gap: 8px; justify-content: space-between; }
.stat-cell {
  display: flex; flex-direction: column; align-items: center; flex: 1;
}
.stat-val { font-size: 16px; font-weight: 700; color: #fff; line-height: 1.1; }
.stat-val.p { color: #51cf66; }
.stat-val.c { color: #ffd43b; }
.stat-val.f { color: #ff922b; }
.stat-unit { font-size: 10px; color: #777; line-height: 1; margin-top: 2px; }
.stat-label { font-size: 11px; color: #666; margin-top: 4px; }
</style>
