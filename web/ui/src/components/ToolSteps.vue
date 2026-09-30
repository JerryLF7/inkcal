<script setup>
import { ref } from 'vue';

// 过程层：一条 assistant 回复里的全部工具调用，默认折叠。
// 标题优先取模型写入的 args.intent；历史消息缺 intent 时按工具名 + 关键参数兜底。
defineProps({
  tools: { type: Array, required: true },
});

const TOOL_LABELS = {
  get_records_in_range: '查询餐食记录',
  get_intake_stats: '统计摄入情况',
  search_meals: '搜索餐食记录',
  get_decisions: '查看 AI 识别决策',
  edit_record: '修改餐食记录',
  add_record: '补记餐食记录',
  reanalyze_record: '重新分析餐食记录',
  request_delete_record: '请求删除餐食记录',
};

const open = ref(false);          // 步骤条展开态
const detailOpen = ref({});       // 单步详情展开态，key = 步骤下标

// 步骤标题：优先 intent，其次工具名兜底 + 参数线索
function stepTitle(tool) {
  const intent = (tool.args?.intent || '').trim();
  if (intent) return intent;

  const label = TOOL_LABELS[tool.name] || tool.name;
  const a = tool.args || {};
  if (tool.name === 'get_records_in_range') {
    const s = (a.start || '').slice(5);
    const e = (a.end || '').slice(5);
    if (s && e) return s === e ? `${label} (${s})` : `${label} (${s}~${e})`;
  } else if (tool.name === 'search_meals' && a.keyword) {
    return `${label}「${a.keyword}」`;
  } else if (tool.name === 'get_decisions' && a.date) {
    return `${label} (${a.date.slice(5)})`;
  }
  return label;
}

// 步骤右侧的轻量结果徽标（不铺开正文，只给一个量级）
function stepBadge(tool) {
  if (tool.name === 'get_records_in_range' || tool.name === 'search_meals') {
    const n = tool.result?.records?.length;
    return n ? `${n} 条` : '';
  }
  if (tool.name === 'get_intake_stats' && tool.result?.total) {
    return `${Math.round(tool.result.total.calories || 0)} kcal`;
  }
  if (tool.name === 'get_decisions') {
    const n = tool.result?.count ?? tool.result?.decisions?.length;
    return n ? `${n} 条` : '';
  }
  return '';
}

function stepParams(tool) {
  const a = { ...(tool.args || {}) };
  delete a.intent;                       // intent 已是标题，不重复展示
  return JSON.stringify(a);
}

function stepOutcome(tool) {
  const r = tool.result || {};
  if (tool.name === 'get_records_in_range' || tool.name === 'search_meals') {
    return `匹配 ${r.records?.length || 0} 条记录`;
  }
  if (tool.name === 'get_intake_stats') {
    return r.total ? `${Math.round(r.total.calories || 0)} kcal` : (r.error || '');
  }
  if (tool.name === 'get_decisions') {
    return `审计决策 ${r.count ?? (r.decisions?.length || 0)} 条`;
  }
  if (tool.name === 'add_record') {
    return r.record ? `新增「${r.record.meal}」${r.record.calories} kcal` : (r.error || '');
  }
  if (tool.name === 'edit_record' || tool.name === 'reanalyze_record') {
    return r.after ? `「${r.after.meal}」${r.after.calories} kcal` : (r.error || '');
  }
  if (tool.name === 'request_delete_record') {
    return r.confirm_card ? '已生成待确认删除卡' : (r.error || '');
  }
  return '';
}

</script>

<template>
<div class="tool-steps">
  <button type="button" class="steps-head" @click="open = !open">
    <span class="steps-check">✓</span>
    <span class="steps-label">已执行 {{ tools.length }} 步操作</span>
    <span class="steps-caret" :class="{ open: open }">▾</span>
  </button>
  <div v-if="open" class="steps-body">
    <div v-for="(tool, tIdx) in tools" :key="tIdx" class="step">
      <button
        type="button"
        class="step-row"
        @click="detailOpen[tIdx] = !detailOpen[tIdx]"
      >
        <span class="step-check">✓</span>
        <span class="step-title">{{ stepTitle(tool) }}</span>
        <span v-if="stepBadge(tool)" class="step-badge">{{ stepBadge(tool) }}</span>
        <span
          class="step-caret"
          :class="{ open: !!detailOpen[tIdx] }"
        >▸</span>
      </button>
      <div
        v-if="detailOpen[tIdx]"
        class="step-detail"
      >
        <div class="step-line">
          <span class="step-k">参数</span><code>{{ stepParams(tool) }}</code>
        </div>
        <div v-if="stepOutcome(tool)" class="step-line">
          <span class="step-k">结果</span><code>{{ stepOutcome(tool) }}</code>
        </div>
      </div>
    </div>
  </div>
</div>
</template>

<style scoped>
/* ── 工具执行步骤链（默认折叠，参考 LobeHub/Pi 的过程展示）── */
.tool-steps {
  border: 1px solid #1f1f1f; border-radius: 10px;
  background: #121212; overflow: hidden; width: 100%;
}
.steps-head {
  width: 100%; display: flex; align-items: center; gap: 7px;
  padding: 8px 11px; background: none; border: 0; cursor: pointer;
  color: #9a9a9a; font: inherit; font-size: 12px; text-align: left;
  transition: background 0.15s;
}
.steps-head:hover { background: #181818; }
.steps-check { color: #51cf66; font-size: 11px; flex: none; line-height: 1; }
.steps-label { flex: 1; min-width: 0; }
.steps-caret {
  color: #555; font-size: 9px; flex: none; line-height: 1;
  transition: transform 0.18s ease;
}
.steps-caret.open { transform: rotate(180deg); }

.steps-body { border-top: 1px solid #1c1c1c; padding: 3px 0; }
.step + .step { border-top: 1px solid #191919; }
.step-row {
  width: 100%; display: flex; align-items: center; gap: 7px;
  padding: 7px 11px; background: none; border: 0; cursor: pointer;
  color: #b8b8b8; font: inherit; font-size: 12px; text-align: left;
  transition: background 0.15s;
}
.step-row:hover { background: #181818; }
.step-check { color: #51cf66; font-size: 11px; flex: none; line-height: 1; }
.step-title { flex: 1; min-width: 0; word-break: break-word; line-height: 1.4; }
.step-badge {
  flex: none; font-size: 10px; color: #808080; line-height: 1.6;
  background: #1f1f1f; border-radius: 6px; padding: 0 6px;
}
.step-caret {
  color: #4a4a4a; font-size: 8px; flex: none; line-height: 1;
  transition: transform 0.15s ease;
}
.step-caret.open { transform: rotate(90deg); }

.step-detail {
  display: flex; flex-direction: column; gap: 4px;
  padding: 0 11px 9px 29px;
}
.step-line { display: flex; gap: 8px; align-items: baseline; }
.step-k { flex: none; font-size: 10px; color: #555; }
.step-detail code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10.5px; color: #8a8a8a; line-height: 1.5;
  word-break: break-all;
}

</style>
