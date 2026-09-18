<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const groups = [
  {
    key: 'memories',
    icon: '💕',
    label: '甜蜜回忆',
    items: [
      { to: '/gallery', icon: '📸', label: '心动画廊', desc: '我们的精彩瞬间' },
      { to: '/timeline', icon: '📖', label: '时间轴', desc: '一路走来的故事' },
      { to: '/map', icon: '🗺️', label: '恋爱地图', desc: '我们去过的地方' },
    ],
  },
  {
    key: 'romance',
    icon: '💌',
    label: '浪漫表达',
    items: [
      { to: '/letter', icon: '💌', label: '表白信', desc: '写给你的情书' },
      { to: '/mood', icon: '😊', label: '心情日历', desc: '记录每天的心情' },
      { to: '/wishes', icon: '⭐', label: '星空许愿', desc: '许下我们的愿望' },
    ],
  },
  {
    key: 'music',
    icon: '🎵',
    label: '音乐空间',
    items: [
      { to: '/music', icon: '🎵', label: '音乐时光', desc: '属于我们的歌单' },
      { to: '/jukebox', icon: '🎤', label: '点歌台', desc: '朋友们的歌曲推荐' },
    ],
  },
  {
    key: 'tools',
    icon: '🔧',
    label: '生活工具',
    items: [
      { to: '/express', icon: '📦', label: '快递查询', desc: '查看物流轨迹' },
      { to: '/cookbook', icon: '🍳', label: '我们的小厨房', desc: '一起决定今天吃什么' },
      { to: '/tripstar', icon: '🌌', label: '旅行星辰', desc: 'AI 生成旅行计划' },
    ],
  },
]

const tabs = [
  { key: 'home', to: '/', icon: '🏠', label: '首页' },
  { key: 'memories', icon: '💕', label: '回忆', panel: 'memories' },
  { key: 'mood', to: '/mood', icon: '😊', label: '心情' },
  { key: 'music', to: '/music', icon: '🎵', label: '音乐' },
  { key: 'more', icon: '✨', label: '更多', panel: 'more' },
]

const moreItems = computed(() => {
  const items = [
    ...groups.find((g) => g.key === 'romance').items.filter((item) => item.to !== '/mood'),
    ...groups.find((g) => g.key === 'music').items.filter((item) => item.to !== '/music'),
    ...groups.find((g) => g.key === 'tools').items,
  ]
  if (authStore.isAdmin) {
    items.push({ to: '/users', icon: '👥', label: '用户管理', desc: '账号、邀请码与回忆备份' })
  }
  return items
})

const activePanel = ref(null)

const panelData = computed(() => {
  if (!activePanel.value) return null
  if (activePanel.value === 'more') {
    return { icon: '✨', title: '更多', items: moreItems.value }
  }
  const group = groups.find((g) => g.key === activePanel.value)
  if (!group) return null
  return { icon: group.icon, title: group.label, items: group.items }
})

const isHome = computed(() => route.path === '/')

const activeTab = computed(() => {
  const path = route.path
  if (path === '/') return 'home'
  if (
    path.startsWith('/gallery')
    || path.startsWith('/timeline')
    || path.startsWith('/map')
    || path.startsWith('/day')
  ) return 'memories'
  if (path.startsWith('/mood')) return 'mood'
  if (path.startsWith('/music')) return 'music'
  return 'more'
})

function toggleGroup(group) {
  activePanel.value = activePanel.value === group.key ? null : group.key
}

function togglePanel(key) {
  activePanel.value = activePanel.value === key ? null : key
}

function onTabClick(tab) {
  if (tab.panel) {
    togglePanel(tab.panel)
    return
  }
  activePanel.value = null
  if (route.path !== tab.to) router.push(tab.to)
}

function navigateTo(to) {
  activePanel.value = null
  router.push(to)
}

function closePanel() {
  activePanel.value = null
}
</script>

<template>
  <!-- 桌面：仅首页左侧分组栏 -->
  <aside class="nav-sidebar" :class="{ 'is-home': isHome }" aria-label="功能导航">
    <button
      v-for="g in groups"
      :key="g.key"
      class="sidebar-btn"
      :class="{ 'is-active': activePanel === g.key }"
      :title="g.label"
      type="button"
      @click.stop="toggleGroup(g)"
    >
      <span class="btn-icon">{{ g.icon }}</span>
      <span class="btn-label">{{ g.label }}</span>
    </button>
  </aside>

  <!-- 手机：底部一级导航 -->
  <nav class="nav-tabbar" aria-label="底部导航">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      class="tab-btn"
      :class="{ 'is-active': activeTab === tab.key }"
      :data-tab="tab.key"
      type="button"
      :aria-current="activeTab === tab.key ? 'page' : undefined"
      @click="onTabClick(tab)"
    >
      <span class="tab-icon">{{ tab.icon }}</span>
      <span class="tab-label">{{ tab.label }}</span>
    </button>
  </nav>

  <Teleport to="body">
    <Transition name="fade">
      <div v-if="panelData" class="panel-overlay" @click="closePanel">
        <div class="panel-card" @click.stop>
          <div class="panel-header">
            <span class="panel-icon">{{ panelData.icon }}</span>
            <span class="panel-title">{{ panelData.title }}</span>
            <button class="panel-close" type="button" aria-label="关闭" @click="closePanel">✕</button>
          </div>
          <div class="panel-grid">
            <button
              v-for="item in panelData.items"
              :key="item.to"
              class="panel-item"
              type="button"
              @click="navigateTo(item.to)"
            >
              <span class="pi-icon">{{ item.icon }}</span>
              <span class="pi-label">{{ item.label }}</span>
              <span class="pi-desc">{{ item.desc }}</span>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* ===== 左侧图标栏（桌面） ===== */
