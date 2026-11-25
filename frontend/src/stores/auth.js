import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '../api'
import { useMusicStore } from './music'

export const useAuthStore = defineStore('auth', () => {
  const authenticated = ref(false)
  const checking = ref(true)
  const username = ref('')
  const role = ref('')
  const isAdmin = computed(() => role.value === 'admin')

  async function checkAuth() {
    checking.value = true
    try {
      const data = await authApi.status()
      authenticated.value = !!data.authenticated
      username.value = data.username || ''
      role.value = data.role || ''
    } catch {
      authenticated.value = false
      username.value = ''
      role.value = ''
    } finally {
      checking.value = false
    }
  }

  async function login(user, pass) {
    const data = await authApi.login(user, pass)
    if (data.ok) {
      authenticated.value = true
      username.value = data.username
      role.value = data.role
    }
    return data
  }

  async function logout() {
    try {
      await authApi.logout()
    } catch (error) {
      // 网络失败也必须完成本地退出，避免用户被困在已登录界面。
      console.warn('退出登录请求失败，继续清理本地会话', error)
    } finally {
      try {
        const localKeys = Object.keys(localStorage).filter(
          (key) => key.startsWith('ai_chat_') || key.startsWith('ai_active_skill'),
        )
        localKeys.forEach((key) => localStorage.removeItem(key))
        localStorage.removeItem('express_history')
      } catch { /* ignore */ }

      try {
        sessionStorage.removeItem('gallery_unlocked')
        sessionStorage.removeItem('tripstar.latestTaskId')
        sessionStorage.removeItem('tripstar.latestTaskExpireAt')
      } catch { /* ignore */ }

      useMusicStore().reset()
      authenticated.value = false
      username.value = ''
      role.value = ''
    }
  }

  return { authenticated, checking, username, role, isAdmin, checkAuth, login, logout }
})
