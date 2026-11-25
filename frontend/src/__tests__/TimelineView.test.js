import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { mount } from '@vue/test-utils'

const mockList = vi.fn()
const mockCreate = vi.fn()
const mockRemove = vi.fn()
const mockPush = vi.fn()
const authState = reactive({ isAdmin: true })

vi.mock('../api/index.js', () => ({
  timelineApi: {
    list: (...args) => mockList(...args),
    create: (...args) => mockCreate(...args),
    remove: (...args) => mockRemove(...args),
  },
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => authState,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
}))

const flushPromises = () => Promise.resolve().then(() => Promise.resolve())

async function mountView() {
  const { default: TimelineView } = await import('../views/TimelineView.vue')
  return mount(TimelineView, {
    global: {
      stubs: {
        TopBar: { template: '<div class="top-bar"><slot /></div>' },
        GlassModal: {
          props: ['modelValue', 'title'],
          template: '<div v-if="modelValue" class="glass-modal-stub"><slot /></div>',
        },
      },
    },
  })
}

describe('TimelineView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.isAdmin = true
    mockList.mockResolvedValue([])
    mockCreate.mockResolvedValue({ ok: true, id: 2 })
    mockRemove.mockResolvedValue({ ok: true })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('为时间轴图片预留比例，删除按钮保留可访问名称', async () => {
    mockList.mockResolvedValue([
      {
        id: 1,
        event_date: '2026-11-25',
        title: '照片事件',
        content: '长内容',
        photo_url: '/photos/timeline.jpg',
      },
    ])
    vi.stubGlobal('confirm', vi.fn(() => true))

    const wrapper = await mountView()
    await flushPromises()

    const photo = wrapper.find('img.photo')
    expect(photo.attributes('width')).toBe('1600')
    expect(photo.attributes('height')).toBe('900')

    const deleteButton = wrapper.find('.delete-btn')
    expect(deleteButton.attributes('aria-label')).toBe('删除这条时间轴记录')
    await deleteButton.trigger('click')
    await flushPromises()

    expect(mockRemove).toHaveBeenCalledWith(1)
    expect(mockList).toHaveBeenCalledTimes(2)
  })

  it('管理员可以打开新增弹窗并提交标题和日期', async () => {
    const wrapper = await mountView()
    await flushPromises()

    await wrapper.find('.add-btn').trigger('click')
    const inputs = wrapper.findAll('.form-group input')
    await inputs[1].setValue('第一次一起看海')
    await wrapper.find('.form-actions .btn-primary').trigger('click')
    await flushPromises()

    expect(mockCreate).toHaveBeenCalledWith(expect.objectContaining({
      title: '第一次一起看海',
      event_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    }))
    expect(wrapper.find('.glass-modal-stub').exists()).toBe(false)
  })
})
