/**
 * auth store 单元测试
 * TDD: 验证 logout 时统一重置音乐状态
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// mock API
vi.mock('../api/index.js', () => ({
  authApi: {
    status: vi.fn().mockResolvedValue({ authenticated: true }),
    login: vi.fn().mockResolvedValue({ ok: true }),
    logout: vi.fn().mockResolvedValue({ ok: true }),
  },
  musicApi: {
    list: vi.fn().mockResolvedValue([]),
    url: vi.fn().mockResolvedValue({ url: '' }),
    lyric: vi.fn().mockResolvedValue({ lyric: '' }),
  },
}))

import { useAuthStore } from '../stores/auth'
import { useMusicStore } from '../stores/music'
import { authApi } from '../api'

describe('useAuthStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('logout', () => {
    it('退出登录时重置音乐状态', async () => {
      const authStore = useAuthStore()
      const musicStore = useMusicStore()
      authStore.authenticated = true
      musicStore.isPlaying = true
      musicStore.currentIndex = 3

      await authStore.logout()

      expect(authStore.authenticated).toBe(false)
      expect(musicStore.isPlaying).toBe(false)
      expect(musicStore.currentIndex).toBe(-1)
    })

    it('API 失败时仍清理本地会话和用户数据', async () => {
      const authStore = useAuthStore()
      const musicStore = useMusicStore()
      authStore.authenticated = true
      authStore.username = 'admin'
      authStore.role = 'admin'
      musicStore.isPlaying = true
      musicStore.currentIndex = 2

      localStorage.setItem('ai_chat_history_admin', '[]')
      localStorage.setItem('ai_active_skill_admin', '{}')
      localStorage.setItem('ai_active_skills_admin', '{}')
      localStorage.setItem('express_history', '[]')
      sessionStorage.setItem('gallery_unlocked', '1')
      sessionStorage.setItem('tripstar.latestTaskId', 'task-1')
      sessionStorage.setItem('tripstar.latestTaskExpireAt', String(Date.now() + 1000))

      vi.mocked(authApi.logout).mockRejectedValueOnce(new Error('network down'))
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})

      await expect(authStore.logout()).resolves.toBeUndefined()

      expect(authStore.authenticated).toBe(false)
      expect(authStore.username).toBe('')
      expect(authStore.role).toBe('')
      expect(musicStore.isPlaying).toBe(false)
      expect(localStorage.getItem('ai_chat_history_admin')).toBeNull()
      expect(localStorage.getItem('ai_active_skill_admin')).toBeNull()
      expect(localStorage.getItem('ai_active_skills_admin')).toBeNull()
      expect(localStorage.getItem('express_history')).toBeNull()
      expect(sessionStorage.getItem('gallery_unlocked')).toBeNull()
      expect(sessionStorage.getItem('tripstar.latestTaskId')).toBeNull()
      expect(warn).toHaveBeenCalled()
      warn.mockRestore()
    })
  })
})
