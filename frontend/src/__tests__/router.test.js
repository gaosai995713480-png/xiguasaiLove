import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../stores/auth', () => ({
  useAuthStore: () => ({
    authenticated: true,
    checking: false,
    isAdmin: false,
  }),
}))

vi.mock('../stores/context', () => ({
  useContextStore: () => ({
    pageName: '',
    setPageState: vi.fn(),
  }),
}))

describe('router', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('提供登录用户可访问的独立 AI 助手路由', async () => {
    const { default: router } = await import('../router/index.js')
    const assistantRoute = router.getRoutes().find((route) => route.name === 'Assistant')

    expect(assistantRoute).toBeTruthy()
    expect(assistantRoute.path).toBe('/assistant')
    expect(assistantRoute.meta.adminOnly).toBeUndefined()
    expect(assistantRoute.components?.default).toBeTruthy()
  })
})
