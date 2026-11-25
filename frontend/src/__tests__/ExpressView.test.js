import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'

const mockCompanies = vi.fn()
const mockDetect = vi.fn()
const mockQuery = vi.fn()
const mockGetConfig = vi.fn()
const mockUpdateConfig = vi.fn()
const mockPush = vi.fn()
const mockGetMapConfig = vi.fn()
const authState = reactive({ isAdmin: false })

vi.mock('../api/index.js', () => ({
  expressApi: {
    companies: (...args) => mockCompanies(...args),
    detect: (...args) => mockDetect(...args),
    query: (...args) => mockQuery(...args),
    getConfig: (...args) => mockGetConfig(...args),
    updateConfig: (...args) => mockUpdateConfig(...args),
  },
  tripstarApi: {
    getMapConfig: (...args) => mockGetMapConfig(...args),
  },
}))

vi.mock('../stores/auth.js', () => ({
  useAuthStore: () => authState,
}))

vi.mock('../stores/context', () => ({
  useContextStore: () => ({
    setPageState: vi.fn(),
  }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}))

const flushPromises = async () => {
  await Promise.resolve()
  await Promise.resolve()
}

function deferred() {
  let resolve
  const promise = new Promise((res) => { resolve = res })
  return { promise, resolve }
}

describe('ExpressView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
    authState.isAdmin = false
    localStorage.clear()
    mockCompanies.mockResolvedValue({
      companies: [
        { code: 'shunfeng', name: '顺丰速运' },
        { code: 'zhongtong', name: '中通快递' },
      ],
    })
    mockDetect.mockResolvedValue({ auto: [] })
    mockQuery.mockResolvedValue({ status: '200', message: 'ok', data: [] })
    mockGetConfig.mockResolvedValue({ customer_configured: false, key_configured: false })
    mockUpdateConfig.mockResolvedValue({ ok: true, updated: 1 })
    mockGetMapConfig.mockResolvedValue({
      configured: false,
      amap_web_js_key: '',
      amap_security_js_code: '',
      message: '未配置',
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('点击历史记录时会恢复手机号并带入查询', async () => {
    localStorage.setItem('express_history', JSON.stringify([
      {
        num: 'SF1234567890',
        com: 'shunfeng',
        comName: '顺丰速运',
        phone: '1234',
        time: '2026/03/24 20:00:00',
      },
    ]))

    const { default: ExpressView } = await import('../views/ExpressView.vue')
    const wrapper = mount(ExpressView, {
      global: {
        stubs: {
          TopBar: { template: '<div><slot /></div>' },
        },
      },
    })

    await flushPromises()
    await wrapper.find('.history-item').trigger('click')
    await flushPromises()

    expect(mockQuery).toHaveBeenCalledWith('SF1234567890', 'shunfeng', '1234')
  })

  it('手机号使用数字键盘，管理员配置头是可访问的按钮', async () => {
    authState.isAdmin = true

    const { default: ExpressView } = await import('../views/ExpressView.vue')
    const wrapper = mount(ExpressView, {
      global: {
        stubs: {
          TopBar: { template: '<div><slot /></div>' },
        },
      },
    })

    await flushPromises()
    await wrapper.find('#express-com-select').setValue('shunfeng')

    const phoneInput = wrapper.get('#express-phone-input')
    expect(phoneInput.attributes('type')).toBe('tel')
    expect(phoneInput.attributes('inputmode')).toBe('numeric')

    const toggle = wrapper.get('[data-test="express-config-toggle"]')
    expect(toggle.element.tagName).toBe('BUTTON')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.attributes('aria-controls')).toBe('express-config-body')

    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('#express-config-body').exists()).toBe(true)
  })

  it('单号缩短到 6 位以下时会立即结束识别中状态', async () => {
    vi.useFakeTimers()

    const { default: ExpressView } = await import('../views/ExpressView.vue')
    const wrapper = mount(ExpressView, {
      global: {
        stubs: {
          TopBar: { template: '<div><slot /></div>' },
        },
      },
    })

    await flushPromises()

    const trackingInput = wrapper.find('#express-num-input')
    await trackingInput.setValue('123456')
    await flushPromises()
    expect(wrapper.find('.input-suffix').exists()).toBe(true)

    await trackingInput.setValue('12345')
    await flushPromises()

    expect(wrapper.find('.input-suffix').exists()).toBe(false)
  })

  it('旧查询晚返回时不会覆盖新查询结果', async () => {
    localStorage.setItem('express_history', JSON.stringify([
      { num: 'SF000001', com: 'shunfeng', comName: '顺丰速运', phone: '', time: '旧' },
      { num: 'ZT000002', com: 'zhongtong', comName: '中通快递', phone: '', time: '新' },
    ]))
    const first = deferred()
    const second = deferred()
    mockQuery.mockImplementation((num) => (
      num === 'SF000001' ? first.promise : second.promise
    ))

    const { default: ExpressView } = await import('../views/ExpressView.vue')
    const wrapper = mount(ExpressView, {
      global: {
        stubs: {
          TopBar: { template: '<div><slot /></div>' },
        },
      },
    })
    await flushPromises()

    const historyItems = wrapper.findAll('.history-item')
    await historyItems[0].trigger('click')
    await historyItems[1].trigger('click')

    second.resolve({
      status: '200',
      message: 'ok',
      com: '中通快递',
      nu: 'ZT000002',
      state: '0',
      data: [],
    })
    await flushPromises()
    expect(wrapper.text()).toContain('ZT000002')

    first.resolve({
      status: '200',
      message: 'ok',
      com: '顺丰速运',
      nu: 'SF000001',
      state: '0',
      data: [],
    })
    await flushPromises()

    expect(wrapper.text()).toContain('ZT000002')
    expect(wrapper.text()).not.toContain('SF000001')
  })

  it('历史记录使用请求开始时的单号快照', async () => {
    const request = deferred()
    mockQuery.mockReturnValue(request.promise)

    const { default: ExpressView } = await import('../views/ExpressView.vue')
    const wrapper = mount(ExpressView, {
      global: {
        stubs: {
          TopBar: { template: '<div><slot /></div>' },
        },
      },
    })
    await flushPromises()

    await wrapper.find('#express-num-input').setValue('SNAPSHOT-A')
    await wrapper.find('#express-com-select').setValue('shunfeng')
    await wrapper.find('#express-phone-input').setValue('1234')
    await wrapper.find('#express-query-btn').trigger('click')
    await wrapper.find('#express-num-input').setValue('CHANGED-B')
    await wrapper.find('#express-phone-input').setValue('9999')

    request.resolve({
      status: '200',
      message: 'ok',
      com: '顺丰速运',
      nu: 'SNAPSHOT-A',
      state: '0',
      data: [],
    })
    await flushPromises()

    const history = JSON.parse(localStorage.getItem('express_history'))
    expect(history[0].num).toBe('SNAPSHOT-A')
    expect(history[0].phone).toBe('1234')
  })
})
