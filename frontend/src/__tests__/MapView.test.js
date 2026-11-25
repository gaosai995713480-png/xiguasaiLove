import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const mockList = vi.fn()
const mockLoadAmap = vi.fn()
const mockPush = vi.fn()

vi.mock('../api/index.js', () => ({
  mapApi: {
    list: (...args) => mockList(...args),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    upload: vi.fn(),
    cleanupUploads: vi.fn(),
  },
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => ({ isAdmin: true }),
}))

vi.mock('../utils/amap', () => ({
  loadAmapFromConfig: (...args) => mockLoadAmap(...args),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
}))

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0))
const mountedWrappers = []

async function mountView() {
  const { default: MapView } = await import('../views/MapView.vue')
  const wrapper = mount(MapView, {
    global: {
      stubs: {
        TopBar: { template: '<div><slot /></div>' },
        GlassModal: {
          props: ['modelValue', 'title'],
          template: '<div v-if="modelValue"><slot /></div>',
        },
      },
    },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

function createAMapStub() {
  const map = {
    on: vi.fn(),
    off: vi.fn(),
    add: vi.fn(),
    remove: vi.fn(),
    destroy: vi.fn(),
    setFitView: vi.fn(),
    setZoomAndCenter: vi.fn(),
    getCenter: () => ({ lat: 30.6, lng: 114.3 }),
  }
  return {
    Map: vi.fn(function MapStub() { return map }),
    Marker: vi.fn(function MarkerStub() { return { on: vi.fn() } }),
    Polyline: vi.fn(function PolylineStub() { return {} }),
    Pixel: vi.fn(function PixelStub(x, y) { this.x = x; this.y = y }),
    Geocoder: vi.fn(function GeocoderStub() {
      this.getAddress = (_position, callback) => callback('complete', {
        regeocode: { formattedAddress: '中国湖北省武汉市测试地点' },
      })
    }),
    PlaceSearch: vi.fn(function PlaceSearchStub() {
      this.search = (_keyword, callback) => callback('complete', { poiList: { pois: [] } })
    }),
    plugin: (_plugins, callback) => callback(),
  }
}

describe('MapView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockList.mockResolvedValue([])
    mockLoadAmap.mockRejectedValue(new Error('高德地图配置加载失败'))
  })

  afterEach(() => {
    while (mountedWrappers.length) mountedWrappers.pop().unmount()
    vi.unstubAllGlobals()
  })

  it('地图加载失败时禁用搜索和添加，并显示恢复入口', async () => {
    const wrapper = await mountView()
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('高德地图配置加载失败')
    expect(wrapper.find('.search-box input').element.disabled).toBe(true)
    expect(wrapper.find('.fab-add').element.disabled).toBe(true)
    expect(wrapper.find('.map-retry').text()).toBe('重新加载')
    expect(mockList).not.toHaveBeenCalled()
  })

  it('点击重新加载后恢复地图和相关操作', async () => {
    mockLoadAmap
      .mockRejectedValueOnce(new Error('高德地图配置加载失败'))
      .mockResolvedValueOnce({})

    const wrapper = await mountView()
    await flushPromises()
    vi.stubGlobal('AMap', createAMapStub())

    await wrapper.find('.map-retry').trigger('click')
    await flushPromises()

    expect(mockLoadAmap).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.find('.search-box input').element.disabled).toBe(false)
    expect(wrapper.find('.fab-add').element.disabled).toBe(false)
    expect(mockList).toHaveBeenCalledTimes(1)
  })
})
