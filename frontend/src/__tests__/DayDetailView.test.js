import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'

const mockGet = vi.fn()
const mockPush = vi.fn()
const routeState = reactive({ params: { date: '2023-10-26' } })

vi.mock('../api/index.js', () => ({
  dayApi: {
    get: (...args) => mockGet(...args),
  },
}))

vi.mock('../stores/context', () => ({
  useContextStore: () => ({
    setPageState: vi.fn(),
  }),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ push: mockPush }),
}))

const flushPromises = () => Promise.resolve().then(() => Promise.resolve())

async function mountView() {
  const { default: DayDetailView } = await import('../views/DayDetailView.vue')
  return mount(DayDetailView, {
    global: {
      stubs: {
        TopBar: { template: '<div><slot /></div>' },
        Teleport: true,
      },
    },
  })
}

describe('DayDetailView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routeState.params.date = '2023-10-26'
  })

  it('把当天的心情、故事、足迹和照片拼在同一页', async () => {
    mockGet.mockResolvedValue({
      date: '2023-10-26',
      mood: { emoji: '🥰', note: '心动', level: 5 },
      timeline: [{ id: 1, title: '第一次见面', content: '很开心', icon: '💕' }],
      places: [{ id: 3, title: '黄鹤楼', note: '一起看江', photos: ['https://img/p1.jpg'] }],
      photos: [{ id: 7, url: '/photos/meet.jpg', thumbnail_url: '/photos/meet.jpg', description: '那天' }],
      gallery_unlocked: true,
    })

    const wrapper = await mountView()
    await flushPromises()

    expect(mockGet).toHaveBeenCalledWith('2023-10-26')
    expect(wrapper.text()).toContain('第一次见面')
    expect(wrapper.text()).toContain('黄鹤楼')
    expect(wrapper.text()).toContain('心动')
    expect(wrapper.text()).toContain('那天')
    expect(wrapper.text()).not.toContain('还是空白的')
  })

  it('没有痕迹时给出空状态，画廊未解锁时不展示照片', async () => {
    mockGet.mockResolvedValue({
      date: '2023-10-26',
      mood: null,
      timeline: [],
      places: [],
      photos: [],
      gallery_unlocked: false,
    })

    const wrapper = await mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('画廊还没解锁')
    expect(wrapper.text()).not.toContain('还是空白的')
  })

  it('画廊已解锁且当天没有任何痕迹时展示空白提示', async () => {
    mockGet.mockResolvedValue({
      date: '2023-10-26',
      mood: null,
      timeline: [],
      places: [],
      photos: [],
      gallery_unlocked: true,
    })

    const wrapper = await mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('还是空白的')
  })

  it('前一天后一天按日期翻页', async () => {
    mockGet.mockResolvedValue({
      date: '2023-10-26',
      mood: null,
      timeline: [],
      places: [],
      photos: [],
      gallery_unlocked: true,
    })

    const wrapper = await mountView()
    await flushPromises()

    const buttons = wrapper.findAll('.nav-btn')
    await buttons[0].trigger('click')
    expect(mockPush).toHaveBeenCalledWith('/day/2023-10-25')
    await buttons[1].trigger('click')
    expect(mockPush).toHaveBeenCalledWith('/day/2023-10-27')
  })
})
