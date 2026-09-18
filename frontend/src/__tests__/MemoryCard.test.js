import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const mockMemory = vi.fn()
const mockSetMemory = vi.fn()
const mockPush = vi.fn()
const authState = { isAdmin: false }

vi.mock('../api/index.js', () => ({
  dayApi: {
    memory: (...args) => mockMemory(...args),
    setMemory: (...args) => mockSetMemory(...args),
  },
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => authState,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
}))

const flush = () => Promise.resolve().then(() => Promise.resolve())

async function mountCard() {
  const { default: MemoryCard } = await import('../components/MemoryCard.vue')
  const wrapper = mount(MemoryCard)
  await flush()
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('MemoryCard', () => {
  beforeEach(() => {
    authState.isAdmin = false
    mockMemory.mockReset()
    mockSetMemory.mockReset()
    mockPush.mockReset()
  })

  it('登录后展示随机一天并进入这一天', async () => {
    mockMemory.mockResolvedValue({
      enabled: true,
      memory: {
        date: '2023-10-26',
        cover_url: 'https://img/a.jpg',
        mood_emoji: '🥰',
        mood_note: '心动',
        story_title: '第一次见面',
        place_title: '',
        has_photos: true,
      },
    })

    const wrapper = await mountCard()

    expect(wrapper.text()).toContain('随机回忆')
    expect(wrapper.text()).toContain('2023年10月26日')
    expect(wrapper.text()).toContain('在一起的第 1 天')
    expect(wrapper.text()).toContain('🥰 心动')
    expect(wrapper.find('.memory-toggle').exists()).toBe(false)

    await wrapper.find('.memory-card').trigger('click')
    expect(mockPush).toHaveBeenCalledWith('/day/2023-10-26')
  })

  it('关闭后访客看不到卡片', async () => {
    mockMemory.mockResolvedValue({ enabled: false, memory: null })

    const wrapper = await mountCard()

    expect(wrapper.find('[data-test="random-memory"]').exists()).toBe(false)
  })

  it('管理员可以关闭随机回忆', async () => {
    authState.isAdmin = true
    mockMemory.mockResolvedValue({
      enabled: true,
      memory: { date: '2023-10-26', cover_url: '', mood_emoji: '', mood_note: '', story_title: '第一次见面', place_title: '', has_photos: false },
    })
    mockSetMemory.mockResolvedValue({ enabled: false })

    const wrapper = await mountCard()
    const toggle = wrapper.find('.memory-toggle')
    expect(toggle.text()).toBe('已开启')

    await toggle.trigger('click')
    await flush()
    await wrapper.vm.$nextTick()

    expect(mockSetMemory).toHaveBeenCalledWith(false)
    expect(wrapper.find('.memory-card').exists()).toBe(false)
    expect(wrapper.text()).toContain('关闭后')
  })
})
