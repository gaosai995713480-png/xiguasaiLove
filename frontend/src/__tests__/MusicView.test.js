import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'

const seekTo = vi.fn()
const loadSongs = vi.fn()
const musicState = reactive({
  songs: [
    { id: 1, netease_id: '1001', title: '测试歌曲', artist: '测试歌手', platform: 'netease' },
  ],
  currentIndex: 0,
  currentSong: { id: 1, netease_id: '1001', title: '测试歌曲', artist: '测试歌手', platform: 'netease' },
  currentPlatformName: '网易云',
  isPlaying: false,
  lyricLines: [],
  currentLyricIndex: -1,
  currentTime: 30,
  duration: 120,
  playError: '',
  loadSongs,
  play: vi.fn(),
  togglePlay: vi.fn(),
  prev: vi.fn(),
  next: vi.fn(),
  seekTo,
  fmtTime: (seconds) => {
    const value = Math.max(0, Math.floor(Number(seconds) || 0))
    return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`
  },
})

vi.mock('../stores/music', () => ({
  useMusicStore: () => musicState,
}))

vi.mock('../stores/context', () => ({
  useContextStore: () => ({
    setPageState: vi.fn(),
  }),
}))

vi.mock('../stores/auth', () => ({
  useAuthStore: () => ({
    isAdmin: true,
  }),
}))

vi.mock('../api/index.js', () => ({
  musicApi: {
    search: vi.fn(),
    add: vi.fn(),
    remove: vi.fn(),
  },
  configApi: {
    getCookies: vi.fn(),
    updateCookies: vi.fn(),
  },
  bgmApi: {
    get: vi.fn(),
    set: vi.fn(),
    clear: vi.fn(),
    upload: vi.fn(),
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}))

async function mountView() {
  const { default: MusicView } = await import('../views/MusicView.vue')
  return mount(MusicView, {
    global: {
      stubs: {
        TopBar: { template: '<div><slot /></div>' },
        GlassModal: { template: '<div><slot /></div>' },
      },
    },
  })
}

describe('MusicView 移动端播放器交互', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    musicState.currentTime = 30
    musicState.duration = 120
  })

  it('进度条暴露 slider 语义并支持键盘 seek', async () => {
    const wrapper = await mountView()
    const slider = wrapper.get('[role="slider"]')

    expect(slider.attributes('aria-label')).toBe('播放进度')
    expect(slider.attributes('aria-valuemin')).toBe('0')
    expect(slider.attributes('aria-valuemax')).toBe('100')
    expect(slider.attributes('aria-valuenow')).toBe('25')
    expect(slider.attributes('aria-valuetext')).toBe('0:30 / 2:00')

    await slider.trigger('keydown', { key: 'ArrowRight' })
    expect(seekTo).toHaveBeenLastCalledWith(30)

    await slider.trigger('keydown', { key: 'Home' })
    expect(seekTo).toHaveBeenLastCalledWith(0)

    await slider.trigger('keydown', { key: 'End' })
    expect(seekTo).toHaveBeenLastCalledWith(100)
  })

  it('歌曲删除和搜索结果添加按钮提供明确可访问名称', async () => {
    const wrapper = await mountView()

    expect(wrapper.get('.song-del').attributes('aria-label')).toBe('删除歌曲 测试歌曲')
    expect(wrapper.get('.setting-btn').attributes('title')).toBe('Cookie 设置')
    expect(wrapper.get('.add-btn').attributes('type')).toBe('button')
  })
})
