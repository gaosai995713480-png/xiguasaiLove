import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const mockList = vi.fn()
const mockUpload = vi.fn()
const mockImportZip = vi.fn()
const mockVerify = vi.fn()
const mockPush = vi.fn()

vi.mock('../api/index.js', () => ({
  photoApi: {
    list: (...args) => mockList(...args),
    upload: (...args) => mockUpload(...args),
    importZip: (...args) => mockImportZip(...args),
  },
  galleryApi: {
    verify: (...args) => mockVerify(...args),
  },
}))

vi.mock('../stores/auth.js', () => ({
  useAuthStore: () => ({
    isAdmin: true,
  }),
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

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('GalleryView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    sessionStorage.setItem('gallery_unlocked', '1')
    mockList.mockResolvedValue([
      {
        id: 1,
        filename: 'sample.jpg',
        url: '/photos/sample.jpg',
        description: '',
        created_at: '2026-04-16 21:00:00',
      },
    ])
    mockUpload.mockRejectedValue(new Error('上传失败'))
    mockImportZip.mockResolvedValue({ ok: true })
    mockVerify.mockResolvedValue({ ok: true })
  })

  it('上传失败时保留当前列表并展示错误信息', async () => {
    const { default: GalleryView } = await import('../views/GalleryView.vue')
    const wrapper = mount(GalleryView, {
      global: {
        stubs: {
          TopBar: { template: '<div><slot /></div>' },
          Teleport: true,
        },
      },
    })

    await flushPromises()

    const uploadInput = wrapper.find('input[accept="image/*"]')
    const file = new File(['bad'], 'bad.txt', { type: 'text/plain' })
    Object.defineProperty(uploadInput.element, 'files', {
      value: [file],
      configurable: true,
    })
    await uploadInput.trigger('change')
    await flushPromises()

    expect(mockUpload).toHaveBeenCalledTimes(1)
    expect(mockList).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('上传失败')
  })

  it('批量上传部分成功时刷新已上传照片', async () => {
    mockUpload
      .mockResolvedValueOnce({ ok: true, saved: 1, name: 'ok.jpg' })
      .mockRejectedValueOnce(new Error('第二张失败'))

    const { default: GalleryView } = await import('../views/GalleryView.vue')
    const wrapper = mount(GalleryView, {
      global: {
        stubs: {
          TopBar: { template: '<div><slot /></div>' },
          Teleport: true,
        },
      },
    })
    await flushPromises()
    expect(mockList).toHaveBeenCalledTimes(1)

    const uploadInput = wrapper.find('input[accept="image/*"]')
    Object.defineProperty(uploadInput.element, 'files', {
      value: [
        new File(['ok'], 'ok.jpg', { type: 'image/jpeg' }),
        new File(['bad'], 'bad.jpg', { type: 'image/jpeg' }),
      ],
      configurable: true,
    })
    await uploadInput.trigger('change')
    await flushPromises()

    expect(mockUpload).toHaveBeenCalledTimes(2)
    expect(mockList).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('第二张失败')
  })

  it('灯箱保留可滚动长说明，照片日期是可访问按钮', async () => {
    const longDescription = `https://example.com/${'very-long-segment-'.repeat(40)}`
    mockList.mockResolvedValue([
      {
        id: 1,
        filename: 'long.jpg',
        url: '/photos/long.jpg',
        description: longDescription,
        created_at: '2026-04-16 21:00:00',
      },
    ])

    const { default: GalleryView } = await import('../views/GalleryView.vue')
    const wrapper = mount(GalleryView, {
      global: {
        stubs: {
          TopBar: { template: '<div><slot /></div>' },
          Teleport: true,
        },
      },
    })
    await flushPromises()

    const photoDate = wrapper.find('.photo-date')
    expect(photoDate.element.tagName).toBe('BUTTON')
    expect(photoDate.attributes('aria-label')).toContain('2026-04-16')

    await photoDate.trigger('click')
    expect(mockPush).toHaveBeenCalledWith('/day/2026-04-16')
    expect(wrapper.find('.lightbox').classes()).not.toContain('is-active')

    await wrapper.find('.gallery-item').trigger('click')
    const caption = wrapper.find('.lightbox-caption')
    expect(caption.attributes('tabindex')).toBe('0')
    expect(caption.text()).toContain(longDescription)
  })

  it('灯箱手势忽略多指和纵向滑动，只切换单指横滑', async () => {
    mockList.mockResolvedValue([
      { id: 1, filename: '1.jpg', url: '/photos/1.jpg', description: '第一张' },
      { id: 2, filename: '2.jpg', url: '/photos/2.jpg', description: '第二张' },
      { id: 3, filename: '3.jpg', url: '/photos/3.jpg', description: '第三张' },
    ])

    const { default: GalleryView } = await import('../views/GalleryView.vue')
    const wrapper = mount(GalleryView, {
      global: {
        stubs: {
          TopBar: { template: '<div><slot /></div>' },
          Teleport: true,
        },
      },
    })
    await flushPromises()
    await wrapper.find('.gallery-item').trigger('click')

    await wrapper.find('.lightbox-content img').trigger('touchstart', {
      touches: [{ clientX: 100, clientY: 100 }, { clientX: 120, clientY: 120 }],
    })
    await wrapper.find('.lightbox-content img').trigger('touchend', {
      changedTouches: [{ clientX: 10, clientY: 100 }],
    })
    expect(wrapper.find('.lightbox-counter').text()).toBe('1 / 3')

    await wrapper.find('.lightbox-content img').trigger('touchstart', {
      touches: [{ clientX: 200, clientY: 100 }],
    })
    await wrapper.find('.lightbox-content img').trigger('touchend', {
      changedTouches: [{ clientX: 100, clientY: 300 }],
    })
    expect(wrapper.find('.lightbox-counter').text()).toBe('1 / 3')

    await wrapper.find('.lightbox-content img').trigger('touchstart', {
      touches: [{ clientX: 200, clientY: 100 }],
    })
    await wrapper.find('.lightbox-content img').trigger('touchend', {
      changedTouches: [{ clientX: 100, clientY: 105 }],
    })
    expect(wrapper.find('.lightbox-counter').text()).toBe('2 / 3')
  })
})
