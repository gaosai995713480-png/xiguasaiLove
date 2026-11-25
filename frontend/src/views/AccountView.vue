<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import TopBar from '../components/TopBar.vue'
import { galleryApi, usersApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { useToast } from '../composables/useToast'

const router = useRouter()
const authStore = useAuthStore()
const { success: toastSuccess } = useToast()

const passwordForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})
const passwordLoading = ref(false)
const passwordError = ref('')

const galleryForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})
const galleryLoading = ref(false)
const galleryError = ref('')
const gallerySuccess = ref('')

const isAdmin = computed(() => authStore.isAdmin)
const currentUsername = computed(() => authStore.username || '当前账号')

function clearGalleryUnlock() {
  try {
    sessionStorage.removeItem('gallery_unlocked')
  } catch { /* 本地存储不可用时仍然完成服务端修改 */ }
}

async function submitOwnPassword() {
  if (passwordLoading.value) return
  passwordError.value = ''

  const oldPassword = passwordForm.oldPassword
  const newPassword = passwordForm.newPassword
  if (!oldPassword) {
    passwordError.value = '请输入当前密码'
    return
  }
  if (newPassword.length < 8 || newPassword.length > 128) {
    passwordError.value = '新密码长度需为 8-128 个字符'
    return
  }
  if (newPassword !== passwordForm.confirmPassword) {
    passwordError.value = '两次输入的新密码不一致'
    return
  }

  passwordLoading.value = true
  try {
    const result = await usersApi.changeOwnPassword(oldPassword, newPassword)
    if (result?.ok === false) {
      throw new Error(result.error || '密码修改失败')
    }

    passwordForm.oldPassword = ''
    passwordForm.newPassword = ''
    passwordForm.confirmPassword = ''
    try {
      await authStore.logout()
    } catch { /* 服务端已撤销会话，继续跳转登录页 */ }
    toastSuccess('登录密码已修改，请使用新密码重新登录', 5000)
    await router.replace('/login')
  } catch (error) {
    passwordError.value = error?.message || '密码修改失败，请稍后重试'
  } finally {
    passwordLoading.value = false
  }
}

async function submitGalleryPassword() {
  if (!isAdmin.value || galleryLoading.value) return
  galleryError.value = ''
  gallerySuccess.value = ''

  const oldPassword = galleryForm.oldPassword
  const newPassword = galleryForm.newPassword
  if (!oldPassword) {
    galleryError.value = '请输入当前画廊密码'
    return
  }
  if (newPassword.length < 4 || newPassword.length > 128) {
    galleryError.value = '新画廊密码长度需为 4-128 个字符'
    return
  }
  if (newPassword !== galleryForm.confirmPassword) {
    galleryError.value = '两次输入的新画廊密码不一致'
    return
  }

  galleryLoading.value = true
  try {
    const result = await galleryApi.changePassword(oldPassword, newPassword)
    if (result?.ok === false) {
      throw new Error(result.error || '画廊密码修改失败')
    }

    clearGalleryUnlock()
    galleryForm.oldPassword = ''
    galleryForm.newPassword = ''
    galleryForm.confirmPassword = ''
    gallerySuccess.value = '画廊密码已修改，所有会话已重新锁定。'
    toastSuccess(gallerySuccess.value, 5000)
  } catch (error) {
    galleryError.value = error?.message || '画廊密码修改失败，请稍后重试'
  } finally {
    galleryLoading.value = false
  }
}
</script>

