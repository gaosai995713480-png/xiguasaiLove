import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick, reactive } from 'vue'

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
const mountedWrappers = []

async function mountView() {
  const { default: DayDetailView } = await import('../views/DayDetailView.vue')
  const wrapper = mount(DayDetailView, {
    global: {
      stubs: {
        TopBar: { template: '<div><slot /></div>' },
        Teleport: true,
      },
    },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

describe('DayDetailView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routeState.params.date = '2023-10-26'
  })

  afterEach(() => {
    while (mountedWrappers.length) mountedWrappers.pop().unmount()
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

  it('旧日期响应晚返回时不会覆盖当前日期', async () => {
    let resolveFirst
    let resolveSecond
    mockGet
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve }))

    const wrapper = await mountView()
    await nextTick()
    await flushPromises()
    expect(mockGet).toHaveBeenCalledTimes(1)

    routeState.params.date = '2023-10-27'
    await nextTick()
    expect(mockGet).toHaveBeenCalledTimes(2)

    resolveSecond({
      date: '2023-10-27',
      mood: { emoji: '🥰', note: '新日期', level: 5 },
      timeline: [],
      places: [],
      photos: [],
      gallery_unlocked: true,
    })
    await flushPromises()
    expect(wrapper.text()).toContain('新日期')

    resolveFirst({
      date: '2023-10-26',
      mood: { emoji: '😢', note: '旧日期', level: 1 },
      timeline: [],
      places: [],
      photos: [],
      gallery_unlocked: true,
    })
    await flushPromises()

    expect(wrapper.text()).toContain('新日期')
    expect(wrapper.text()).not.toContain('旧日期')
  })
})
