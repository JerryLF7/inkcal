<script setup>
// 设置 Tab：体征参数（算 BMR）+ Calo 滑动窗口（原 ChatPane 弹窗迁移至此）
import { ref, onMounted } from 'vue';
import { API } from '../utils/format.js';
import { toast } from '../store.js';

const loading = ref(true);
const saving = ref(false);

// 体征参数
const height = ref('');       // cm
const weight = ref('');       // kg
const birthdate = ref('');    // YYYY-MM-DD
const gender = ref('male');   // male | female
const bmr = ref(null);

// Calo 聊天滑动窗口（原 ChatPane 设置弹窗）
const chatWindow = ref(20);

async function load() {
  loading.value = true;
  try {
    const res = await fetch(`${API}/api/settings`);
    if (res.ok) {
      const d = await res.json();
      height.value = d.user_height || '';
      weight.value = d.user_weight || '';
      birthdate.value = d.user_birthdate || '';
      gender.value = d.user_gender || 'male';
      bmr.value = d.bmr;
      chatWindow.value = d.chat_window || 20;
    }
  } catch (e) {
    console.error('load settings failed:', e);
  } finally {
    loading.value = false;
  }
}

async function save() {
  // 轻量前端校验，后端还有同样的边界校验
  const h = parseFloat(height.value);
  const w = parseFloat(weight.value);
  if (height.value && !(h >= 50 && h <= 260)) return toast('身高需在 50–260 cm', 'error');
  if (weight.value && !(w >= 20 && w <= 300)) return toast('体重需在 20–300 kg', 'error');
  if (birthdate.value && !/^\d{4}-\d{2}-\d{2}$/.test(birthdate.value)) {
    return toast('出生日期格式应为 YYYY-MM-DD', 'error');
  }

  saving.value = true;
  try {
    const res = await fetch(`${API}/api/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_window: chatWindow.value,
        user_height: height.value,
        user_weight: weight.value,
        user_birthdate: birthdate.value,
        user_gender: gender.value,
      }),
    });
    if (res.ok) {
      const d = await res.json();
      bmr.value = d.bmr;
      toast('设置已保存');
    } else {
      const err = await res.json().catch(() => ({}));
      toast(err.error || '保存失败', 'error');
    }
  } catch (e) {
    toast('保存失败', 'error');
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="settings-pane">
    <div class="topbar">
      <div class="sticky-date">设置</div>
    </div>

    <div class="scroll" v-if="!loading">
      <!-- 体征参数 -->
      <div class="set-card">
        <div class="set-card-title">体征参数</div>
        <div class="set-card-desc">用于计算基础代谢 BMR（Mifflin-St Jeor 公式），进而得出每日热量缺口。</div>

        <div class="set-field">
          <label>性别</label>
          <div class="seg">
            <button type="button" :class="{ active: gender === 'male' }" @click="gender = 'male'">男</button>
            <button type="button" :class="{ active: gender === 'female' }" @click="gender = 'female'">女</button>
          </div>
        </div>

        <div class="set-field">
          <label>身高 (cm)</label>
          <input v-model="height" type="number" min="50" max="260" placeholder="例如 182" inputmode="decimal" />
        </div>

        <div class="set-field">
          <label>体重 (kg)</label>
          <input v-model="weight" type="number" min="20" max="300" placeholder="例如 76" inputmode="decimal" />
        </div>

        <div class="set-field">
          <label>出生日期</label>
          <input v-model="birthdate" type="date" />
        </div>

        <div class="bmr-result" :class="{ ready: bmr }">
          <template v-if="bmr">基础代谢 ≈ <b>{{ Math.round(bmr) }}</b> kcal/天</template>
          <template v-else>填写身高、体重、出生日期后自动计算</template>
        </div>
      </div>

      <!-- Calo 聊天窗口（自 ChatPane 弹窗迁移） -->
      <div class="set-card">
        <div class="set-card-title">Calo 对话</div>
        <div class="set-field">
          <div class="set-label">
            <span>上下文滑动窗口</span>
            <span class="set-val">{{ chatWindow }} 轮</span>
          </div>
          <input v-model.number="chatWindow" type="range" min="5" max="50" step="1" class="set-range" />
          <div class="set-card-desc">
            每轮向模型发送最近 N 轮对话历史（5～50 轮，默认 20）。调大可记住更长上下文，调小节省 Token 与提高响应速度。
          </div>
        </div>
      </div>

      <button class="btn-save" type="button" :disabled="saving" @click="save">
        {{ saving ? '保存中…' : '保存设置' }}
      </button>
    </div>

    <div v-else class="loading">加载中…</div>
  </section>
</template>

<style scoped>
.settings-pane {
  width: 100%; height: 100%; display: flex; flex-direction: column;
  overflow: hidden; background: #0f0f0f;
}
.topbar {
  display: flex; align-items: center; padding: 14px 14px 10px;
  border-bottom: 1px solid #1c1c1c; flex: none;
}
.sticky-date { font-size: 15px; font-weight: 600; color: #e0e0e0; }

.scroll {
  flex: 1; overflow-y: auto; padding: 14px;
  display: flex; flex-direction: column; gap: 14px;
}
.loading { padding: 40px; text-align: center; color: #666; }

.set-card {
  background: #161616; border: 1px solid #242424;
  border-radius: 12px; padding: 16px;
  display: flex; flex-direction: column; gap: 14px;
}
.set-card-title { font-size: 14px; font-weight: 600; color: #e0e0e0; }
.set-card-desc { font-size: 12px; color: #777; line-height: 1.6; }

.set-field { display: flex; flex-direction: column; gap: 6px; }
.set-field label { font-size: 13px; color: #aaa; }
.set-field input[type="number"],
.set-field input[type="date"] {
  background: #0d0d0d; border: 1px solid #2a2a2a; border-radius: 8px;
  color: #e0e0e0; font-size: 15px; padding: 10px 12px; font-family: inherit;
  width: 100%; box-sizing: border-box;
}
.set-field input:focus { outline: none; border-color: #2a6eff; }

.set-label {
  display: flex; justify-content: space-between; font-size: 13px; color: #aaa;
}
.set-val { color: #2a6eff; font-weight: 600; }
.set-range { width: 100%; accent-color: #2a6eff; }

.seg {
  display: flex; border-radius: 8px; padding: 2px; gap: 2px;
  background: #0d0d0d; border: 1px solid #2a2a2a; width: fit-content;
}
.seg button {
  border: none; background: none; color: #888; font-size: 13px;
  padding: 6px 20px; border-radius: 7px; cursor: pointer; font-family: inherit;
}
.seg button.active { background: #2a6eff22; color: #2a6eff; }

.bmr-result {
  font-size: 14px; color: #666; text-align: center;
  padding: 12px; border-radius: 8px; background: #0d0d0d;
  border: 1px dashed #2a2a2a;
}
.bmr-result.ready { color: #4cda8b; border-style: solid; border-color: #1e4030; background: #0e1a13; }
.bmr-result b { font-size: 18px; }

.btn-save {
  border: none; border-radius: 10px; background: #2a6eff;
  color: #fff; font-size: 14px; font-weight: 600; padding: 13px;
  cursor: pointer; font-family: inherit;
}
.btn-save:disabled { opacity: .6; }
.btn-save:active { background: #1a5aee; }
</style>
