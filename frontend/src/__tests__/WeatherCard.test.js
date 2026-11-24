import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const mockWeather = vi.fn()
const mockDistrict = vi.fn()
const mockLocate = vi.fn()

vi.mock('../api/index.js', () => ({
  weatherApi: {
    weather: (...args) => mockWeather(...args),
    district: (...args) => mockDistrict(...args),
    locate: (...args) => mockLocate(...args),
  },
}))

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0))

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('WeatherCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    localStorage.setItem('weather_adcode', '420100')

    mockWeather.mockImplementation((city, extensions) => {
      if (extensions === 'base') {
        return Promise.resolve({
          status: '1',
          lives: [
            {
              city: '武汉',
              weather: '晴',
              temperature: '26',
              winddirection: '东',
              windpower: '3',
              humidity: '48',
              reporttime: '2026-05-07 10:00:00',
            },
          ],
        })
      }

      return Promise.resolve({
        status: '1',
        forecasts: [
          {
            city: '武汉',
            casts: [
              { date: '2026-05-07', dayweather: '晴', nighttemp: '18', daytemp: '27' },
              { date: '2026-05-08', dayweather: '多云', nighttemp: '19', daytemp: '28' },
              { date: '2026-05-09', dayweather: '小雨', nighttemp: '20', daytemp: '26' },
            ],
          },
        ],
      })
    })

    mockDistrict.mockResolvedValue({ status: '1', districts: [] })
    mockLocate.mockResolvedValue({ adcode: '420100' })
  })

  it('默认展开并可通过按钮收起再展开', async () => {
    const { default: WeatherCard } = await import('../components/WeatherCard.vue')
    const wrapper = mount(WeatherCard)

    await flushPromises()

    expect(wrapper.find('.weather-toggle-btn').text()).toContain('收起')
    expect(wrapper.find('.weather-body').exists()).toBe(true)

    await wrapper.find('.weather-toggle-btn').trigger('click')

    expect(wrapper.find('.weather-body').exists()).toBe(false)
    expect(wrapper.find('.weather-toggle-btn').text()).toContain('展开')
    expect(wrapper.text()).toContain('武汉')
    expect(wrapper.text()).toContain('26°')

    await wrapper.find('.weather-toggle-btn').trigger('click')

    expect(wrapper.find('.weather-body').exists()).toBe(true)
    expect(wrapper.find('.weather-toggle-btn').text()).toContain('收起')
  })

  it('旧城市响应晚返回时不会覆盖新城市天气', async () => {
    const { default: WeatherCard } = await import('../components/WeatherCard.vue')
    const wrapper = mount(WeatherCard)
    await flushPromises()

    const beijingBase = deferred()
    const beijingAll = deferred()
    const shanghaiBase = deferred()
    const shanghaiAll = deferred()
    mockWeather.mockImplementation((city, extensions) => {
      const pair = city === '110000'
        ? { base: beijingBase, all: beijingAll }
        : { base: shanghaiBase, all: shanghaiAll }
      return extensions === 'base' ? pair.base.promise : pair.all.promise
    })

    const beijingRequest = wrapper.vm.loadWeather('110000')
    const shanghaiRequest = wrapper.vm.loadWeather('310000')

    shanghaiBase.resolve({
      status: '1',
      lives: [{ city: '上海', weather: '晴', temperature: '28' }],
    })
    shanghaiAll.resolve({
      status: '1',
      forecasts: [{ city: '上海', casts: [] }],
    })
    await shanghaiRequest
    await flushPromises()
    expect(wrapper.text()).toContain('上海')

    beijingBase.resolve({
      status: '1',
      lives: [{ city: '北京', weather: '阴', temperature: '12' }],
    })
    beijingAll.resolve({
      status: '1',
      forecasts: [{ city: '北京', casts: [] }],
    })
    await beijingRequest
    await flushPromises()

    expect(wrapper.text()).toContain('上海')
    expect(wrapper.text()).not.toContain('北京')
  })

  it('切换城市加载失败时清空旧城市数据并显示错误', async () => {
    const { default: WeatherCard } = await import('../components/WeatherCard.vue')
    const wrapper = mount(WeatherCard)
    await flushPromises()
    expect(wrapper.text()).toContain('武汉')

    mockWeather.mockRejectedValue(new Error('network down'))
    await wrapper.vm.loadWeather('999999')
    await flushPromises()

    expect(wrapper.text()).not.toContain('武汉')
    expect(wrapper.text()).toContain('网络错误')
  })
})
