import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const mockList = vi.fn()
const mockCreate = vi.fn()

vi.mock('../api/index.js', () => ({
  wishApi: {
    list: (...args) => mockList(...args),
    create: (...args) => mockCreate(...args),
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

const flushPromises = () => Promise.resolve().then(() => Promise.resolve())

function deferred() {
  let resolve
  const promise = new Promise((res) => { resolve = res })
  return { promise, resolve }
}

async function mountView() {
  const { default: WishesView } = await import('../views/WishesView.vue')
  return mount(WishesView, {
    global: {
      stubs: {
        TopBar: { template: '<div class="top-bar"><slot /></div>' },
      },
    },
  })
}

describe('WishesView', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    mockList.mockResolvedValue([])
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('点击或键盘操作星点可展开愿望文字', async () => {
    mockList.mockResolvedValue([
      { id: 1, content: '愿我们一直在一起', x: 0.2, y: 0.3, color: '#ffd700' },
    ])

    const wrapper = await mountView()
    await flushPromises()

    const star = wrapper.find('.star')
    expect(star.attributes('tabindex')).toBe('0')
    expect(star.attributes('aria-expanded')).toBe('false')

    await star.trigger('click')
    expect(star.classes()).toContain('is-active')
    expect(star.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.wish-modal').classes()).not.toContain('is-visible')

    await star.trigger('keydown', { key: 'Enter' })
    expect(star.classes()).not.toContain('is-active')

    wrapper.unmount()
  })

  it('点击弹窗外只关闭弹窗并保留草稿', async () => {
    const wrapper = await mountView()
    await flushPromises()

    await wrapper.find('#sky').trigger('click', { clientX: 100, clientY: 120 })
    await wrapper.find('.wish-modal input').setValue('还没写完的愿望')
    await wrapper.find('#sky').trigger('click', { clientX: 220, clientY: 260 })

    expect(wrapper.find('.wish-modal').classes()).not.toContain('is-visible')

    await wrapper.find('#sky').trigger('click', { clientX: 180, clientY: 300 })
    expect(wrapper.find('.wish-modal').classes()).toContain('is-visible')
    expect(wrapper.find('.wish-modal input').element.value).toBe('还没写完的愿望')

    await wrapper.find('.wish-close').trigger('click')
    expect(wrapper.find('.wish-modal').classes()).not.toContain('is-visible')

    wrapper.unmount()
  })

  it('请求进行中禁止重复许愿，并使用提交时的坐标', async () => {
    const request = deferred()
    mockCreate.mockReturnValue(request.promise)

    const wrapper = await mountView()
    await flushPromises()
    await wrapper.find('#sky').trigger('click', { clientX: 100, clientY: 120 })
    await wrapper.find('.wish-modal input').setValue('一直在一起')

    const submit = wrapper.find('.wish-submit')
    await submit.trigger('click')
    await submit.trigger('click')

    expect(mockCreate).toHaveBeenCalledTimes(1)
    const payload = mockCreate.mock.calls[0][0]
    expect(payload.content).toBe('一直在一起')
    expect(payload.x).toBeGreaterThan(0)
    expect(payload.y).toBeGreaterThan(0)
    expect(submit.attributes('disabled')).toBeDefined()

    request.resolve({ ok: true, id: 9 })
    await flushPromises()
    expect(wrapper.text()).toContain('1 颗星')

    wrapper.unmount()
  })
})
