import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { mount } from '@vue/test-utils'

const mockList = vi.fn()
const mockCreate = vi.fn()
const mockOpen = vi.fn()
const mockToastError = vi.fn()
const mockToastSuccess = vi.fn()
const authState = reactive({ isAdmin: true })

vi.mock('../api/index.js', () => ({
  capsuleApi: {
    list: (...args) => mockList(...args),
    create: (...args) => mockCreate(...args),
    open: (...args) => mockOpen(...args),
  },
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => authState,
}))

vi.mock('../composables/useToast', () => ({
  useToast: () => ({
    error: mockToastError,
    success: mockToastSuccess,
  }),
}))

const flushPromises = () => Promise.resolve().then(() => Promise.resolve())

async function mountView() {
  const { default: CapsuleSection } = await import('../components/CapsuleSection.vue')
  return mount(CapsuleSection, {
    global: {
      stubs: {
        GlassModal: {
          props: ['modelValue'],
          template: '<div v-if="modelValue" class="capsule-modal-test"><slot /></div>',
        },
      },
    },
  })
}

describe('CapsuleSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.isAdmin = true
    mockList.mockResolvedValue([])
    mockCreate.mockResolvedValue({ ok: true, id: 1 })
  })

  it('管理员在空胶囊状态也能创建胶囊', async () => {
    const wrapper = await mountView()
    await flushPromises()

    expect(wrapper.find('.capsule-create-btn').exists()).toBe(true)
    expect(wrapper.text()).toContain('还没有时间胶囊')

    await wrapper.find('.capsule-create-btn').trigger('click')
    await wrapper.find('.capsule-form textarea').setValue('给未来的信')
    await wrapper.find('.capsule-form input[type="date"]').setValue('2027-01-01')
    await wrapper.find('.capsule-form button.btn-primary').trigger('click')
    await flushPromises()

    expect(mockCreate).toHaveBeenCalledWith({
      content: '给未来的信',
      open_date: '2027-01-01',
    })
    expect(mockList).toHaveBeenCalledTimes(2)
    expect(mockToastSuccess).toHaveBeenCalled()
  })

  it('优先使用后端 can_open，而不是自行比较日期', async () => {
    mockList.mockResolvedValue([
      {
        id: 1,
        content: null,
        open_date: '2020-01-01',
        is_opened: false,
        can_open: false,
      },
    ])
    authState.isAdmin = false

    const wrapper = await mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('2020-01-01')
    expect(wrapper.findAll('button').some(button => button.text().includes('开启'))).toBe(false)
  })
})
