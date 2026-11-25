<script setup>
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import TopBar from '../components/TopBar.vue'
import { wishApi } from '../api'

const router = useRouter()
const wishes = ref([])
const modalVisible = ref(false)
const modalPos = ref({ left: '0', top: '0' })
const wishInput = ref('')
const wishInputEl = ref(null)
const submitting = ref(false)
const activeWishId = ref(null)
let pendingPos = null

function createBackgroundStars() {
  const sky = document.getElementById('sky')
  if (!sky) return
  for (let i = 0; i < 200; i++) {
    const s = document.createElement('div')
    s.className = 'bg-star'
    s.style.left = Math.random() * 100 + '%'
    s.style.top = Math.random() * 100 + '%'
    s.style.setProperty('--dur', (1.5 + Math.random() * 3) + 's')
    s.style.animationDelay = (Math.random() * 3) + 's'
    sky.appendChild(s)
  }
}

function spawnShootingStar() {
  const el = document.createElement('div')
  el.className = 'shooting-star'
  el.style.left = (Math.random() * 60 + 10) + '%'
  el.style.top = (Math.random() * 40 + 5) + '%'
  document.body.appendChild(el)
  setTimeout(() => el.remove(), 1400)
}

function onSkyClick(e) {
  if (submitting.value) return
  if (e.target.closest('.star') || e.target.closest('.top-bar')) return
  if (modalVisible.value) {
    modalVisible.value = false
    return
  }
  activeWishId.value = null
  pendingPos = {
    x: e.clientX / window.innerWidth,
    y: e.clientY / window.innerHeight,
  }
  const isMobile = window.innerWidth <= 720
  if (isMobile) {
    modalPos.value = { left: '16px', right: '16px', bottom: '20px', top: 'auto' }
  } else {
    modalPos.value = {
      left: Math.min(e.clientX, window.innerWidth - 240) + 'px',
      top: Math.min(e.clientY + 20, window.innerHeight - 100) + 'px',
    }
  }
  modalVisible.value = true
  nextTick(() => wishInputEl.value?.focus())
}

function closeWishModal() {
  if (submitting.value) return
  modalVisible.value = false
}

function toggleWish(id) {
  activeWishId.value = activeWishId.value === id ? null : id
}

function wishTextStyle(wish) {
  const left = `clamp(12px, calc(${wish.x * 100}% - 90px), calc(100% - 192px))`
  if (wish.y > 0.68) {
    return {
      left,
      bottom: `max(calc(var(--tabbar-height) + 12px), calc(${(1 - wish.y) * 100}% + 10px))`,
    }
  }
  return {
    left,
    top: `clamp(calc(var(--topbar-actual-height) + 12px), calc(${wish.y * 100}% + 10px), calc(100% - var(--tabbar-height) - 140px))`,
  }
}

async function submitWish() {
  const content = wishInput.value.trim()
  const position = pendingPos
  if (!content || !position || submitting.value) return
  const colors = ['#ffd700', '#ff6b9d', '#a78bfa', '#60a5fa', '#34d399', '#f472b6']
  const color = colors[Math.floor(Math.random() * colors.length)]
  submitting.value = true
  try {
    const data = await wishApi.create({ content, x: position.x, y: position.y, color })
    if (data.ok) {
      wishes.value.push({ id: data.id, content, x: position.x, y: position.y, color })
      modalVisible.value = false
      wishInput.value = ''
      if (pendingPos === position) pendingPos = null
    }
  } catch { /* ignore */ }
  finally {
    submitting.value = false
  }
}

function onInputKeydown(e) {
  if (e.isComposing) return
  if (e.key === 'Enter' && !submitting.value) submitWish()
  if (e.key === 'Escape' && !submitting.value) closeWishModal()
}

async function loadWishes() {
  try {
    wishes.value = await wishApi.list()
  } catch { /* ignore */ }
}

let shootingStarTimer = null

onMounted(() => {
  loadWishes()
  createBackgroundStars()
  spawnShootingStar()
  shootingStarTimer = setInterval(spawnShootingStar, 5000 + Math.random() * 8000)
})

onUnmounted(() => {
  if (shootingStarTimer) clearInterval(shootingStarTimer)
})
</script>

