<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import TopBar from '../components/TopBar.vue'
import GlassModal from '../components/GlassModal.vue'
import { backupApi, configApi, usersApi } from '../api'
import { useAuthStore } from '../stores/auth'

const POLL_MS = 800

const router = useRouter()
const authStore = useAuthStore()
const users = ref([])
const inviteCode = ref('')
const newCode = ref('')
const loading = ref(false)
const showCodeEdit = ref(false)
const configKeys = ref([])
const showConfigAdd = ref(false)
const configLoading = ref(false)
const configError = ref('')
const newConfig = ref({
  key: '',
  value: '',
})
const backupJob = ref({ status: 'idle' })
const backupBusy = ref(false)
const backupHint = ref('')
const backupDownloadHref = '/api/backup/export/download'
const resetDialogOpen = ref(false)
const resetTarget = ref(null)
const resetPassword = ref('')
const resetPasswordConfirm = ref('')
const resetLoading = ref(false)
const resetError = ref('')
const resetNotice = ref('')
let backupPollTimer = 0
let backupPollRequestInFlight = false
let backupViewActive = false
let backupStatusRequestSeq = 0

async function loadUsers() {
  try {
    users.value = await usersApi.list()
  } catch { /* handled by api layer */ }
}

async function loadInviteCode() {
  try {
    const data = await usersApi.getInviteCode()
    inviteCode.value = data.code || ''
    newCode.value = inviteCode.value
  } catch { /* handled */ }
}

async function loadConfigKeys() {
  try {
    const data = await configApi.listKeys()
    configKeys.value = data.items || []
  } catch { /* handled by api layer */ }
}

async function toggleUser(userId) {
  if (!confirm('确定要切换该用户的状态吗？')) return
  await usersApi.toggle(userId)
  await loadUsers()
}

function openResetPassword(user) {
  if (!user || isCurrentUser(user)) return
  resetTarget.value = user
  resetPassword.value = ''
  resetPasswordConfirm.value = ''
  resetError.value = ''
  resetNotice.value = ''
  resetDialogOpen.value = true
}

function isCurrentUser(user) {
  return String(user?.username || '').toLocaleLowerCase() === String(authStore.username || '').toLocaleLowerCase()
}

function closeResetPassword() {
  if (resetLoading.value) return
  resetDialogOpen.value = false
  resetError.value = ''
}

async function submitResetPassword() {
  if (resetLoading.value || !resetTarget.value) return
  resetError.value = ''

  const newPassword = resetPassword.value
  if (newPassword.length < 8 || newPassword.length > 128) {
    resetError.value = '新密码长度需为 8-128 个字符'
    return
  }
  if (newPassword !== resetPasswordConfirm.value) {
    resetError.value = '两次输入的新密码不一致'
    return
  }

  resetLoading.value = true
  try {
    const result = await usersApi.resetUserPassword(resetTarget.value.id, newPassword)
    if (result?.ok === false) {
      throw new Error(result.error || '重置密码失败')
    }
    resetNotice.value = `已重置「${resetTarget.value.username}」的密码，该用户需要重新登录。`
    resetDialogOpen.value = false
    resetPassword.value = ''
    resetPasswordConfirm.value = ''
  } catch (error) {
    resetError.value = error?.message || '重置密码失败，请稍后重试'
  } finally {
    resetLoading.value = false
  }
}

async function saveInviteCode() {
  if (!newCode.value.trim()) return
  loading.value = true
  try {
    await usersApi.updateInviteCode(newCode.value.trim())
    inviteCode.value = newCode.value.trim()
    showCodeEdit.value = false
  } finally {
    loading.value = false
  }
}

async function saveConfigKey() {
  const key = newConfig.value.key.trim().toUpperCase()
  if (!key) {
    configError.value = '请输入配置键'
    return
  }
  configError.value = ''
  configLoading.value = true
  try {
    await configApi.saveKey({
      key,
      value: newConfig.value.value,
    })
    newConfig.value = { key: '', value: '' }
    showConfigAdd.value = false
    await loadConfigKeys()
  } finally {
    configLoading.value = false
  }
}

