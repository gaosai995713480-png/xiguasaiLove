import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'

const mockChangeOwnPassword = vi.fn()
const mockChangeGalleryPassword = vi.fn()
const mockLogout = vi.fn()
const mockReplace = vi.fn()
const mockSuccess = vi.fn()

const authState = reactive({
  username: 'admin',
  isAdmin: true,
  logout: (...args) => mockLogout(...args),
})

vi.mock('../api/index.js', () => ({
  usersApi: {
    changeOwnPassword: (...args) => mockChangeOwnPassword(...args),
  },
  galleryApi: {
    changePassword: (...args) => mockChangeGalleryPassword(...args),
  },
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => authState,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    replace: mockReplace,
    push: vi.fn(),
  }),
}))

vi.mock('../composables/useToast', () => ({
  useToast: () => ({
    success: mockSuccess,
  }),
}))

const flushPromises = async () => {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

async function mountView() {
  const { default: AccountView } = await import('../views/AccountView.vue')
  return mount(AccountView, {
    global: {
      stubs: {
        TopBar: { template: '<div><slot /></div>' },
      },
    },
  })
}

function fillOwnPassword(wrapper, oldPassword, newPassword, confirmPassword) {
  const inputs = wrapper.findAll('input[type="password"]')
  return Promise.all([
    inputs[0].setValue(oldPassword),
    inputs[1].setValue(newPassword),
    inputs[2].setValue(confirmPassword),
  ])
}

function fillGalleryPassword(wrapper, oldPassword, newPassword, confirmPassword) {
  const inputs = wrapper.findAll('input[type="password"]')
  return Promise.all([
    inputs[3].setValue(oldPassword),
    inputs[4].setValue(newPassword),
    inputs[5].setValue(confirmPassword),
  ])
}

describe('AccountView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.username = 'admin'
    authState.isAdmin = true
    mockChangeOwnPassword.mockResolvedValue({ ok: true, reauthenticate: true })
    mockChangeGalleryPassword.mockResolvedValue({ ok: true })
    mockLogout.mockResolvedValue()
    sessionStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('普通用户只显示登录密码，管理员额外显示画廊密码', async () => {
    authState.isAdmin = false
    const visitorWrapper = await mountView()
    expect(visitorWrapper.find('[data-test="gallery-password-card"]').exists()).toBe(false)
    expect(visitorWrapper.text()).toContain('修改登录密码')
    visitorWrapper.unmount()

    authState.isAdmin = true
    const adminWrapper = await mountView()
    expect(adminWrapper.find('[data-test="gallery-password-card"]').exists()).toBe(true)
    adminWrapper.unmount()
  })

  it('校验登录密码长度和两次输入一致', async () => {
    const wrapper = await mountView()
    const form = wrapper.get('.password-form')

    await fillOwnPassword(wrapper, 'old-password', 'short', 'short')
    await form.trigger('submit')
    expect(wrapper.text()).toContain('新密码长度需为 8-128 个字符')
    expect(mockChangeOwnPassword).not.toHaveBeenCalled()

    await fillOwnPassword(wrapper, 'old-password', 'new-password-1', 'new-password-2')
    await form.trigger('submit')
    expect(wrapper.text()).toContain('两次输入的新密码不一致')
    expect(mockChangeOwnPassword).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('登录密码修改成功后清理会话、提示并跳转登录页', async () => {
    const wrapper = await mountView()

    await fillOwnPassword(wrapper, 'old-password', 'new-password-1', 'new-password-1')
    await wrapper.get('.password-form').trigger('submit')
    await flushPromises()

    expect(mockChangeOwnPassword).toHaveBeenCalledWith('old-password', 'new-password-1')
    expect(mockLogout).toHaveBeenCalledTimes(1)
    expect(mockSuccess).toHaveBeenCalledWith(
      expect.stringContaining('重新登录'),
      5000,
    )
    expect(mockReplace).toHaveBeenCalledWith('/login')
    wrapper.unmount()
  })

  it('校验画廊密码长度和两次输入一致', async () => {
    const wrapper = await mountView()
    const galleryForm = wrapper.findAll('.password-form')[1]

    await fillGalleryPassword(wrapper, 'old-gallery', 'abc', 'abc')
    await galleryForm.trigger('submit')
    expect(wrapper.text()).toContain('新画廊密码长度需为 4-128 个字符')
    expect(mockChangeGalleryPassword).not.toHaveBeenCalled()

    await fillGalleryPassword(wrapper, 'old-gallery', 'new-gallery-1', 'new-gallery-2')
    await galleryForm.trigger('submit')
    expect(wrapper.text()).toContain('两次输入的新画廊密码不一致')
    expect(mockChangeGalleryPassword).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('管理员修改画廊密码成功后清除本地解锁状态并提示重新锁定', async () => {
    sessionStorage.setItem('gallery_unlocked', '1')
    const wrapper = await mountView()
    const galleryForm = wrapper.findAll('.password-form')[1]

    await fillGalleryPassword(wrapper, 'old-gallery', 'new-gallery', 'new-gallery')
    await galleryForm.trigger('submit')
    await flushPromises()

    expect(mockChangeGalleryPassword).toHaveBeenCalledWith('old-gallery', 'new-gallery')
    expect(sessionStorage.getItem('gallery_unlocked')).toBeNull()
    expect(wrapper.text()).toContain('所有会话已重新锁定')
    expect(mockSuccess).toHaveBeenCalledWith(
      '画廊密码已修改，所有会话已重新锁定。',
      5000,
    )
    wrapper.unmount()
  })
})
