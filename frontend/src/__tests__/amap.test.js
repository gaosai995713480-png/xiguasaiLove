import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mockGetMapConfig = vi.fn()

vi.mock('../api/index.js', () => ({
  tripstarApi: {
    getMapConfig: (...args) => mockGetMapConfig(...args),
  },
}))

const flushPromises = () => Promise.resolve().then(() => Promise.resolve())

function config(overrides = {}) {
  return {
    configured: true,
    amap_web_js_key: 'test-web-key',
    amap_security_js_code: 'test-security-code',
    ...overrides,
  }
}

describe('loadAmapFromConfig', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    delete window.AMap
    delete window._AMapSecurityConfig
    document.getElementById('shared-amap-js-sdk')?.remove()
  })

  afterEach(() => {
    vi.useRealTimers()
    delete window.AMap
    delete window._AMapSecurityConfig
    document.getElementById('shared-amap-js-sdk')?.remove()
  })

  it('从后端配置生成脚本地址并加载插件', async () => {
    mockGetMapConfig.mockResolvedValue(config())
    const { loadAmapFromConfig } = await import('../utils/amap')

    const loading = loadAmapFromConfig({ plugins: ['AMap.Geocoder'] })
    await flushPromises()

    const script = document.getElementById('shared-amap-js-sdk')
    expect(script).toBeTruthy()
    expect(script.src).toContain('key=test-web-key')
    expect(script.src).toContain('plugin=AMap.Geocoder')
    expect(window._AMapSecurityConfig.securityJsCode).toBe('test-security-code')

    const plugin = vi.fn((plugins, callback) => callback())
    window.AMap = { Map: vi.fn(), plugin }
    script.dispatchEvent(new Event('load'))

    await expect(loading).resolves.toBe(window.AMap)
    expect(plugin).toHaveBeenCalledWith(['AMap.Geocoder'], expect.any(Function))
  })

  it('脚本错误时 reject，而不是永久 pending', async () => {
    mockGetMapConfig.mockResolvedValue(config())
    const { loadAmapFromConfig } = await import('../utils/amap')

    const loading = loadAmapFromConfig()
    const assertion = expect(loading).rejects.toThrow('SDK 加载失败')
    await flushPromises()

    document.getElementById('shared-amap-js-sdk').dispatchEvent(new Event('error'))
    await assertion
  })

  it('脚本 12 秒未加载时超时 reject', async () => {
    vi.useFakeTimers()
    mockGetMapConfig.mockResolvedValue(config())
    const { loadAmapFromConfig } = await import('../utils/amap')

    const loading = loadAmapFromConfig()
    const assertion = expect(loading).rejects.toThrow('SDK 加载超时')
    await Promise.resolve()
    await Promise.resolve()

    await vi.advanceTimersByTimeAsync(12_000)
    await assertion
  })

  it('配置缺失时给出明确错误且不创建脚本', async () => {
    mockGetMapConfig.mockResolvedValue({
      configured: false,
      amap_web_js_key: '',
      amap_security_js_code: '',
      message: '未配置高德前端 Key',
    })
    const { loadAmapFromConfig } = await import('../utils/amap')

    await expect(loadAmapFromConfig()).rejects.toThrow('未配置高德前端 Key')
    expect(document.getElementById('shared-amap-js-sdk')).toBeNull()
  })
})