.nav-sidebar {
  display: none;
  position: fixed;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  z-index: 8;
  flex-direction: column;
  gap: 4px;
  background: var(--glass-bg);
  backdrop-filter: blur(24px);
  border: 1px solid var(--glass-border);
  border-left: none;
  border-radius: 0 16px 16px 0;
  padding: 10px 6px;
  box-shadow: 4px 0 20px rgba(0, 0, 0, 0.15);
}

.nav-sidebar.is-home {
  display: flex;
}

.sidebar-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 10px 8px;
  border: none;
  border-radius: 12px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
  min-width: 52px;
}

@media (hover: hover) {
  .sidebar-btn:hover {
    background: rgba(255, 255, 255, 0.1);
    color: var(--text-primary);
    transform: scale(1.05);
  }
}

.sidebar-btn.is-active {
  background: rgba(255, 107, 157, 0.15);
  color: var(--primary);
}

.btn-icon { font-size: 22px; line-height: 1; }
.btn-label { font-size: 10px; font-weight: 600; white-space: nowrap; }

/* ===== 底部 Tab（手机默认隐藏，窄屏显示） ===== */
.nav-tabbar {
  display: none;
}

/* ===== 弹出面板 ===== */
.panel-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(6px);
}

.panel-card {
  background: var(--glass-bg);
  backdrop-filter: blur(30px);
  border: 1px solid var(--glass-border);
  border-radius: 24px;
  padding: 28px 32px 24px;
  min-width: 320px;
  max-width: 460px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
  animation: card-in 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes card-in {
  from { opacity: 0; transform: scale(0.9) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.panel-icon { font-size: 28px; }
.panel-title { flex: 1; font-size: 20px; font-weight: 700; }

.panel-close {
  width: 32px; height: 32px; border-radius: 50%;
  border: none; background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary); font-size: 14px;
  cursor: pointer; transition: all 0.2s;
  display: flex; align-items: center; justify-content: center;
}

@media (hover: hover) {
  .panel-close:hover { background: rgba(255, 80, 80, 0.2); color: #fff; }
}

.panel-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.panel-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
}

@media (hover: hover) {
  .panel-item:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: rgba(255, 255, 255, 0.15);
    transform: translateX(4px);
  }
}

.pi-icon { font-size: 28px; flex-shrink: 0; }
.pi-label { font-size: 15px; font-weight: 700; }
.pi-desc {
  font-size: 12px; color: var(--text-secondary);
  margin-left: auto; flex-shrink: 0;
}

.fade-enter-active { transition: opacity 0.2s; }
.fade-leave-active { transition: opacity 0.15s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (max-width: 720px) {
  .nav-sidebar {
    display: none !important;
  }

  .nav-tabbar {
    display: flex;
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 25;
    align-items: stretch;
    justify-content: space-around;
    min-height: var(--tabbar-height);
    padding: 4px 4px var(--safe-bottom);
    padding-left: max(4px, var(--safe-left));
    padding-right: max(4px, var(--safe-right));
    background: rgba(18, 12, 28, 0.88);
    backdrop-filter: blur(24px);
    border-top: 1px solid var(--glass-border);
  }

  .tab-btn {
    flex: 1;
    min-width: 0;
    min-height: var(--touch-min);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    padding: 6px 4px;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
  }

  .tab-btn.is-active {
    color: var(--primary);
  }

  .tab-icon { font-size: 20px; line-height: 1; }
  .tab-label {
    font-size: 11px;
    font-weight: 600;
    white-space: nowrap;
  }

  .panel-overlay {
    align-items: flex-end;
  }

  .panel-card {
    width: 100%;
    max-width: none;
    min-width: 0;
    margin: 0;
    border-radius: 20px 20px 0 0;
    padding: 18px 16px calc(16px + var(--safe-bottom));
    max-height: min(80dvh, calc(100dvh - var(--safe-top) - 12px));
    overflow-y: auto;
    animation: sheet-in 0.28s cubic-bezier(0.16, 1, 0.3, 1);
  }

  @keyframes sheet-in {
    from { opacity: 0; transform: translateY(24px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .panel-close {
    width: var(--touch-min);
    height: var(--touch-min);
  }

  .panel-item { padding: 12px 14px; min-height: var(--touch-min); }
  .pi-desc { display: none; }
}
</style>