const backupPacking = computed(() => backupJob.value.status === 'packing')
const backupReady = computed(() => backupJob.value.status === 'done')
const backupFailed = computed(() => backupJob.value.status === 'failed')
const backupPercent = computed(() => {
  const progress = backupJob.value.progress || {}
  if (!progress.total) return backupPacking.value ? 8 : 0
  return Math.min(100, Math.round((progress.current / progress.total) * 100))
})
const backupStatusText = computed(() => {
  if (backupPacking.value) {
    return backupJob.value.progress?.message || '正在打包回忆'
  }
  if (backupReady.value) {
    const failed = backupJob.value.stats?.files_failed || 0
    const size = formatBackupSize(backupJob.value.file_size)
    const sizeText = size ? `，约 ${size}` : ''
    if (failed) return `备份已生成${sizeText}，有 ${failed} 张照片没打进去。请点下载备份`
    return `备份已生成${sizeText}，请点下载备份`
  }
  if (backupFailed.value) return backupJob.value.error || '导出失败，请重试'
  return '把时间轴、心情、许愿、胶囊、足迹、相册和做过的菜打成一份压缩包。不含密码和密钥。'
})

function formatBackupSize(bytes) {
  const size = Number(bytes)
  if (!Number.isFinite(size) || size <= 0) return ''
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1).replace(/\.0$/, '')} MB`
  return `${(size / (1024 * 1024 * 1024)).toFixed(1).replace(/\.0$/, '')} GB`
}

function applyBackupJob(job) {
  if (!backupViewActive) return
  backupJob.value = job && job.status ? job : { status: 'idle' }
  if (backupJob.value.status === 'packing') {
    startBackupPolling()
  } else {
    stopBackupPolling()
  }
}

async function loadBackupStatus() {
  const requestId = ++backupStatusRequestSeq
  try {
    const job = await backupApi.status()
    if (backupViewActive && requestId === backupStatusRequestSeq) applyBackupJob(job)
  } catch {
    if (backupViewActive && requestId === backupStatusRequestSeq) {
      applyBackupJob({ status: 'idle' })
    }
  }
}

async function startBackup() {
  if (backupBusy.value || backupPacking.value) return
  backupBusy.value = true
  backupHint.value = ''
  const requestId = ++backupStatusRequestSeq
  try {
    const job = await backupApi.start()
    if (backupViewActive && requestId === backupStatusRequestSeq) applyBackupJob(job)
  } catch {
    backupHint.value = '导出没有开始，请稍后重试'
  } finally {
    backupBusy.value = false
  }
}

function startBackupPolling() {
  if (backupPollTimer) return
  backupPollTimer = window.setInterval(async () => {
    if (backupPollRequestInFlight || !backupViewActive) return
    backupPollRequestInFlight = true
    const requestId = ++backupStatusRequestSeq
    try {
      const job = await backupApi.status()
      if (backupViewActive && requestId === backupStatusRequestSeq) applyBackupJob(job)
    } catch {
      stopBackupPolling()
    } finally {
      backupPollRequestInFlight = false
    }
  }, POLL_MS)
}

function stopBackupPolling() {
  if (!backupPollTimer) return
  window.clearInterval(backupPollTimer)
  backupPollTimer = 0
}

onMounted(() => {
  backupViewActive = true
  if (!authStore.isAdmin) {
    router.replace('/')
    return
  }
  loadUsers()
  loadInviteCode()
  loadConfigKeys()
  loadBackupStatus()
})

onUnmounted(() => {
  backupViewActive = false
  backupStatusRequestSeq += 1
  stopBackupPolling()
})
</script>

<template>
  <TopBar title="用户管理" @back="router.back()" />
  <main class="users-page">
    <!-- 邀请码管理 -->
    <section class="invite-section glass-card">
      <h3>🔑 邀请码管理</h3>
      <div class="invite-row" v-if="!showCodeEdit">
        <span class="invite-label">当前邀请码：</span>
        <code class="invite-code">{{ inviteCode }}</code>
        <button class="btn-small" @click="showCodeEdit = true">修改</button>
      </div>
      <div class="invite-row" v-else>
        <input v-model="newCode" class="invite-input" placeholder="输入新邀请码" />
        <button class="btn-small btn-primary" @click="saveInviteCode" :disabled="loading">保存</button>
        <button class="btn-small" @click="showCodeEdit = false">取消</button>
      </div>
    </section>

    <section class="backup-section glass-card" data-test="backup-export">
      <h3>导出回忆</h3>
      <p class="backup-copy" data-test="backup-status">{{ backupStatusText }}</p>
      <p class="backup-note">压缩包里是全部相册原图，体积会比较大。文件在服务器上保留两小时。</p>
      <div
        class="backup-progress"
        :class="{ visible: backupPacking || backupReady }"
        role="status"
        aria-live="polite"
      >
        <div class="backup-progress-track">
          <div class="backup-progress-bar" :style="{ width: `${backupPercent}%` }"></div>
        </div>
      </div>
      <div class="backup-actions">
        <button
          class="btn-small btn-primary backup-btn"
          data-test="backup-start"
          :disabled="backupBusy || backupPacking"
          :aria-busy="backupPacking ? 'true' : 'false'"
          @click="startBackup"
        >
          {{ backupPacking ? '正在打包' : backupReady || backupFailed ? '重新导出' : '开始导出' }}
        </button>
        <a
          v-if="backupReady"
          class="btn-small backup-btn"
          data-test="backup-download"
          :href="backupDownloadHref"
          :download="backupJob.filename || 'xiguasai-memory.zip'"
        >
          下载备份
        </a>
      </div>
      <p v-if="backupHint" class="config-error backup-hint">{{ backupHint }}</p>
    </section>

    <!-- 系统配置管理 -->
    <section class="config-section glass-card">
      <div class="section-title-row">
        <h3>🧩 系统配置</h3>
        <button
          class="btn-small btn-primary"
          data-test="add-config-key"
          @click="showConfigAdd = !showConfigAdd"
        >
          {{ showConfigAdd ? '收起' : '添加 Key' }}
        </button>
      </div>

      <div v-if="showConfigAdd" class="config-add-panel">
        <input
          v-model="newConfig.key"
          class="invite-input config-key-input"
          data-test="config-key-input"
          placeholder="例如 TRIPSTAR_AMAP_WEB_KEY"
        />
        <input
          v-model="newConfig.value"
          class="invite-input config-value-input"
          data-test="config-value-input"
          placeholder="输入配置值，保存后不回显明文"
        />
        <button
          class="btn-small btn-primary"
          data-test="save-config-key"
          :disabled="configLoading"
          @click="saveConfigKey"
        >
          保存 Key
        </button>
        <p v-if="configError" class="config-error">{{ configError }}</p>
      </div>

      <div class="config-table-wrap">
        <table class="user-table config-table">
          <thead>
            <tr>
              <th>Key</th>
              <th>说明</th>
              <th>状态</th>
              <th>脱敏值</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in configKeys" :key="item.key">
              <td data-label="Key">
                <span class="cell-value"><code class="config-key">{{ item.key }}</code></span>
              </td>
              <td data-label="说明">
                <span class="cell-value">{{ item.label }}</span>
              </td>
              <td data-label="状态">
                <span class="cell-value">
                  <span class="status-dot" :class="item.has_value ? 'on' : 'off'"></span>
                  {{ item.has_value ? '已配置' : '未配置' }}
                </span>
              </td>
              <td data-label="脱敏值" class="time-col">
                <span class="cell-value">{{ item.masked_value || '—' }}</span>
              </td>
            </tr>
            <tr v-if="configKeys.length === 0">
              <td colspan="4" class="empty-config" data-label="">暂无配置项</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 用户列表 -->
    <section class="glass-card">
      <h3>👥 用户列表（{{ users.length }}）</h3>
      <p v-if="resetNotice" class="reset-notice" role="status">{{ resetNotice }}</p>
      <div class="user-table-wrap">
        <table class="user-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>用户名</th>
              <th>角色</th>
              <th>状态</th>
              <th>注册时间</th>
              <th>最后登录</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id" :class="{ 'row-disabled': u.disabled }">
              <td data-label="ID">
                <span class="cell-value">{{ u.id }}</span>
              </td>
              <td data-label="用户名">
                <span class="cell-value">{{ u.username }}</span>
              </td>
              <td data-label="角色">
                <span class="cell-value">
                  <span class="role-badge" :class="u.role">{{ u.role === 'admin' ? '管理员' : '访客' }}</span>
                </span>
              </td>
              <td data-label="状态">
                <span class="cell-value">
                  <span class="status-dot" :class="u.disabled ? 'off' : 'on'"></span>
                  {{ u.disabled ? '已禁用' : '正常' }}
                </span>
              </td>
              <td data-label="注册时间" class="time-col">
                <span class="cell-value">{{ u.created_at }}</span>
              </td>
              <td data-label="最后登录" class="time-col">
                <span class="cell-value">
                  <span v-if="u.last_login_at">{{ u.last_login_at }}</span>
                  <span v-else class="admin-hint">从未登录</span>
                </span>
              </td>
              <td data-label="操作">
                <span v-if="isCurrentUser(u)" class="cell-value admin-hint">当前账号</span>
                <div v-else class="cell-value user-actions">
                  <button
                    v-if="u.role !== 'admin'"
                    class="btn-small"
                    type="button"
                    :data-test="`toggle-user-${u.id}`"
                    :class="u.disabled ? 'btn-enable' : 'btn-disable'"
                    @click="toggleUser(u.id)"
                  >
                    {{ u.disabled ? '启用' : '禁用' }}
                  </button>
                  <button
                    class="btn-small btn-reset"
                    type="button"
                    :data-test="`reset-password-${u.id}`"
                    :aria-label="`重置 ${u.username} 的密码`"
                    @click="openResetPassword(u)"
                  >
                    重置密码
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>

  <GlassModal
    v-model="resetDialogOpen"
    :title="`重置 ${resetTarget?.username || '用户'} 的密码`"
  >
    <form class="reset-password-form" @submit.prevent="submitResetPassword">
      <p class="reset-password-hint">
        重置后，该用户的所有登录会话都会被撤销，需要使用新密码重新登录。
      </p>
      <label>
        <span>新密码</span>
        <input
          v-model="resetPassword"
          type="password"
          autocomplete="new-password"
          maxlength="128"
          :disabled="resetLoading"
          data-test="reset-password-input"
        />
      </label>
      <label>
        <span>确认新密码</span>
        <input
          v-model="resetPasswordConfirm"
          type="password"
          autocomplete="new-password"
          maxlength="128"
          :disabled="resetLoading"
          data-test="reset-password-confirm"
        />
      </label>
      <p class="password-hint">新密码长度为 8-128 个字符。</p>
      <p v-if="resetError" class="config-error reset-error" role="alert">{{ resetError }}</p>
      <div class="reset-actions">
        <button type="button" class="btn-small" :disabled="resetLoading" @click="closeResetPassword">
          取消
        </button>
        <button type="submit" class="btn-small btn-primary" :disabled="resetLoading">
          {{ resetLoading ? '正在重置...' : '确认重置' }}
        </button>
      </div>
    </form>
  </GlassModal>
</template>

<style scoped>
.users-page {
  max-width: 960px;
  margin: 0 auto;
  padding: var(--page-pad-top) var(--page-pad-x) var(--page-pad-bottom);
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.glass-card {
  backdrop-filter: blur(40px) saturate(150%);
  background: rgba(40, 40, 45, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 24px;
  padding: 28px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.2);
  transition: transform 0.3s ease;
}

.glass-card h3 { 
  margin: 0 0 20px; 
  font-size: 20px; 
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  display: flex; align-items: center; gap: 8px;
}

.section-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.section-title-row h3 {
  margin: 0;
}

.invite-section { margin-bottom: 0px; }

.backup-section h3 {
  margin-bottom: 12px;
}

.backup-copy {
  margin: 0 0 8px;
  color: rgba(255, 255, 255, 0.78);
  font-size: 15px;
  line-height: 1.6;
}

.backup-note {
  margin: 0 0 16px;
  color: rgba(255, 255, 255, 0.48);
  font-size: 13px;
  line-height: 1.5;
}

.backup-progress {
  height: 10px;
  margin: 0 0 16px;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.backup-progress.visible {
  opacity: 1;
}

.backup-progress-track {
  height: 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.12);
  overflow: hidden;
}

.backup-progress-bar {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(135deg, #667eea, #764ba2);
  transition: width 0.2s ease;
}

.backup-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.backup-btn {
  min-height: var(--touch-min);
  min-width: 120px;
}

a.backup-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
  box-sizing: border-box;
}

.backup-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none;
}

.backup-hint {
  margin-top: 12px;
}

@media (prefers-reduced-motion: reduce) {
  .backup-progress,
  .backup-progress-bar {
    transition: none;
  }
}

.config-section { margin-bottom: 0; }

.config-add-panel {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(260px, 1.2fr) auto;
  gap: 12px;
  align-items: center;
  margin-bottom: 18px;
  background: rgba(0, 0, 0, 0.15);
  padding: 16px;
  border-radius: 16px;
}

.config-key-input {
  text-transform: uppercase;
}

.config-error {
  grid-column: 1 / -1;
  margin: 0;
  color: #fca5a5;
  font-size: 13px;
}

.config-table-wrap {
  overflow-x: auto;
}

.config-table {
  margin-top: 0;
}

.config-key {
  color: #c4b5fd;
  font-family: 'Fira Code', monospace;
  font-size: 12px;
}

.empty-config {
  text-align: center;
  color: rgba(255, 255, 255, 0.45);
}

.reset-notice {
  margin: -8px 0 18px;
  padding: 10px 12px;
  border-radius: 10px;
  color: #bbf7d0;
  background: rgba(22, 101, 52, 0.22);
  border: 1px solid rgba(74, 222, 128, 0.24);
  font-size: 13px;
  line-height: 1.5;
}

.invite-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  background: rgba(0, 0, 0, 0.15);
  padding: 16px 20px;
  border-radius: 16px;
}

.invite-label { color: rgba(255, 255, 255, 0.7); font-size: 15px; }

.invite-code {
  background: linear-gradient(135deg, rgba(255,255,255,0.1), rgba(255,255,255,0.02));
  padding: 8px 16px;
  border-radius: 12px;
  font-family: 'Fira Code', monospace;
  font-size: 18px;
  color: #c4b5fd;
  letter-spacing: 2px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.invite-input {
  height: 40px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 12px;
  padding: 0 16px;
  font-size: 15px;
  color: #fff;
  background: rgba(0, 0, 0, 0.3);
  outline: none;
  min-width: 200px;
  transition: all 0.2s;
}
.invite-input:focus { border-color: #a78bfa; background: rgba(0, 0, 0, 0.5); }

.btn-small {
  padding: 8px 16px;
  border: none;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.9);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.btn-small:hover { 
  background: rgba(255, 255, 255, 0.2); 
  transform: translateY(-2px);
}
.btn-small.btn-primary {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
}
.btn-small.btn-primary:active { transform: translateY(0) scale(0.95); }

.user-table-wrap { overflow-x: auto; margin: 0 -8px; padding: 0 8px; }

.user-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0 8px;
  font-size: 14px;
}

.user-table th {
  padding: 0 16px 8px;
  text-align: left;
  color: rgba(255, 255, 255, 0.5);
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.user-table td {
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.85);
}
.user-table tr td:first-child { border-radius: 12px 0 0 12px; }
.user-table tr td:last-child { border-radius: 0 12px 12px 0; }

.user-table tbody tr { transition: all 0.2s; }
.user-table tbody tr:hover td { background: rgba(255, 255, 255, 0.08); }

.row-disabled td { opacity: 0.6; }

.role-badge {
  padding: 4px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.role-badge.admin { background: rgba(244, 114, 182, 0.15); color: #f472b6; border: 1px solid rgba(244, 114, 182, 0.3); }
.role-badge.visitor { background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); }

.status-dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px;
}
.status-dot.on { background: #34d399; box-shadow: 0 0 8px rgba(52, 211, 153, 0.8); animation: pulse-green 2s infinite; }
.status-dot.off { background: #f87171; }

@keyframes pulse-green {
  0% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.4); }
  70% { box-shadow: 0 0 0 6px rgba(52, 211, 153, 0); }
  100% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0); }
}

.time-col { font-size: 13px; color: rgba(255, 255, 255, 0.5); font-variant-numeric: tabular-nums; }
.admin-hint { color: rgba(255, 255, 255, 0.3); font-size: 12px; font-style: italic; }

.btn-disable { background: rgba(248, 113, 113, 0.1); color: #fca5a5; border: 1px solid rgba(248, 113, 113, 0.2); }
.btn-disable:hover { background: rgba(248, 113, 113, 0.2); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(248, 113, 113, 0.2); }
.btn-enable { background: rgba(52, 211, 153, 0.1); color: #6ee7b7; border: 1px solid rgba(52, 211, 153, 0.2); }
.btn-enable:hover { background: rgba(52, 211, 153, 0.2); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(52, 211, 153, 0.2); }
.btn-reset { background: rgba(167, 139, 250, 0.14); color: #ddd6fe; border: 1px solid rgba(167, 139, 250, 0.25); }
.btn-reset:hover { background: rgba(167, 139, 250, 0.24); transform: translateY(-2px); }

.user-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.user-actions .btn-small {
  min-height: var(--touch-min);
}

.reset-password-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.reset-password-form label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.reset-password-form input {
  width: 100%;
  min-height: var(--touch-min);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 12px;
  padding: 0 14px;
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.07);
  outline: none;
}

.reset-password-form input:focus {
  border-color: var(--accent);
}

.reset-password-hint,
.password-hint {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.55;
}

.reset-error {
  grid-column: auto;
}

.reset-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 600px) {
  .glass-card { padding: 20px; }
  .section-title-row { align-items: flex-start; flex-direction: column; }
  .config-add-panel { grid-template-columns: 1fr; }

  .config-table-wrap,
  .user-table-wrap {
    margin: 0;
    padding: 0;
    overflow: visible;
  }

  .user-table {
    display: block;
    width: 100%;
    border-spacing: 0;
    font-size: 13px;
  }

  .user-table thead {
    display: none;
  }

  .user-table tbody {
    display: grid;
    gap: 12px;
  }

  .user-table tbody tr {
    display: block;
    padding: 12px 14px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.035);
  }

  .user-table td,
  .user-table tr td:first-child,
  .user-table tr td:last-child {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    width: 100%;
    min-width: 0;
    padding: 5px 0;
    border-radius: 0;
    background: transparent !important;
    text-align: right;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .user-table td::before {
    content: attr(data-label);
    flex: 0 0 76px;
    color: rgba(255, 255, 255, 0.48);
    font-size: 12px;
    font-weight: 600;
    text-align: left;
    text-transform: none;
    letter-spacing: 0;
  }

  .user-table .cell-value {
    flex: 1;
    min-width: 0;
    text-align: right;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .user-table tbody tr:hover td {
    background: transparent;
  }

  .user-table .empty-config {
    display: block;
    text-align: center;
  }

  .user-table .empty-config::before {
    display: none;
  }

  .config-table .config-key {
    display: inline;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .row-disabled {
    opacity: 0.65;
  }

  .row-disabled td {
    opacity: 1;
  }
}
</style>
