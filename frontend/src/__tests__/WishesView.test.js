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

  it('请求进行中禁止重复许愿，并使用提交时的坐标', async () => {
    const request = deferred()
    mockCreate.mockReturnValue(request.promise)

    const wrapper = await mountView()
    await flushPromises()
    await wrapper.find('#sky').trigger('click', { clientX: 100, clientY: 120 })
    await wrapper.find('.wish-modal input').setValue('一直在一起')

    const submit = wrapper.find('.wish-modal button')
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
