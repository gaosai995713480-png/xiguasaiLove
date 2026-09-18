/**
 * music store 单元测试
 * TDD: 先写测试 → 确认失败 → 写实现 → 确认通过
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useMusicStore } from '../stores/music'
import { bgmApi, musicApi } from '../api'

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    bgmApi: {
      ...actual.bgmApi,
      get: vi.fn(),
    },
    musicApi: {
      ...actual.musicApi,
      url: vi.fn(),
      lyric: vi.fn().mockResolvedValue({ lyric: '' }),
    },
  }
})

describe('useMusicStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(bgmApi.get).mockReset()
    vi.mocked(musicApi.url).mockReset()
    vi.mocked(musicApi.lyric).mockReset()
    vi.mocked(musicApi.lyric).mockResolvedValue({ lyric: '' })
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('reset', () => {
    it('重置所有播放状态', () => {
      const store = useMusicStore()
      // 模拟播放中状态
      store.isPlaying = true
      store.currentIndex = 2
      store.currentTime = 120
      store.duration = 300
      store.playError = '测试错误'

      store.reset()

      expect(store.isPlaying).toBe(false)
      expect(store.currentIndex).toBe(-1)
      expect(store.currentTime).toBe(0)
      expect(store.duration).toBe(0)
      expect(store.lyricLines).toEqual([])
      expect(store.currentLyricIndex).toBe(-1)
      expect(store.playError).toBe('')
    })
  })

  describe('startBgm', () => {
    it('配置关闭时不播放', async () => {
      vi.mocked(bgmApi.get).mockResolvedValue({ enabled: false })
      const store = useMusicStore()

      await store.startBgm()

      expect(store.bgm).toBe(null)
      expect(store.isPlaying).toBe(false)
      expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
    })

    it('有可用音源时循环播放', async () => {
      vi.mocked(bgmApi.get).mockResolvedValue({
        enabled: true,
        source: 'local',
        title: '首页曲',
        url: '/api/music/bgm/file/song.mp3',
      })
      const store = useMusicStore()

      await store.startBgm()

      expect(store.bgm.title).toBe('首页曲')
      expect(store.isPlaying).toBe(true)
      expect(store.bgmBlocked).toBe(false)
      expect(HTMLMediaElement.prototype.play).toHaveBeenCalled()
    })

    it('浏览器拦截自动播放时给出点击提示', async () => {
      vi.mocked(bgmApi.get).mockResolvedValue({
        enabled: true,
        source: 'local',
        title: '首页曲',
        url: '/api/music/bgm/file/song.mp3',
      })
      vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(
        Object.assign(new Error('denied'), { name: 'NotAllowedError' }),
      )
      const store = useMusicStore()

      await store.startBgm()

      expect(store.isPlaying).toBe(false)
      expect(store.bgmBlocked).toBe(true)
      expect(store.playError).toBe('')
    })

    it('音频源 404 时提示加载失败而不是点一下播放', async () => {
      vi.mocked(bgmApi.get).mockResolvedValue({
        enabled: true,
        source: 'local',
        title: '首页曲',
        url: '/api/music/bgm/file/missing.mp3',
      })
      vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(
        Object.assign(new Error('failed'), { name: 'NotSupportedError' }),
      )
      const store = useMusicStore()

      await store.startBgm()

      expect(store.isPlaying).toBe(false)
      expect(store.bgmBlocked).toBe(false)
      expect(store.playError).toContain('音频加载失败')
    })

    it('把 http 音源升到 https，避免 Chrome 混合内容拦截', async () => {
      vi.mocked(bgmApi.get).mockResolvedValue({
        enabled: true,
        source: 'meting',
        song_id: '1',
        title: '晴天',
        url: 'http://m701.music.126.net/song.mp3',
      })
      const store = useMusicStore()

      await store.startBgm()

      expect(store.audio.src).toBe('https://m701.music.126.net/song.mp3')
      expect(store.isPlaying).toBe(true)
    })
  })

  describe('play', () => {
    it('网易云 http 直链升到 https 再播放', async () => {
      vi.mocked(musicApi.url).mockResolvedValue({
        url: 'http://m801.music.126.net/song.mp3',
      })
      const store = useMusicStore()
      store.songs = [{ id: 1, netease_id: '2067368745', platform: 'netease', title: '歌', artist: '唱' }]

      await store.play(0)

      expect(store.audio.src).toBe('https://m801.music.126.net/song.mp3')
      expect(store.isPlaying).toBe(true)
      expect(store.playError).toBe('')
    })

    it('同源代理地址原样播放', async () => {
      vi.mocked(musicApi.url).mockResolvedValue({
        url: '/api/music/stream?id=1&platform=netease',
      })
      const store = useMusicStore()
      store.songs = [{ id: 1, netease_id: '1', platform: 'netease', title: '歌', artist: '唱' }]

      await store.play(0)

      expect(store.audio.src).toContain('/api/music/stream?id=1&platform=netease')
      expect(store.isPlaying).toBe(true)
    })

    it('播放失败后再点播放会重新拉直链', async () => {
      vi.mocked(musicApi.url)
        .mockResolvedValueOnce({ url: 'https://bad.example/x.mp3' })
        .mockResolvedValueOnce({ url: '/api/music/stream?id=1&platform=netease' })
      const playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play')
      playSpy.mockRejectedValueOnce(
        Object.assign(new Error('no source'), { name: 'NotSupportedError' }),
      )
      playSpy.mockResolvedValueOnce()
      const store = useMusicStore()
      store.songs = [{ id: 1, netease_id: '1', platform: 'netease', title: '歌', artist: '唱' }]

      await store.play(0)
      expect(store.playError).toBe('音频加载失败（NotSupportedError）')

      await store.togglePlay()
      expect(musicApi.url).toHaveBeenCalledTimes(2)
      expect(store.isPlaying).toBe(true)
    })

    it('音源不被 Chrome 支持时提示加载失败', async () => {
      vi.mocked(musicApi.url).mockResolvedValue({
        url: 'https://m801.music.126.net/song.mp3',
      })
      vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(
        Object.assign(new Error('no source'), { name: 'NotSupportedError' }),
      )
      const store = useMusicStore()
      store.songs = [{ id: 1, netease_id: '1', platform: 'netease', title: '歌', artist: '唱' }]

      await store.play(0)

      expect(store.isPlaying).toBe(false)
      expect(store.playError).toBe('音频加载失败（NotSupportedError）')
    })
  })
})
