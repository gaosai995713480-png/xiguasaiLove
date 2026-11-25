import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'

const mockListUsers = vi.fn()
const mockGetInviteCode = vi.fn()
const mockListKeys = vi.fn()
const mockResetUserPassword = vi.fn()

const authState = reactive({
  isAdmin: true,
  username: 'admin',
})

vi.mock('../api/index.js', () => ({
  usersApi: {
    list: (...args) => mockListUsers(...args),
    toggle: vi.fn(),
    getInviteCode: (...args) => mockGetInviteCode(...args),
    updateInviteCode: vi.fn(),
    resetUserPassword: (...args) => mockResetUserPassword(...args),
  },
  configApi: {
    listKeys: (...args) => mockListKeys(...args),
    saveKey: vi.fn(),
  },
  backupApi: {
    status: vi.fn().mockResolvedValue({ status: 'idle' }),
    start: vi.fn(),
    download: vi.fn(),
  },
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => authState,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
  }),
}))

const GlassModalStub = {
  props: ['modelValue', 'title'],
  emits: ['update:modelValue'],
  template: `
    <div v-if="modelValue" class="glass-modal-stub">
      <h2>{{ title }}</h2>
      <slot />
    </div>
  `,
}

const flushPromises = async () => {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

async function mountView() {
  const { default: UsersView } = await import('../views/UsersView.vue')
  return mount(UsersView, {
    global: {
      stubs: {
        TopBar: { template: '<div><slot /></div>' },
        GlassModal: GlassModalStub,
      },
    },
  })
}

describe('UsersView 重置密码', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.isAdmin = true
    authState.username = 'admin'
    mockListUsers.mockResolvedValue([
      {
        id: 1,
        username: 'admin',
        role: 'admin',
        disabled: false,
        created_at: '2026-01-01 00:00:00',
        last_login_at: null,
      },
      {
        id: 2,
        username: 'other_admin',
        role: 'admin',
        disabled: false,
        created_at: '2026-01-02 00:00:00',
        last_login_at: null,
      },
      {
        id: 3,
        username: 'disabled_guest',
        role: 'visitor',
        disabled: true,
        created_at: '2026-01-03 00:00:00',
        last_login_at: null,
      },
    ])
    mockGetInviteCode.mockResolvedValue({ code: 'love2023' })
    mockListKeys.mockResolvedValue({ items: [] })
    mockResetUserPassword.mockResolvedValue({ ok: true })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('当前账号不显示重置入口，其他管理员和禁用用户仍可重置', async () => {
    const wrapper = await mountView()
    await flushPromises()

    expect(wrapper.find('[data-test="reset-password-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="reset-password-2"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="reset-password-3"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="toggle-user-3"]').text()).toBe('启用')

    wrapper.unmount()
  })

  it('校验密码长度和一致性后再提交重置', async () => {
    const wrapper = await mountView()
    await flushPromises()

    await wrapper.get('[data-test="reset-password-3"]').trigger('click')
    expect(wrapper.get('.glass-modal-stub').text()).toContain('disabled_guest')

    await wrapper.get('[data-test="reset-password-input"]').setValue('short')
    await wrapper.get('[data-test="reset-password-confirm"]').setValue('short')
    await wrapper.get('.reset-password-form').trigger('submit')
    expect(wrapper.text()).toContain('新密码长度需为 8-128 个字符')
    expect(mockResetUserPassword).not.toHaveBeenCalled()

    await wrapper.get('[data-test="reset-password-input"]').setValue('new-password-1')
    await wrapper.get('[data-test="reset-password-confirm"]').setValue('new-password-2')
    await wrapper.get('.reset-password-form').trigger('submit')
    expect(wrapper.text()).toContain('两次输入的新密码不一致')
    expect(mockResetUserPassword).not.toHaveBeenCalled()

    await wrapper.get('[data-test="reset-password-confirm"]').setValue('new-password-1')
    await wrapper.get('.reset-password-form').trigger('submit')
    await flushPromises()

    expect(mockResetUserPassword).toHaveBeenCalledWith(3, 'new-password-1')
    expect(wrapper.find('.glass-modal-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain('已重置「disabled_guest」的密码')

    wrapper.unmount()
  })

  it('显示后端返回的重置错误', async () => {
    mockResetUserPassword.mockRejectedValueOnce(new Error('用户不存在'))
    const wrapper = await mountView()
    await flushPromises()

    await wrapper.get('[data-test="reset-password-2"]').trigger('click')
    await wrapper.get('[data-test="reset-password-input"]').setValue('new-password-1')
    await wrapper.get('[data-test="reset-password-confirm"]').setValue('new-password-1')
    await wrapper.get('.reset-password-form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('用户不存在')
    expect(wrapper.find('.glass-modal-stub').exists()).toBe(true)

    wrapper.unmount()
  })
})
