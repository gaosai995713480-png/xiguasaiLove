<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TopBar from '../components/TopBar.vue'
import { dayApi } from '../api'
import { useContextStore } from '../stores/context'
import { formatDayTitle, isIsoDate, photoDay, shiftIsoDate } from '../utils/dayDate'

const LEVEL_LABELS = ['低落', '一般', '还行', '开心', '超开心']

const route = useRoute()
const router = useRouter()
const contextStore = useContextStore()

const day = computed(() => String(route.params.date || ''))
const loading = ref(false)
const errorMsg = ref('')
const data = ref(null)
const preview = ref(null)

const valid = computed(() => isIsoDate(day.value))
const title = computed(() => (valid.value ? formatDayTitle(day.value) : '这一天'))
const mood = computed(() => data.value?.mood || null)
const timeline = computed(() => data.value?.timeline || [])
const places = computed(() => data.value?.places || [])
const photos = computed(() => data.value?.photos || [])
const galleryUnlocked = computed(() => Boolean(data.value?.gallery_unlocked))
const empty = computed(() => {
  if (!data.value || !galleryUnlocked.value) return false
  return !mood.value && !timeline.value.length && !places.value.length && !photos.value.length
})

async function load() {
  preview.value = null
  data.value = null
  errorMsg.value = ''
  if (!valid.value) {
    errorMsg.value = '日期不正确'
    contextStore.setPageState('日期不正确')
    return
  }
  loading.value = true
  try {
    data.value = await dayApi.get(day.value)
    contextStore.setPageState(`正在查看 ${title.value}`)
  } catch (error) {
    errorMsg.value = error?.message || '加载失败'
    contextStore.setPageState(errorMsg.value)
  } finally {
    loading.value = false
  }
}

function go(offset) {
  if (!valid.value) return
  router.push(`/day/${shiftIsoDate(day.value, offset)}`)
}

function jump(event) {
  const next = event.target.value
  if (isIsoDate(next)) router.push(`/day/${next}`)
}

function placeCover(place) {
  if (place.photos?.length) return place.photos[0]
  return place.photo_url || ''
}

function moodLevelLabel(level) {
  return LEVEL_LABELS[(Number(level) || 0) - 1] || ''
}

watch(day, load, { immediate: true })
</script>

<template>
  <TopBar :title="valid ? `📅 ${day}` : '📅 这一天'" />

  <div class="page">
    <header class="hero">
      <p class="eyebrow">这一天</p>
      <h2>{{ title }}</h2>
      <p class="hero-hint">把当天已经留下的心情、故事、足迹和照片放在一起看。</p>
      <div class="day-nav">
        <button class="nav-btn" :disabled="!valid" @click="go(-1)">‹ 前一天</button>
        <input class="nav-date" type="date" :value="valid ? day : ''" @change="jump" />
        <button class="nav-btn" :disabled="!valid" @click="go(1)">后一天 ›</button>
      </div>
    </header>

    <p v-if="loading" class="status">正在把这一天找回来…</p>
    <p v-else-if="errorMsg" class="status is-error">{{ errorMsg }}</p>

    <template v-else-if="data">
      <section class="section">
        <div class="section-head">
          <h3>心情</h3>
          <button class="text-link" @click="router.push('/mood')">去心情日历</button>
        </div>
        <div v-if="mood" class="mood-card">
          <span class="mood-emoji">{{ mood.emoji }}</span>
          <div>
            <div class="mood-level">{{ moodLevelLabel(mood.level) }}</div>
            <p class="mood-note">{{ mood.note || '这天没有写下备注' }}</p>
          </div>
        </div>
        <p v-else class="empty-line">这天还没有打卡。<button class="text-link" @click="router.push('/mood')">去记下心情</button></p>
      </section>

      <section class="section">
        <div class="section-head">
          <h3>故事</h3>
          <button class="text-link" @click="router.push('/timeline')">去时间轴</button>
        </div>
        <div v-if="timeline.length" class="story-list">
          <article v-for="item in timeline" :key="item.id" class="story-card">
            <div class="story-icon">{{ item.icon || '💕' }}</div>
            <div>
              <h4>{{ item.title }}</h4>
              <p v-if="item.content">{{ item.content }}</p>
              <img v-if="item.photo_url" :src="item.photo_url" alt="" />
            </div>
          </article>
        </div>
        <p v-else class="empty-line">这天还没有写进时间轴。<button class="text-link" @click="router.push('/timeline')">去记录</button></p>
      </section>

      <section class="section">
        <div class="section-head">
          <h3>足迹</h3>
          <button class="text-link" @click="router.push('/map')">去恋爱地图</button>
        </div>
        <div v-if="places.length" class="place-list">
          <article v-for="place in places" :key="place.id" class="place-card" @click="router.push('/map')">
            <img v-if="placeCover(place)" :src="placeCover(place)" alt="" />
            <div>
              <h4>{{ place.title }}</h4>
              <p>{{ place.note || '没有备注' }}</p>
            </div>
          </article>
        </div>
        <p v-else class="empty-line">这天还没有落到地图上。<button class="text-link" @click="router.push('/map')">去标记</button></p>
      </section>

      <section class="section">
        <div class="section-head">
          <h3>照片</h3>
          <button class="text-link" @click="router.push('/gallery')">去心动画廊</button>
        </div>
        <p v-if="!galleryUnlocked" class="empty-line">
          画廊还没解锁，照片先藏着。
          <button class="text-link" @click="router.push('/gallery')">去解锁</button>
        </p>
        <div v-else-if="photos.length" class="photo-grid">
          <button
            v-for="photo in photos"
            :key="photo.id || photo.filename"
            class="photo-item"
            type="button"
            @click="preview = photo"
          >
            <img :src="photo.thumbnail_url || photo.url" :alt="photo.description || '照片'" />
            <span v-if="photo.description">{{ photo.description }}</span>
          </button>
        </div>
        <p v-else class="empty-line">这天还没有进入相册的照片。<button class="text-link" @click="router.push('/gallery')">去相册</button></p>
      </section>

      <p v-if="empty" class="empty-all">这一天还是空白的。可以从心情、时间轴、地图或相册留下第一条痕迹。</p>
    </template>
  </div>

  <Teleport to="body">
    <div v-if="preview" class="lightbox" @click.self="preview = null">
      <button class="lightbox-close" type="button" @click="preview = null">✕</button>
      <img :src="preview.url" :alt="preview.description || '大图'" />
      <p v-if="preview.description || photoDay(preview.created_at)">
        {{ preview.description || photoDay(preview.created_at) }}
      </p>
    </div>
  </Teleport>
