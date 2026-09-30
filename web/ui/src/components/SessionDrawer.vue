<script setup>
// 历史会话抽屉：只负责展示与发出意图，会话状态由 ChatPane 持有。
defineProps({
  sessions: { type: Array, required: true },
  currentId: { type: [Number, String], default: null },
});
const emit = defineEmits(['close', 'create', 'select']);

function formatSessionTime(t) {
  if (!t) return '';
  return t.replace('T', ' ').slice(0, 16);
}
</script>

<template>
<div class="drawer-mask" @click.self="emit('close')">
  <div class="drawer">
    <div class="drawer-header">
      <div class="drawer-title">历史会话</div>
      <button
        type="button"
        class="drawer-close"
        aria-label="关闭"
        @click="emit('close')"
      >
        ✕
      </button>
    </div>
    <div class="drawer-action">
      <button type="button" class="new-session-btn" @click="emit('create')">
        ＋ 新建会话
      </button>
    </div>
    <div class="session-list">
      <div
        v-if="sessions.length === 0"
        class="session-empty"
      >
        暂无历史会话
      </div>
      <div
        v-for="s in sessions"
        :key="s.id"
        class="session-item"
        :class="{ active: s.id === currentId }"
        @click="emit('select', s.id)"
      >
        <div class="session-item-title">{{ s.title || '新会话' }}</div>
        <div class="session-item-time">{{ formatSessionTime(s.updated_at || s.created_at) }}</div>
      </div>
    </div>
  </div>
</div>
</template>

<style scoped>
.drawer-mask {
  position: absolute; inset: 0; background: rgba(0, 0, 0, 0.7);
  z-index: 50; display: flex; justify-content: flex-end;
}
.drawer {
  width: 280px; height: 100%; background: #141414; border-left: 1px solid #222;
  display: flex; flex-direction: column; box-sizing: border-box;
}
.drawer-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px; border-bottom: 1px solid #202020;
}
.drawer-title { font-size: 14px; font-weight: 600; color: #eee; }
.drawer-close {
  border: 0; background: transparent; color: #888; font-size: 15px;
  cursor: pointer; padding: 4px;
}
.drawer-close:hover { color: #fff; }
.drawer-action { padding: 10px 14px; border-bottom: 1px solid #1c1c1c; }
.new-session-btn {
  width: 100%; padding: 8px; border-radius: 6px; border: 1px solid #2a6eff;
  background: #2a6eff15; color: #2a6eff; font-size: 13px; font-weight: 500;
  cursor: pointer; transition: background 0.15s;
}
.new-session-btn:hover { background: #2a6eff28; }
.session-list { flex: 1; overflow-y: auto; padding: 8px 10px; }
.session-empty { text-align: center; color: #666; font-size: 12px; margin-top: 20px; }
.session-item {
  padding: 10px 12px; border-radius: 8px; cursor: pointer;
  margin-bottom: 6px; transition: background 0.15s;
}
.session-item:hover { background: #1c1c1c; }
.session-item.active { background: #222; border-left: 3px solid #2a6eff; }
.session-item-title {
  font-size: 13px; color: #ddd; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; margin-bottom: 3px;
}
.session-item-time { font-size: 11px; color: #666; }
</style>