<template>
  <TopBar
    title="账号与安全"
    subtitle="管理登录密码与私密空间访问"
    @back="router.push('/')"
  />

  <main class="account-page">
    <section class="account-card glass-card">
      <div class="section-heading">
        <span class="section-icon">🔐</span>
        <div>
          <h2>修改登录密码</h2>
          <p>当前账号：{{ currentUsername }}</p>
        </div>
      </div>

      <form class="password-form" @submit.prevent="submitOwnPassword">
        <label>
          <span>当前密码</span>
          <input
            v-model="passwordForm.oldPassword"
            type="password"
            autocomplete="current-password"
            :disabled="passwordLoading"
          />
        </label>
        <label>
          <span>新密码</span>
          <input
            v-model="passwordForm.newPassword"
            type="password"
            autocomplete="new-password"
            :disabled="passwordLoading"
          />
        </label>
        <label>
          <span>确认新密码</span>
          <input
            v-model="passwordForm.confirmPassword"
            type="password"
            autocomplete="new-password"
            :disabled="passwordLoading"
          />
        </label>
        <p class="field-hint">新密码长度为 8-128 个字符；修改后需要重新登录。</p>
        <p v-if="passwordError" class="form-message is-error" role="alert">{{ passwordError }}</p>
        <button class="submit-btn" type="submit" :disabled="passwordLoading">
          {{ passwordLoading ? '正在修改...' : '修改登录密码' }}
        </button>
      </form>
    </section>

    <section v-if="isAdmin" class="account-card glass-card" data-test="gallery-password-card">
      <div class="section-heading">
        <span class="section-icon">🖼️</span>
        <div>
          <h2>心动画廊密码</h2>
          <p>修改后，所有已解锁的画廊会话都会重新锁定。</p>
        </div>
      </div>

      <form class="password-form" @submit.prevent="submitGalleryPassword">
        <label>
          <span>当前画廊密码</span>
          <input
            v-model="galleryForm.oldPassword"
            type="password"
            autocomplete="current-password"
            :disabled="galleryLoading"
          />
        </label>
        <label>
          <span>新画廊密码</span>
          <input
            v-model="galleryForm.newPassword"
            type="password"
            autocomplete="new-password"
            :disabled="galleryLoading"
          />
        </label>
        <label>
          <span>确认新画廊密码</span>
          <input
            v-model="galleryForm.confirmPassword"
            type="password"
            autocomplete="new-password"
            :disabled="galleryLoading"
          />
        </label>
        <p class="field-hint">新画廊密码长度为 4-128 个字符。</p>
        <p v-if="galleryError" class="form-message is-error" role="alert">{{ galleryError }}</p>
        <p v-if="gallerySuccess" class="form-message is-success" role="status">{{ gallerySuccess }}</p>
        <button class="submit-btn" type="submit" :disabled="galleryLoading">
          {{ galleryLoading ? '正在修改...' : '修改画廊密码' }}
        </button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.account-page {
  width: min(720px, calc(100% - 2 * var(--page-pad-x)));
  margin: 0 auto;
  padding: var(--page-pad-top) 0 var(--page-pad-bottom);
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.account-card {
  padding: 26px;
}

.section-heading {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 22px;
}

.section-icon {
  font-size: 28px;
  line-height: 1;
}

.section-heading h2 {
  margin: 0 0 6px;
  font-size: 20px;
}

.section-heading p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.password-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.password-form label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.password-form input {
  width: 100%;
  min-height: var(--touch-min);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 12px;
  padding: 0 14px;
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.07);
  outline: none;
}

.password-form input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(255, 107, 157, 0.14);
}

.field-hint {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.form-message {
  margin: 0;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.5;
}

.form-message.is-error {
  color: #fecdd3;
  background: rgba(190, 24, 93, 0.2);
  border: 1px solid rgba(251, 113, 133, 0.25);
}

.form-message.is-success {
  color: #bbf7d0;
  background: rgba(22, 101, 52, 0.22);
  border: 1px solid rgba(74, 222, 128, 0.24);
}

.submit-btn {
  min-height: var(--touch-min);
  border: none;
  border-radius: 12px;
  padding: 0 18px;
  background: linear-gradient(135deg, var(--primary), var(--secondary));
  color: #fff;
  font-weight: 700;
  cursor: pointer;
}

.submit-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

@media (max-width: 720px) {
  .account-card {
    padding: 20px 16px;
    border-radius: 18px;
  }

  .section-heading h2 {
    font-size: 18px;
  }
}
</style>