<template>
  <TopBar title="⭐ 星空许愿" @back="router.push('/')">
    <span class="count">{{ wishes.length }} 颗星</span>
  </TopBar>

  <div class="sky" id="sky" @click="onSkyClick">
    <div
      v-for="w in wishes"
      :key="w.id"
      class="star"
      :class="{
        'is-active': activeWishId === w.id,
        'edge-left': w.x < 0.2,
        'edge-right': w.x > 0.8,
      }"
      :style="{
        left: `clamp(22px, ${w.x * 100}%, calc(100% - 22px))`,
        top: `clamp(calc(var(--topbar-actual-height) + 22px), ${w.y * 100}%, calc(100% - var(--tabbar-height) - 22px))`,
      }"
      role="button"
      tabindex="0"
      :aria-label="`${w.content}，点击${activeWishId === w.id ? '收起' : '查看'}愿望文字`"
      :aria-expanded="activeWishId === w.id"
      @click.stop="toggleWish(w.id)"
      @keydown.enter.prevent="toggleWish(w.id)"
      @keydown.space.prevent="toggleWish(w.id)"
    >
      <div class="star-dot" :style="{ color: w.color, background: w.color }"></div>
      <div class="star-text" :style="wishTextStyle(w)" @click.stop>{{ w.content }}</div>
    </div>
  </div>

  <div class="hint">✨ 点击星空，许一个心愿</div>

  <div
    class="wish-modal"
    :class="{ 'is-visible': modalVisible }"
    :style="modalPos"
    role="dialog"
    aria-modal="true"
    aria-label="写下心愿"
    :aria-hidden="!modalVisible"
    :inert="!modalVisible"
    @click.stop
  >
    <button
      class="wish-close"
      type="button"
      aria-label="关闭许愿框"
      :disabled="submitting"
      @click.stop="closeWishModal"
    >✕</button>
    <div class="wish-modal-row">
      <input
        ref="wishInputEl"
        v-model="wishInput"
        type="text"
        aria-label="写下你的心愿"
        placeholder="写下你的心愿..."
        maxlength="50"
        :disabled="submitting"
        @keydown="onInputKeydown"
      />
      <button class="wish-submit" :disabled="submitting" @click="submitWish">
        {{ submitting ? '正在许愿...' : '许愿 ⭐' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.count { margin-left: auto; font-size: 13px; color: rgba(255, 255, 255, 0.5); }

/* Override body for this page */
:deep(body) { overflow: hidden; }

.sky { position: fixed; inset: 0; z-index: 1; cursor: crosshair;
  background: radial-gradient(ellipse at 20% 50%, #0d1b2a 0%, #0a0e1a 50%, #020408 100%);
}

.hint {
  position: fixed; bottom: calc(24px + var(--tabbar-height)); left: 50%; transform: translateX(-50%);
  font-size: 13px; color: rgba(255, 255, 255, 0.35); z-index: 5;
  pointer-events: none; animation: pulse 3s ease-in-out infinite;
}

.star {
  position: absolute; z-index: 2; width: 44px; height: 44px;
  margin-left: -22px; margin-top: -22px;
  display: flex; align-items: center; justify-content: center;
  text-align: center; cursor: pointer; border-radius: 50%;
  touch-action: manipulation;
}

.star-dot {
  width: 6px; height: 6px; border-radius: 50%;
  animation: twinkle 2s ease-in-out infinite alternate;
  box-shadow: 0 0 8px 2px currentColor; pointer-events: none;
  transition: transform 0.2s;
}

.star-text {
  position: fixed;
  z-index: 4;
  width: min(180px, calc(100vw - 24px));
  max-height: min(160px, calc(100dvh - 140px));
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(4, 8, 18, 0.82);
  font-size: 12px; line-height: 1.55; color: rgba(255, 255, 255, 0.88);
  white-space: normal; overflow-wrap: anywhere; word-break: break-word;
  text-align: center;
  opacity: 0; pointer-events: none; transition: opacity 0.3s;
  text-shadow: 0 0 8px rgba(255, 255, 255, 0.3);
}

.star.edge-left .star-text { text-align: left; }
.star.edge-right .star-text { text-align: right; }

.star.is-active .star-text,
.star:focus-visible .star-text {
  opacity: 1;
  pointer-events: auto;
}

.star.is-active .star-dot {
  transform: scale(1.55);
}

.star:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 4px;
}

@media (hover: hover) {
  .star:hover .star-text { opacity: 1; }
}

:deep(.bg-star) {
  position: absolute; width: 2px; height: 2px; border-radius: 50%;
  background: rgba(255, 255, 255, 0.5);
  animation: twinkle-bg var(--dur) ease-in-out infinite alternate;
}

@keyframes twinkle-bg { 0% { opacity: 0.2; } 100% { opacity: 0.8; } }

:deep(.shooting-star) {
  position: fixed; width: 80px; height: 1px; z-index: 0;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.8), transparent);
  animation: shoot 1.2s linear forwards; transform-origin: left center;
}

@keyframes shoot {
  0% { transform: translateX(0) translateY(0) rotate(-20deg); opacity: 1; }
  100% { transform: translateX(300px) translateY(120px) rotate(-20deg); opacity: 0; }
}

.wish-modal {
  position: fixed; z-index: 20; padding: 52px 16px 16px; border-radius: 16px;
  background: rgba(10, 14, 26, 0.9); backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 215, 0, 0.2);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  opacity: 0; pointer-events: none; transition: all 0.3s; transform: scale(0.9);
}

.wish-modal.is-visible { opacity: 1; pointer-events: auto; transform: scale(1); }

.wish-modal-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.wish-close {
  position: absolute; top: 6px; right: 6px;
  width: 44px; height: 44px; border: none; border-radius: 50%;
  background: rgba(255, 255, 255, 0.08); color: rgba(255, 255, 255, 0.8);
  font-size: 18px; cursor: pointer;
}

.wish-close:disabled { opacity: 0.45; cursor: not-allowed; }

.wish-modal input {
  width: 200px; padding: 8px 12px; border-radius: 8px;
  border: 1px solid rgba(255, 215, 0, 0.3); background: rgba(255, 255, 255, 0.05);
  color: #ffd700; font-size: 14px; outline: none;
  min-height: 44px;
}

.wish-modal input::placeholder { color: rgba(255, 215, 0, 0.4); }
.wish-modal input:focus { border-color: #ffd700; }

.wish-submit {
  width: 100%; padding: 8px; border-radius: 8px; border: none;
  background: linear-gradient(135deg, #ffd700, #ffaa00);
  color: #1a0e2e; font-weight: 700; font-size: 13px; cursor: pointer;
}

@media (max-width: 720px) {
  .wish-modal {
    left: 16px !important;
    right: 16px !important;
    top: auto !important;
    bottom: calc(12px + var(--tabbar-height)) !important;
    padding: 52px 16px 16px;
  }

  .wish-modal-row {
    flex-direction: row;
    align-items: center;
  }

  .wish-modal input {
    width: auto;
    flex: 1;
    min-width: 0;
  }

  .wish-submit {
    width: auto;
    flex: 0 0 auto;
    padding: 8px 16px;
    white-space: nowrap;
    min-height: var(--touch-min);
  }

  .hint {
    bottom: calc(80px + var(--tabbar-height));
  }
}
</style>