</template>

<style scoped>
.day-nav {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.nav-btn,
.nav-date {
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  border-radius: 10px;
  font-size: 13px;
}

.nav-btn {
  padding: 6px 10px;
  cursor: pointer;
}

.nav-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.nav-date {
  padding: 6px 8px;
  color-scheme: dark;
}

.page {
  max-width: 820px;
  margin: 0 auto;
  padding: var(--page-pad-top) var(--page-pad-x) var(--page-pad-bottom);
}

.hero {
  margin-bottom: 28px;
}

.eyebrow {
  font-size: 12px;
  letter-spacing: 0.2em;
  color: var(--accent);
  margin-bottom: 6px;
}

.hero h2 {
  font-size: clamp(24px, 4vw, 34px);
  margin-bottom: 8px;
}

.hero-hint,
.status,
.empty-line,
.empty-all {
  color: var(--text-secondary);
  line-height: 1.7;
}

.status {
  padding: 24px 0;
}

.status.is-error {
  color: #f8a5a5;
}

.section {
  margin-bottom: 28px;
  padding: 20px;
  border-radius: 20px;
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  backdrop-filter: blur(20px);
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.section-head h3 {
  font-size: 16px;
}

.text-link {
  border: none;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font-size: 13px;
  padding: 0;
}

.mood-card,
.story-card,
.place-card {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.mood-emoji,
.story-icon {
  font-size: 32px;
  line-height: 1;
}

.mood-level,
.story-card h4,
.place-card h4 {
  font-weight: 700;
  margin-bottom: 4px;
}

.mood-note,
.story-card p,
.place-card p,
.empty-line {
  font-size: 14px;
}

.story-list,
.place-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.story-card img,
.place-card img {
  width: 88px;
  height: 88px;
  object-fit: cover;
  border-radius: 12px;
  flex-shrink: 0;
}

.story-card img {
  width: 100%;
  height: auto;
  max-height: 180px;
  margin-top: 10px;
}

.place-card {
  cursor: pointer;
}

.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}

.photo-item {
  border: none;
  padding: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.photo-item img {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  border-radius: 14px;
}

.photo-item span {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.empty-all {
  text-align: center;
  padding: 8px 8px 0;
}

.lightbox {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: rgba(0, 0, 0, 0.78);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.lightbox img {
  max-width: min(920px, 92vw);
  max-height: 78vh;
  border-radius: 16px;
}

.lightbox p {
  margin-top: 12px;
  color: #fff;
}

.lightbox-close {
  position: absolute;
  top: calc(12px + var(--safe-top));
  right: calc(12px + var(--safe-right));
  width: var(--touch-min);
  height: var(--touch-min);
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
  cursor: pointer;
}

@media (max-width: 720px) {
  .day-nav {
    gap: 4px;
  }

  .nav-btn {
    padding: 8px 10px;
    font-size: 12px;
    min-height: var(--touch-min);
  }

  .section {
    padding: 16px;
  }

  .place-card img {
    width: 72px;
    height: 72px;
  }
}
</style>
