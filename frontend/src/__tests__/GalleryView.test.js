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
})
