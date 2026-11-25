import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick, reactive } from 'vue'

const mockPush = vi.fn()
const route = reactive({ path: '/' })
const authState = { isAdmin: false }

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
  useRoute: () => route,
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => authState,
}))

async function mountNav() {
  const { default: NavSidebar } = await import('../components/NavSidebar.vue')
  return mount(NavSidebar, {
    attachTo: document.body,
    global: {
      stubs: {
        Teleport: true,
        Transition: false,
      },
    },
  })
}

function panelText(wrapper) {
  const panel = wrapper.find('.panel-card')
  expect(panel.exists()).toBe(true)
  return panel.text()
}

describe('NavSidebar 手机底部导航', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    route.path = '/'
    authState.isAdmin = false
    document.body.innerHTML = ''
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('点击心情会跳转到心情页并关闭面板', async () => {
    const wrapper = await mountNav()
    await wrapper.get('[data-tab="mood"]').trigger('click')
    expect(mockPush).toHaveBeenCalledWith('/mood')
    expect(wrapper.find('.panel-card').exists()).toBe(false)
    wrapper.unmount()
  })

  it('点击回忆打开包含相册和时间轴的面板', async () => {
    const wrapper = await mountNav()
    await wrapper.get('[data-tab="memories"]').trigger('click')
    const text = panelText(wrapper)
    expect(text).toContain('心动画廊')
    expect(text).toContain('时间轴')
    expect(text).toContain('恋爱地图')
    wrapper.unmount()
  })

  it('更多面板不重复心情和音乐主入口', async () => {
    const wrapper = await mountNav()
    await wrapper.get('[data-tab="more"]').trigger('click')
    const text = panelText(wrapper)
    expect(text).toContain('表白信')
    expect(text).toContain('点歌台')
    expect(text).toContain('我们的小厨房')
    expect(text).toContain('账号与安全')
    expect(text).not.toContain('心情日历')
    expect(text).not.toContain('音乐时光')
    expect(text).not.toContain('用户管理')
    wrapper.unmount()
  })

  it('所有用户可从手机或桌面更多面板进入账号与安全', async () => {
    const wrapper = await mountNav()

    await wrapper.get('[data-tab="more"]').trigger('click')
    const mobileItem = wrapper.findAll('.panel-item')
      .find((btn) => btn.text().includes('账号与安全'))
    expect(mobileItem).toBeTruthy()
    await mobileItem.trigger('click')
    expect(mockPush).toHaveBeenCalledWith('/account')

    await wrapper.get('[data-desktop-tab="more"]').trigger('click')
    expect(panelText(wrapper)).toContain('账号与安全')

    wrapper.unmount()
  })

  it('管理员在更多里能看到用户管理', async () => {
    authState.isAdmin = true
    const wrapper = await mountNav()
    await wrapper.get('[data-tab="more"]').trigger('click')
    expect(panelText(wrapper)).toContain('用户管理')
    wrapper.unmount()
  })

  it('从更多面板打开 AI 助手事件并关闭面板', async () => {
    const onOpenAi = vi.fn()
    window.addEventListener('ai-chat:open', onOpenAi)
    const wrapper = await mountNav()

    await wrapper.get('[data-tab="more"]').trigger('click')
    const item = wrapper.findAll('.panel-item').find((btn) => btn.text().includes('AI 助手'))
    expect(item).toBeTruthy()
    await item.trigger('click')

    expect(onOpenAi).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.panel-card').exists()).toBe(false)

    window.removeEventListener('ai-chat:open', onOpenAi)
    wrapper.unmount()
  })

  it('路由变化后自动关闭底部面板', async () => {
    const wrapper = await mountNav()
    await wrapper.get('[data-tab="more"]').trigger('click')
    expect(wrapper.find('.panel-card').exists()).toBe(true)

    route.path = '/mood'
    await nextTick()

    expect(wrapper.find('.panel-card').exists()).toBe(false)
    wrapper.unmount()
  })

  it('当前在相册时回忆 Tab 为激活态', async () => {
    route.path = '/gallery'
    const wrapper = await mountNav()
    expect(wrapper.get('[data-tab="memories"]').classes()).toContain('is-active')
    expect(wrapper.get('[data-tab="home"]').classes()).not.toContain('is-active')
    wrapper.unmount()
  })

  it('从面板进入页面会关闭面板', async () => {
    const wrapper = await mountNav()
    await wrapper.get('[data-tab="memories"]').trigger('click')
    const item = wrapper.findAll('.panel-item').find((btn) => btn.text().includes('心动画廊'))
    expect(item).toBeTruthy()
    await item.trigger('click')
    expect(mockPush).toHaveBeenCalledWith('/gallery')
    expect(wrapper.find('.panel-card').exists()).toBe(false)
    wrapper.unmount()
  })
})
