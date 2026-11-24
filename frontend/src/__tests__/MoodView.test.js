import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { mount } from '@vue/test-utils'

const mockList = vi.fn()
const mockPush = vi.fn()
const authState = reactive({ isAdmin: true })

vi.mock('../api/index.js', () => ({
  moodApi: {
    list: (...args) => mockList(...args),
    save: vi.fn(),
  },
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => authState,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
}))

const flushPromises = () => Promise.resolve().then(() => Promise.resolve())

async function mountView() {
  const { default: MoodView } = await import('../views/MoodView.vue')
  return mount(MoodView, {
    global: {
      stubs: {
        TopBar: { template: '<div><slot /></div>' },
        GlassModal: {
          props: ['modelValue'],
          template: '<div v-if="modelValue" class="mood-modal"><slot /></div>',
        },
      },
    },
  })
}

describe('MoodView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.isAdmin = true
    mockList.mockResolvedValue([])
  })

  it('旧月份响应晚返回时不会覆盖当前月份', async () => {
    const requests = []
    mockList.mockImplementation((year, month) => new Promise((resolve) => {
      requests.push({ year, month, resolve })
    }))

    const wrapper = await mountView()
    const prevButton = wrapper.findAll('.cal-header button')[0]
    await prevButton.trigger('click')
    await prevButton.trigger('click')

    expect(requests).toHaveLength(3)
    const latest = requests[2]
    latest.resolve([{
      mood_date: `${latest.year}-${String(latest.month).padStart(2, '0')}-01`,
      emoji: '🎉',
      level: 5,
      note: '当前月份',
    }])
    await flushPromises()
    expect(wrapper.text()).toContain('🎉')

    const stale = requests[1]
    stale.resolve([{
      mood_date: `${stale.year}-${String(stale.month).padStart(2, '0')}-02`,
      emoji: '😢',
      level: 1,
      note: '旧月份',
    }])
    await flushPromises()

    expect(wrapper.text()).toContain('🎉')
    expect(wrapper.text()).not.toContain('😢')
  })

  it('访客点击日期只查看当天，不打开编辑弹窗', async () => {
    authState.isAdmin = false
    const wrapper = await mountView()
    await flushPromises()

    const day = wrapper.find('.cal-day:not(.is-empty)')
    await day.trigger('click')

    expect(mockPush).toHaveBeenCalledWith(expect.stringMatching(/^\/day\/\d{4}-\d{2}-\d{2}$/))
    expect(wrapper.find('.mood-modal').exists()).toBe(false)
  })
})
