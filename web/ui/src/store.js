import { reactive } from 'vue';
import { API } from './utils/format.js';

// 轻量全局状态（无 pinia）：
// - bump：数据变更计数器，各视图 watch 它自行重载已加载的数据
// - toast：全局轻提示
export const store = reactive({
  bump: 0,
  toastMsg: '',
  toastType: '',
  bmr: null,        // 基础代谢（来自 /api/settings）；null = 未填体征
  bmrLoaded: false,
});

// BMR 全局缓存：App 挂载时拉一次；设置页保存体征后 force 刷新
export async function ensureBmr(force) {
  if (store.bmrLoaded && !force) return;
  try {
    const r = await fetch(`${API}/api/settings`);
    if (!r.ok) return;
    const d = await r.json();
    store.bmr = d.bmr ?? null;
    store.bmrLoaded = true;
  } catch { /* 静默，视图自动退到固定目标 */ }
}

let _toastTimer = null;

export function touch() {
  store.bump++;
}

export function toast(msg, type) {
  store.toastMsg = msg;
  store.toastType = type === 'error' ? 'error' : '';
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { store.toastMsg = ''; }, 2600);
}

// ── agent 监督数据缓存（/api/decisions、/api/skipped，按日期）──────
// 餐卡 🤖 角标、lightbox "AI 决策" 区块、skip 折叠条共用。
export const agentData = reactive({ decisions: {}, skipped: {} });

export function clearAgentCaches() {
  agentData.decisions = {};
  agentData.skipped = {};
}

export async function ensureDecisions(date) {
  if (agentData.decisions[date]) return;
  try {
    const r = await fetch(`${API}/api/decisions?date=${date}`);
    if (!r.ok) return;
    const d = await r.json();
    agentData.decisions[date] = d.decisions || [];
  } catch { /* 静默，角标只是增强 */ }
}

export async function ensureSkipped(date) {
  if (agentData.skipped[date]) return;
  try {
    const r = await fetch(`${API}/api/skipped?date=${date}`);
    if (!r.ok) return;
    const d = await r.json();
    agentData.skipped[date] = d.skipped || [];
  } catch { /* 静默 */ }
}

// 覆盖该记录的决策：add 命中 asset_ids；update 命中 target_asset_id（asset_ids 是新图）
export function decisionFor(record) {
  const list = agentData.decisions[record.date] || [];
  return list.find(d =>
    (d.asset_ids || []).includes(record.asset_id) ||
    d.target_asset_id === record.asset_id
  ) || null;
}

export const ACTION_LABELS = { add: '新增', update: '合并更新', skip: '跳过' };
export const RELATION_LABELS = { new_meal: '新餐', same_meal: '同餐', rejected: '非食物' };

// ── Background data-version polling（参考旧版 pollDataVersion）──────
// Cron 在服务端写记录后，打开的页面不会察觉。每 30s 轮询一次指纹，
// 变化时 bump 让所有视图刷新。
let _lastDataVersion = null;
let _pollTimer = null;

async function pollDataVersion() {
  if (document.visibilityState !== 'visible') return;
  try {
    const r = await fetch(`${API}/api/data-version`);
    if (!r.ok) return;
    const v = await r.json();
    if (!v || !v.version) return;
    if (_lastDataVersion === null) { _lastDataVersion = v.version; return; }
    if (v.version !== _lastDataVersion) {
      _lastDataVersion = v.version;
      clearAgentCaches();
      touch();
    }
  } catch { /* 网络失败静默 */ }
}

export function startDataVersionPolling() {
  if (_pollTimer) return;
  pollDataVersion();
  _pollTimer = setInterval(pollDataVersion, 30000);
}
