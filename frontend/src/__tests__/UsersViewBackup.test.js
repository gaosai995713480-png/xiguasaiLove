import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const mockListUsers = vi.fn()
const mockGetInviteCode = vi.fn()
const mockListKeys = vi.fn()
const mockBackupStatus = vi.fn()
const mockBackupStart = vi.fn()
const mockBackupDownload = vi.fn()
const mockReplace = vi.fn()

vi.mock('../api/index.js', () => ({
  usersApi: {
    list: (...args) => mockListUsers(...args),
    getInviteCode: (...args) => mockGetInviteCode(...args),
    toggle: vi.fn(),
    updateInviteCode: vi.fn(),
  },
  configApi: {
    listKeys: (...args) => mockListKeys(...args),
    saveKey: vi.fn(),
  },
  backupApi: {
    status: (...args) => mockBackupStatus(...args),
    start: (...args) => mockBackupStart(...args),
    download: (...args) => mockBackupDownload(...args),
  },
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => ({
    isAdmin: true,
  }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: mockReplace,
    back: vi.fn(),
  }),
}))

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
      },
    },
  })
}

describe('UsersView 导出回忆', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockListUsers.mockResolvedValue([])
    mockGetInviteCode.mockResolvedValue({ code: 'love2023' })
    mockListKeys.mockResolvedValue({ items: [] })
    mockBackupStatus.mockResolvedValue({ status: 'idle' })
    mockBackupStart.mockResolvedValue({
      status: 'packing',
      progress: { current: 1, total: 4, message: '正在打包照片 1/4' },
    })
    mockBackupDownload.mockResolvedValue({
      blob: new Blob(['zip']),
      filename: 'xiguasai-memory-2026-09-18.zip',
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('管理员可以看到导出入口', async () => {
    const wrapper = await mountView()
    await flushPromises()

    expect(wrapper.get('[data-test="backup-export"]').text()).toContain('导出回忆')
    expect(wrapper.get('[data-test="backup-start"]').text()).toContain('开始导出')
    wrapper.unmount()
  })

  it('点击开始导出后显示打包进度并禁用按钮', async () => {
    const wrapper = await mountView()
    await flushPromises()

    await wrapper.get('[data-test="backup-start"]').trigger('click')
    await flushPromises()

    expect(mockBackupStart).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-test="backup-status"]').text()).toContain('正在打包照片 1/4')
    expect(wrapper.get('[data-test="backup-start"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="backup-start"]').attributes('aria-busy')).toBe('true')
    wrapper.unmount()
  })

  it('打包完成后可以下载备份', async () => {
    vi.useFakeTimers()
    mockBackupStatus
      .mockResolvedValueOnce({ status: 'idle' })
      .mockResolvedValue({
        status: 'done',
        filename: 'xiguasai-memory-2026-09-18.zip',
        stats: { files_failed: 0 },
      })

    const wrapper = await mountView()
    await flushPromises()

    await wrapper.get('[data-test="backup-start"]').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(800)
    await flushPromises()

    expect(wrapper.get('[data-test="backup-status"]').text()).toContain('备份已生成')
    const download = wrapper.get('[data-test="backup-download"]')
    expect(download.element.tagName).toBe('A')
    expect(download.attributes('href')).toBe('/api/backup/export/download')
    expect(download.attributes('download')).toBe('xiguasai-memory-2026-09-18.zip')
    wrapper.unmount()
  })
})
