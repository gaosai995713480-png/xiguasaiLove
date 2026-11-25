import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'

const mockBack = vi.fn()
const mockPush = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({
    back: mockBack,
    push: mockPush,
  }),
}))

describe('TopBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.documentElement.style.removeProperty('--topbar-actual-height')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    document.documentElement.style.removeProperty('--topbar-actual-height')
  })

  it('没有自定义 back 监听时点击返回执行默认路由返回', async () => {
    const { default: TopBar } = await import('../components/TopBar.vue')
    const wrapper = mount(TopBar, {
      props: { title: '旅行星辰' },
      global: {
        stubs: {
          ThemeSwitcher: { template: '<div />' },
        },
      },
    })

    await wrapper.find('.back-btn').trigger('click')

    expect(mockBack).toHaveBeenCalledTimes(1)
  })

  it('有自定义 back 监听时只触发父组件逻辑，不重复路由返回', async () => {
    const onBack = vi.fn()
    const { default: TopBar } = await import('../components/TopBar.vue')
    const wrapper = mount(TopBar, {
      props: { title: '旅行星辰', onBack },
      global: {
        stubs: {
          ThemeSwitcher: { template: '<div />' },
        },
      },
    })

    await wrapper.find('.back-btn').trigger('click')

    expect(onBack).toHaveBeenCalledTimes(1)
    expect(mockBack).not.toHaveBeenCalled()
  })

  it('渲染副标题，并通过 ResizeObserver 同步实际顶栏高度', async () => {
    let measuredHeight = 112
    let resizeCallback = null
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback) {
        resizeCallback = callback
      }
      observe() {}
      disconnect() {}
    })

    const originalRect = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function () {
      if (this.classList?.contains('top-bar')) {
        return { height: measuredHeight }
      }
      return originalRect.call(this)
    })

    const { default: TopBar } = await import('../components/TopBar.vue')
    const wrapper = mount(TopBar, {
      props: {
        title: '音乐时光',
        subtitle: '共 12 首歌曲',
      },
      global: {
        stubs: {
          ThemeSwitcher: { template: '<div />' },
        },
      },
    })

    await nextTick()
    await nextTick()
    expect(wrapper.get('.subtitle').text()).toBe('共 12 首歌曲')
    expect(document.documentElement.style.getPropertyValue('--topbar-actual-height')).toBe('112px')

    measuredHeight = 160
    resizeCallback?.()
    await nextTick()
    expect(document.documentElement.style.getPropertyValue('--topbar-actual-height')).toBe('160px')

    wrapper.unmount()
    expect(document.documentElement.style.getPropertyValue('--topbar-actual-height')).toBe('')
  })
})
