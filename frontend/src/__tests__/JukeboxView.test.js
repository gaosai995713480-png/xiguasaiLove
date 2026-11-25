import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, reactive } from 'vue'
import { mount } from '@vue/test-utils'

const mockList = vi.fn()
const authState = reactive({ isAdmin: false })

vi.mock('../api/index.js', () => ({
  musicApi: {
    search: vi.fn(),
  },
  jukeboxApi: {
    list: (...args) => mockList(...args),
    create: vi.fn(),
    like: vi.fn(),
    adopt: vi.fn(),
    remove: vi.fn(),
  },
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => authState,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

const flushPromises = () => Promise.resolve().then(() => Promise.resolve())

async function mountView() {
  const { default: JukeboxView } = await import('../views/JukeboxView.vue')
  return mount(JukeboxView, {
    global: {
      stubs: {
        TopBar: { template: '<div><slot /></div>' },
        GlassModal: { template: '<div><slot /></div>' },
      },
    },
  })
}

describe('JukeboxView 权限 UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.isAdmin = false
    mockList.mockResolvedValue([
      {
        id: 1,
        song_name: '歌',
        artist: '歌手',
        platform: 'netease',
        likes: 0,
        is_adopted: false,
      },
    ])
  })

  it('访客看不到采纳和删除按钮，管理员才显示', async () => {
    const wrapper = await mountView()
    await flushPromises()

    expect(wrapper.find('.rc-adopt-btn').exists()).toBe(false)
    expect(wrapper.find('.rc-remove-btn').exists()).toBe(false)

    authState.isAdmin = true
    await nextTick()

    expect(wrapper.find('.rc-adopt-btn').exists()).toBe(true)
    expect(wrapper.find('.rc-remove-btn').exists()).toBe(true)
    expect(wrapper.get('.rc-adopt-btn').attributes('aria-label')).toBe('采纳 歌')
    expect(wrapper.get('.rc-remove-btn').attributes('aria-label')).toBe('移除 歌 的推荐')
  })
})
