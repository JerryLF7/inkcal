<script setup>
import { computed, ref } from 'vue';
import { API, displayDate, fmtDate, hktNow } from '../utils/format.js';
import { toast, touch } from '../store.js';

const emit = defineEmits(['close']);

const cursor = ref(hktNow().toISOString().slice(0, 10));
const groups = ref([]);
const loading = ref(false);
const loadingMore = ref(false);
const hasMore = ref(true);
const analyzing = ref(false);
const status = ref('');
const fileInput = ref(null);
const correction = ref(null);
const correctedDate = ref('');

const empty = computed(() => !loading.value && groups.value.length === 0 && !hasMore.value);

function reset() {
  cursor.value = fmtDate(hktNow());
  groups.value = [];
  hasMore.value = true;
  status.value = '';
  correction.value = null;
  loadPage(false);
}

async function loadPage(append) {
  if (loading.value || loadingMore.value || !hasMore.value) return;
  if (append) loadingMore.value = true;
  else loading.value = true;

  try {
    const response = await fetch(`${API}/api/album-photos?cursor=${cursor.value}&days=7`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const dates = data.dates || [];
    groups.value = append ? groups.value.concat(dates) : dates;
    cursor.value = data.next_cursor || cursor.value;
    if (!dates.length) hasMore.value = false;
  } catch (error) {
    if (!append) hasMore.value = false;
    toast(`加载相册失败: ${error.message || '请重试'}`, 'error');
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}

function close(force = false) {
  if (analyzing.value && !force) return;
  emit('close');
}

function onScroll(event) {
  const el = event.currentTarget;
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80) loadPage(true);
}

async function analyzeAlbumPhoto(photo, date) {
  if (analyzing.value) return;
  analyzing.value = true;
  status.value = '正在分析照片...';
  try {
    const response = await fetch(`${API}/api/analyze-album-photo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        asset_id: photo.asset_id,
        source: photo.source,
        date,
        thumbnail_url: photo.thumbnail_url,
        photo_time: photo.photo_time,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    touch();
    toast('已添加记录');
    close(true);
  } catch (error) {
    const message = error.message || '未知错误';
    if (message === 'not food') toast('此图片不是真实食物，无法记录', 'error');
    else if (message === 'already processed') toast('此照片已在记录中', 'error');
    else toast(`分析失败: ${message}`, 'error');
  } finally {
    analyzing.value = false;
    status.value = '';
  }
}

function chooseLocalFile() {
  fileInput.value?.click();
}

async function onLocalFile(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file || analyzing.value) return;

  analyzing.value = true;
  status.value = '正在上传并分析照片...';
  try {
    const form = new FormData();
    form.append('image', file);
    const response = await fetch(`${API}/api/manual-upload`, { method: 'POST', body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    touch();
    if (data._date_source === 'fallback') {
      correction.value = data.record;
      correctedDate.value = data.date;
      status.value = '';
      return;
    }
    toast('已添加记录');
    close(true);
  } catch (error) {
    const message = error.message || '未知错误';
    if (message === 'not food') toast('此图片不是真实食物，无法记录', 'error');
    else if (message === 'already processed') toast('此照片已在记录中', 'error');
    else toast(`上传失败: ${message}`, 'error');
  } finally {
    analyzing.value = false;
    if (!correction.value) status.value = '';
  }
}

async function saveCorrection() {
  if (!correction.value || !correctedDate.value) return;
  analyzing.value = true;
  status.value = '正在调整日期...';
  try {
    const response = await fetch(`${API}/api/move-record`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asset_id: correction.value.asset_id, date: correctedDate.value }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    touch();
    toast('已添加记录');
    correction.value = null;
    close(true);
  } catch (error) {
    toast(`调整日期失败: ${error.message || '请重试'}`, 'error');
  } finally {
    analyzing.value = false;
    status.value = '';
  }
}

function keepFallbackDate() {
  correction.value = null;
  toast('已添加记录');
  close();
}

reset();
</script>

<template>
  <div class="modal-backdrop" @click.self="close">
    <section class="picker" role="dialog" aria-modal="true" aria-label="选择照片">
      <header class="picker-head">
        <h2>选择照片</h2>
        <button class="icon-button" type="button" aria-label="关闭" @click="close">×</button>
      </header>

      <input ref="fileInput" class="hidden-input" type="file" accept="image/*" @change="onLocalFile">

      <div v-if="correction" class="date-correction">
        <p>未能读取拍摄日期：{{ correction.meal || '上传记录' }}</p>
        <input v-model="correctedDate" type="date">
        <div class="correction-actions">
          <button type="button" class="secondary-button" @click="keepFallbackDate">保留今天</button>
          <button type="button" class="primary-button" @click="saveCorrection">调整日期</button>
        </div>
      </div>

      <template v-else>
        <div class="album-scroll" @scroll="onScroll">
          <div v-if="loading" class="state">加载中...</div>
          <template v-for="group in groups" :key="group.date">
            <div class="album-date">{{ displayDate(group.date) }}</div>
            <div class="album-grid">
              <button
                v-for="photo in group.photos"
                :key="photo.asset_id"
                class="album-photo"
                type="button"
                :disabled="analyzing"
                @click="analyzeAlbumPhoto(photo, group.date)"
              >
                <img :src="`${API}/api/image?url=${encodeURIComponent(photo.thumbnail_url)}`" alt="">
              </button>
            </div>
          </template>
          <div v-if="empty" class="state">没有未处理的照片</div>
          <div v-else-if="loadingMore" class="state compact">加载中...</div>
        </div>

        <footer class="picker-foot">
          <button class="primary-button" type="button" :disabled="analyzing" @click="chooseLocalFile">从本地上传</button>
        </footer>
      </template>

      <div v-if="analyzing" class="busy" role="status">{{ status }}</div>
    </section>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed; inset: 0; z-index: 240; padding: 24px 14px;
  background: rgb(0 0 0 / 72%); display: flex; align-items: flex-end; justify-content: center;
}
.picker {
  width: min(100%, 480px); max-height: min(78dvh, 720px); display: flex; flex-direction: column;
  background: #171717; border: 1px solid #303030; border-radius: 8px; overflow: hidden;
}
.picker-head { display: flex; align-items: center; justify-content: space-between; padding: 14px; border-bottom: 1px solid #292929; }
h2 { margin: 0; color: #e6e6e6; font-size: 16px; font-weight: 600; }
.icon-button { width: 32px; height: 32px; border: 0; background: transparent; color: #999; font-size: 24px; line-height: 1; cursor: pointer; }
.hidden-input { display: none; }
.album-scroll { flex: 1; min-height: 180px; overflow-y: auto; padding: 12px 14px 18px; }
.album-date { color: #9a9a9a; font-size: 12px; margin: 12px 0 8px; }
.album-date:first-child { margin-top: 0; }
.album-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; }
.album-photo { aspect-ratio: 1; padding: 0; overflow: hidden; background: #252525; border: 1px solid #303030; border-radius: 6px; cursor: pointer; }
.album-photo:disabled { cursor: wait; opacity: .55; }
.album-photo img { display: block; width: 100%; height: 100%; object-fit: cover; }
.picker-foot { padding: 12px 14px calc(12px + env(safe-area-inset-bottom)); border-top: 1px solid #292929; }
.primary-button, .secondary-button { border-radius: 6px; padding: 9px 12px; font: inherit; font-size: 13px; cursor: pointer; }
.primary-button { width: 100%; border: 1px solid #2a6eff; background: #2a6eff; color: #fff; }
.primary-button:disabled { opacity: .55; cursor: wait; }
.secondary-button { border: 1px solid #414141; background: #242424; color: #d0d0d0; }
.state { padding: 38px 0; color: #777; text-align: center; font-size: 13px; }
.state.compact { padding: 14px 0 0; }
.busy { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; padding: 28px; background: rgb(0 0 0 / 68%); color: #e7e7e7; font-size: 14px; text-align: center; }
.date-correction { padding: 20px 14px; color: #bdbdbd; font-size: 13px; }
.date-correction p { margin: 0 0 12px; }
.date-correction input { width: 100%; margin-bottom: 14px; padding: 9px; border: 1px solid #3b3b3b; border-radius: 6px; background: #101010; color: #e7e7e7; font: inherit; }
.correction-actions { display: flex; gap: 8px; }
.correction-actions button { flex: 1; }
.correction-actions .primary-button { width: auto; }
@media (min-width: 520px) { .modal-backdrop { align-items: center; } }
</style>
