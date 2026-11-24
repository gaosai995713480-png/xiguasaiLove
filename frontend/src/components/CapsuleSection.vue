<script setup>
/**
 * 时间胶囊组件 — 从 HomeView 拆出
 */
import { computed, ref, onMounted } from 'vue'
import { capsuleApi } from '../api'
import { useToast } from '../composables/useToast'
import { useAuthStore } from '../stores/auth'
import { isDateDueInShanghai, todayInShanghai } from '../utils/dayDate'
import GlassModal from './GlassModal.vue'

const { error: toastError, success: toastSuccess } = useToast()
const authStore = useAuthStore()

const capsules = ref([])
const capsuleModal = ref(false)
const capsuleForm = ref({ content: '', open_date: '' })
const saving = ref(false)
const showSection = computed(() => authStore.isAdmin || capsules.value.length > 0)

async function loadCapsules() {
  try { capsules.value = await capsuleApi.list() } catch { /* API layer handles toast */ }
}

async function saveCapsule() {
  if (!authStore.isAdmin || saving.value) return
  if (!capsuleForm.value.content.trim() || !capsuleForm.value.open_date) {
    toastError('请填写内容和开启日期')
    return
  }
  saving.value = true
  try {
    await capsuleApi.create({
      content: capsuleForm.value.content.trim(),
      open_date: capsuleForm.value.open_date,
    })
    capsuleModal.value = false
    capsuleForm.value = { content: '', open_date: '' }
    toastSuccess('胶囊已保存 💊')
    await loadCapsules()
  } catch {
    toastError('保存失败')
  } finally {
    saving.value = false
  }
}

async function openCapsule(id) {
  try {
    await capsuleApi.open(id)
    toastSuccess('胶囊已开启 🎉')
    loadCapsules()
  } catch { /* API layer handles toast */ }
}

function openCreateModal() {
  capsuleForm.value = { content: '', open_date: '' }
  capsuleModal.value = true
}

function canOpen(capsule) {
  if (typeof capsule?.can_open === 'boolean') return capsule.can_open
  return isDateDueInShanghai(capsule?.open_date)
}

defineExpose({ loadCapsules })

onMounted(() => {
  loadCapsules()
})
</script>

<template>
  <section class="capsule-section" v-if="showSection">
    <div class="capsule-head">
      <h3>⏰ 时间胶囊</h3>
      <button v-if="authStore.isAdmin" type="button" class="capsule-create-btn" @click="openCreateModal">
        ＋ 新建胶囊
      </button>
    </div>
    <div class="capsule-list">
      <div v-for="c in capsules.slice(0, 5)" :key="c.id" class="capsule-card">
        <template v-if="c.is_opened">
          <div class="capsule-content">{{ c.content }}</div>
          <div class="capsule-date">{{ c.open_date }} 已开启</div>
        </template>
        <template v-else>
          <div class="capsule-locked">🔒 {{ c.open_date }} 开启</div>
          <button v-if="canOpen(c)" class="btn-primary btn-small" @click="openCapsule(c.id)">开启</button>
        </template>
      </div>
    </div>
    <p v-if="authStore.isAdmin && !capsules.length" class="capsule-empty">还没有时间胶囊，写下想对未来说的话吧。</p>
  </section>

  <GlassModal v-if="authStore.isAdmin" v-model="capsuleModal" title="⏰ 新建时间胶囊">
    <div class="capsule-form">
      <label>
        内容
        <textarea v-model="capsuleForm.content" rows="4" placeholder="写一封给未来的信..." maxlength="2000"></textarea>
      </label>
      <label>
        开启日期
        <input v-model="capsuleForm.open_date" type="date" :min="todayInShanghai()" />
      </label>
      <div class="capsule-form-actions">
        <button type="button" class="capsule-cancel" :disabled="saving" @click="capsuleModal = false">取消</button>
        <button type="button" class="btn-primary" :disabled="saving || !capsuleForm.content.trim() || !capsuleForm.open_date" @click="saveCapsule">
          {{ saving ? '保存中...' : '保存胶囊' }}
        </button>
      </div>
    </div>
  </GlassModal>
</template>

<style scoped>
.capsule-section { margin: 32px 0; text-align: left; }
.capsule-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.capsule-section h3 { font-size: 18px; margin: 0; }
.capsule-create-btn {
  border: 1px solid var(--glass-border); border-radius: 999px; padding: 7px 14px;
  background: rgba(255,255,255,0.08); color: var(--text-primary); cursor: pointer;
}
.capsule-list { display: flex; gap: 12px; overflow-x: auto; padding: 4px 0; }
.capsule-card {
  min-width: 200px; padding: 16px; border-radius: 16px;
  background: var(--glass-bg); backdrop-filter: blur(20px);
  border: 1px solid var(--glass-border); flex-shrink: 0;
}
.capsule-content { font-size: 14px; line-height: 1.5; margin-bottom: 8px; }
.capsule-date { font-size: 12px; color: var(--accent); }
.capsule-locked { font-size: 14px; color: var(--text-secondary); }
.btn-small { padding: 6px 14px; font-size: 12px; margin-top: 8px; }
.capsule-empty { color: var(--text-secondary); font-size: 14px; margin: 8px 0 0; }
.capsule-form { display: flex; flex-direction: column; gap: 16px; }
.capsule-form label { display: flex; flex-direction: column; gap: 8px; color: var(--text-secondary); font-size: 14px; }
.capsule-form textarea,
.capsule-form input {
  width: 100%; border: 1px solid var(--glass-border); border-radius: 12px;
  background: rgba(255,255,255,0.06); color: var(--text-primary);
  padding: 11px 13px; font: inherit; outline: none; box-sizing: border-box;
}
.capsule-form textarea { resize: vertical; min-height: 100px; }
.capsule-form-actions { display: flex; gap: 10px; }
.capsule-form-actions button { flex: 1; padding: 11px; border-radius: 12px; cursor: pointer; }
.capsule-cancel { border: 1px solid var(--glass-border); background: transparent; color: var(--text-secondary); }
</style>
