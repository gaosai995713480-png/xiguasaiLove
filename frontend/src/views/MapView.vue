<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import TopBar from '../components/TopBar.vue'
import GlassModal from '../components/GlassModal.vue'
import { mapApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { todayInShanghai } from '../utils/dayDate'
import { loadAmapFromConfig } from '../utils/amap'
import {
  createMapPhotoDrafts,
  createPendingPhotoDrafts,
  resolveMapPhotoDraftUrls,
  revokeLocalPhotoDrafts,
} from './mapPhotoDraft'
const authStore = useAuthStore()

const router = useRouter()
const markers = ref([])
const selectedMarker = ref(null)
const showDetail = ref(false)
const showForm = ref(false)
const form = ref(createEmptyForm())
const uploading = ref(false)
const carouselIndex = ref(0)
const mapError = ref('')
const mapReady = ref(false)
const mapLoading = ref(false)
let editingId = null
let map = null
let mapMarkers = []
let polyline = null
let viewActive = false

function createEmptyForm() {
  return {
    name: '',
    note: '',
    date: todayInShanghai(),
    photos: [],
    lat: 0,
    lng: 0,
  }
}

// 地图初始化（需要等高德 SDK 加载完毕）
function initMap() {
  if (!window.AMap?.Map) throw new Error('高德地图 SDK 未就绪')
  map = new AMap.Map('map-container', {
    zoom: 5,
    center: [114.3, 30.6],
    mapStyle: 'amap://styles/dark',
    viewMode: '2D',
  })
  map.on('click', onMapClick)
  mapReady.value = true
  loadMarkers()
}

function onMapClick(e) {
  if (showForm.value || showDetail.value) return
  const lnglat = e.lnglat
  const geocoder = new AMap.Geocoder()
  geocoder.getAddress([lnglat.lng, lnglat.lat], (status, result) => {
    let name = ''
    if (status === 'complete' && result.regeocode) {
      const addr = result.regeocode.formattedAddress || ''
      name = addr.replace(/^中国/, '').replace(/^\w+省/, '').replace(/^\w+市/, '')
    }
    openForm(name, lnglat.lat, lnglat.lng)
  })
}

function openForm(name, lat, lng, data) {
  revokeLocalPhotoDrafts(form.value.photos)
  editingId = data ? data.id : null
  form.value = {
    name: data ? data.title : (name || ''),
    note: data ? (data.note || '') : '',
    date: data ? (data.visit_date || '') : todayInShanghai(),
    photos: createMapPhotoDrafts(data),
    lat, lng,
  }
  showForm.value = true
}

function closeForm() {
  revokeLocalPhotoDrafts(form.value.photos)
  form.value = createEmptyForm()
  editingId = null
  showForm.value = false
}

function handleFormVisibleChange(value) {
  if (value) {
    showForm.value = true
    return
  }
  if (uploading.value) return
  closeForm()
}

function handleFileSelect(e) {
  if (uploading.value) return
  const files = e.target.files
  if (!files || !files.length) return
  const drafts = createPendingPhotoDrafts(files)
  form.value.photos.push(...drafts)
  e.target.value = ''
}

function removePhoto(index) {
  if (uploading.value) return
  const [removed] = form.value.photos.splice(index, 1)
  revokeLocalPhotoDrafts(removed ? [removed] : [])
}

async function saveForm() {
  if (!form.value.name) { alert('请输入地点名称'); return }
  let uploadedNames = []
  uploading.value = true
  try {
    const resolved = await resolveMapPhotoDraftUrls(
      form.value.photos,
      mapApi.upload,
      mapApi.cleanupUploads,
    )
    uploadedNames = resolved.uploadedNames
    const body = {
      title: form.value.name,
      note: form.value.note,
      visit_date: form.value.date,
      photos: resolved.urls,
      lat: form.value.lat,
      lng: form.value.lng,
    }
    if (editingId) {
      body.id = editingId
      await mapApi.update(body)
    } else {
      await mapApi.create(body)
    }
    showDetail.value = false
    closeForm()
    loadMarkers()
  } catch {
    if (uploadedNames.length) {
      try {
        await mapApi.cleanupUploads(uploadedNames)
      } catch {
        // 清理失败时保留原始保存错误提示
      }
    }
    alert('保存失败')
  } finally {
    uploading.value = false
  }
}

function openDetail(data) {
  selectedMarker.value = data
  carouselIndex.value = 0
  showDetail.value = true
}

function editDetail() {
  if (!selectedMarker.value) return
  const d = selectedMarker.value
  showDetail.value = false
  openForm(d.title, d.lat, d.lng, d)
}

async function deleteDetail() {
  if (!selectedMarker.value || !confirm(`确定要删除「${selectedMarker.value.title}」吗？`)) return
  try {
    await mapApi.remove(selectedMarker.value.id)
    showDetail.value = false
    loadMarkers()
  } catch { alert('删除失败') }
}

function clearMapMarkers() {
  if (!map) return
  mapMarkers.forEach(m => map.remove(m))
  mapMarkers = []
  if (polyline) { map.remove(polyline); polyline = null }
}

function destroyMapInstance() {
  clearMapMarkers()
  mapMarkers = []
  polyline = null
  if (map) {
    map.off('click', onMapClick)
    if (typeof map.destroy === 'function') map.destroy()
    map = null
  }
  mapReady.value = false
}

function renderMapMarkers(data) {
  clearMapMarkers()
  data.forEach(item => {
    const content = document.createElement('div')
    content.className = 'love-marker'
    content.textContent = '💕'
    const marker = new AMap.Marker({
      position: [item.lng, item.lat],
      content,
      offset: new AMap.Pixel(-22, -22),
    })
    marker.on('click', () => openDetail(item))
    map.add(marker)
    mapMarkers.push(marker)
  })
  // 路线
  const sorted = [...data].filter(d => d.visit_date).sort((a, b) => a.visit_date.localeCompare(b.visit_date))
  if (sorted.length >= 2) {
    const path = sorted.map(d => [d.lng, d.lat])
    polyline = new AMap.Polyline({
      path,
      strokeColor: 'rgba(255,107,157,0.6)',
      strokeWeight: 2,
      strokeStyle: 'dashed',
      lineJoin: 'round',
    })
    map.add(polyline)
  }
  if (data.length > 0) map.setFitView(mapMarkers, false, [80, 80, 80, 80])
}

async function loadMarkers() {
  try {
    const data = await mapApi.list()
    markers.value = Array.isArray(data) ? data : []
    if (map) renderMapMarkers(markers.value)
  } catch { /* ignore */ }
}

// Search
const searchInput = ref('')
const searchResultsData = ref([])
const searchVisible = ref(false)
let searchTimer = null
let placeSearch = null

function initSearch() {
  if (!window.AMap) return
  AMap.plugin('AMap.PlaceSearch', function () {
    placeSearch = new AMap.PlaceSearch({ pageSize: 8 })
  })
}

function onSearchInput() {
  clearTimeout(searchTimer)
  if (!mapReady.value) {
    searchVisible.value = false
    return
  }
  const kw = searchInput.value.trim()
  if (!kw) { searchVisible.value = false; return }
  searchTimer = setTimeout(() => {
    if (!placeSearch) return
    placeSearch.search(kw, (status, result) => {
      if (status !== 'complete' || !result.poiList) {
        searchResultsData.value = []
        searchVisible.value = true
        return
      }
      searchResultsData.value = result.poiList.pois.map(p => ({
        name: p.name, address: p.address || p.cityname || '',
        lng: p.location.lng, lat: p.location.lat,
      }))
      searchVisible.value = true
    })
  }, 400)
}

function selectSearchResult(r) {
  if (!map) return
  map.setZoomAndCenter(15, [r.lng, r.lat])
  searchInput.value = r.name
  searchVisible.value = false
  openForm(r.name, r.lat, r.lng)
}

// Load AMap SDK dynamically
function loadAmapSDK() {
  return loadAmapFromConfig({
    plugins: ['AMap.PlaceSearch', 'AMap.AutoComplete', 'AMap.Geocoder'],
  })
}

async function initMapView() {
  if (mapLoading.value) return
  mapLoading.value = true
  mapReady.value = false
  mapError.value = ''
  searchVisible.value = false
  searchResultsData.value = []
  try {
    destroyMapInstance()
    await loadAmapSDK()
    if (!viewActive) return
    initMap()
    initSearch()
  } catch (error) {
    if (!viewActive) return
    destroyMapInstance()
    mapError.value = error?.message || '高德地图加载失败'
  } finally {
    mapLoading.value = false
  }
}

function retryMap() {
  if (mapLoading.value) return
  initMapView()
}

onMounted(() => {
  viewActive = true
  initMapView()
})

onUnmounted(() => {
  viewActive = false
  mapReady.value = false
  revokeLocalPhotoDrafts(form.value.photos)
  if (searchTimer) clearTimeout(searchTimer)
  destroyMapInstance()
})
</script>

<template>
  <TopBar title="🗺️ 恋爱足迹地图" @back="router.push('/')">
    <span class="marker-count">已标记 {{ markers.length }} 个地点</span>
  </TopBar>

  <!-- Search -->
  <div class="search-wrap">
    <div class="search-box" :class="{ 'is-disabled': !mapReady }">
      <span>🔍</span>
      <input
        v-model="searchInput"
        :disabled="!mapReady"
        :placeholder="mapLoading ? '地图加载中...' : mapReady ? '搜索地点名称...' : '地图不可用'"
        autocomplete="off"
        @input="onSearchInput"
      />
    </div>
    <div class="search-results" :class="{ 'is-visible': searchVisible && searchResultsData.length }">
      <div
        v-for="(r, i) in searchResultsData"
        :key="i"
        class="search-result-item"
        @click="selectSearchResult(r)"
      >
        <div class="search-result-name">{{ r.name }}</div>
        <div class="search-result-addr">{{ r.address }}</div>
      </div>
    </div>
  </div>

  <div id="map-container"></div>
  <div v-if="mapError" class="map-error" role="alert">
    <span>⚠️ {{ mapError }}</span>
    <button type="button" class="map-retry" :disabled="mapLoading" @click="retryMap">
      {{ mapLoading ? '重新加载中...' : '重新加载' }}
    </button>
  </div>

  <!-- FAB -->
  <button
    v-if="authStore.isAdmin"
    type="button"
    class="fab-add"
    :disabled="!mapReady || mapLoading"
    :aria-label="mapReady ? '添加恋爱足迹' : '地图不可用，暂时不能添加足迹'"
    @click="map && openForm('', map.getCenter().lat, map.getCenter().lng)"
  >+</button>

  <!-- Detail Card -->
  <div class="detail-backdrop" :class="{ 'is-visible': showDetail }" @click="showDetail = false"></div>
  <div class="detail-card" :class="{ 'is-visible': showDetail }" v-if="selectedMarker">
    <div class="detail-handle"></div>
    <!-- 照片轮播 -->
    <div v-if="selectedMarker.photos && selectedMarker.photos.length" class="detail-carousel">
      <div class="carousel-track" :style="{ transform: `translateX(-${carouselIndex * 100}%)` }">
        <img v-for="(url, i) in selectedMarker.photos" :key="i" :src="url" alt="" class="detail-photo" />
      </div>
      <div v-if="selectedMarker.photos.length > 1" class="carousel-nav">
        <button class="carousel-btn" type="button" aria-label="上一张照片" @click="carouselIndex = Math.max(0, carouselIndex - 1)" :disabled="carouselIndex === 0">
          <span class="carousel-glyph" aria-hidden="true">‹</span>
        </button>
        <span class="carousel-counter">{{ carouselIndex + 1 }} / {{ selectedMarker.photos.length }}</span>
        <button class="carousel-btn" type="button" aria-label="下一张照片" @click="carouselIndex = Math.min(selectedMarker.photos.length - 1, carouselIndex + 1)" :disabled="carouselIndex === selectedMarker.photos.length - 1">
          <span class="carousel-glyph" aria-hidden="true">›</span>
        </button>
      </div>
    </div>
    <!-- 兼容旧数据 -->
    <img v-else-if="selectedMarker.photo_url" class="detail-photo" :src="selectedMarker.photo_url" alt="" />
    <div class="detail-title">{{ selectedMarker.title }}</div>
    <div class="detail-date">{{ selectedMarker.visit_date ? `📅 ${selectedMarker.visit_date}` : '' }}</div>
    <div class="detail-note">{{ selectedMarker.note || '暂无备注' }}</div>
    <div class="detail-actions">
      <button v-if="selectedMarker.visit_date" class="btn-edit" @click="router.push(`/day/${selectedMarker.visit_date}`)">📅 这一天</button>
      <button v-if="authStore.isAdmin" class="btn-edit" @click="editDetail">✏️ 编辑</button>
      <button v-if="authStore.isAdmin" class="btn-delete" @click="deleteDetail">🗑️ 删除</button>
    </div>
  </div>

  <!-- Form Modal -->
  <GlassModal
    :model-value="showForm"
    :title="editingId ? '✏️ 编辑足迹' : '📍 添加足迹'"
    @update:model-value="handleFormVisibleChange"
  >
    <div class="form-group">
      <label>地点名称 *</label>
      <input v-model="form.name" placeholder="如：黄鹤楼" maxlength="100" />
    </div>
    <div class="form-group">
      <label>一句话备注</label>
      <textarea v-model="form.note" placeholder="如：第一次约会的地方"></textarea>
    </div>
    <div class="form-group">
      <label>日期</label>
      <input type="date" v-model="form.date" />
    </div>
    <div class="form-group">
      <label>照片（可选，支持多张）</label>
      <div class="photo-upload-area">
        <div class="photo-thumbs">
          <div v-for="(photo, i) in form.photos" :key="`${photo.url}-${i}`" class="photo-thumb-item">
            <img :src="photo.url" alt="" />
            <button class="photo-remove-btn" type="button" aria-label="移除这张待上传照片" @click="removePhoto(i)" :disabled="uploading">
              <span class="photo-remove-glyph" aria-hidden="true">✕</span>
            </button>
          </div>
          <label class="photo-add-btn">
            <span>＋</span>
            <input type="file" accept="image/*" multiple @change="handleFileSelect" :disabled="uploading" />
          </label>
        </div>
      </div>
    </div>
    <div class="form-btns">
      <button class="btn-cancel" @click="closeForm" :disabled="uploading">取消</button>
      <button class="btn-primary" @click="saveForm" :disabled="uploading">
        {{ uploading ? '保存中...' : '保存' }}
      </button>
    </div>
  </GlassModal>
</template>

<style scoped>
.marker-count {
  margin-left: auto; min-width: 0; font-size: 13px; color: var(--text-secondary);
  white-space: nowrap; overflow-wrap: anywhere;
}

#map-container { position: fixed; top: var(--topbar-actual-height); left: 0; right: 0; bottom: var(--tabbar-height); }
.map-error {
  position: fixed; left: 50%; top: calc(var(--topbar-actual-height) + 90px); z-index: 16;
  transform: translateX(-50%); width: max-content; max-width: min(520px, calc(100vw - 32px));
  padding: 10px 14px; border-radius: 12px; background: rgba(120, 30, 40, 0.9);
  color: #fff; font-size: 13px; line-height: 1.5; text-align: center;
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  overflow-wrap: anywhere; word-break: break-word;
}
.map-error > span { min-width: 0; }
.map-retry {
  min-height: 44px; padding: 8px 18px; border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.35);
  background: rgba(255, 255, 255, 0.14); color: #fff;
  font: inherit; font-weight: 600; cursor: pointer;
}
.map-retry:disabled { opacity: 0.5; cursor: not-allowed; }

.search-wrap { position: fixed; top: calc(var(--topbar-actual-height) + 12px); left: 16px; right: 16px; z-index: 15; }
.search-box { display: flex; align-items: center; gap: 8px; background: var(--glass-bg); backdrop-filter: blur(20px); border: 1px solid var(--glass-border); border-radius: 14px; padding: 8px 16px; }
.search-box input { flex: 1; border: none; background: transparent; outline: none; font-size: 15px; color: var(--text-primary); }
.search-box.is-disabled { opacity: 0.6; }
.search-box input:disabled { cursor: not-allowed; }
.search-box input::placeholder { color: var(--text-secondary); }

.search-results { margin-top: 6px; max-height: 260px; overflow-y: auto; background: rgba(30, 30, 50, 0.92); backdrop-filter: blur(20px); border-radius: 12px; border: 1px solid var(--glass-border); display: none; }
.search-results.is-visible { display: block; }
.search-result-item { padding: 12px 16px; cursor: pointer; font-size: 14px; border-bottom: 1px solid rgba(255, 255, 255, 0.06); transition: background 0.15s; }
.search-result-item:hover { background: rgba(255, 255, 255, 0.08); }
.search-result-name { min-width: 0; font-weight: 600; overflow-wrap: anywhere; word-break: break-word; }
.search-result-addr { min-width: 0; font-size: 12px; color: var(--text-secondary); margin-top: 2px; overflow-wrap: anywhere; word-break: break-word; }

.fab-add { position: fixed; bottom: var(--fab-bottom); right: var(--fab-right); z-index: 15; width: 56px; height: 56px; border-radius: 50%; border: none; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: #fff; font-size: 28px; cursor: pointer; box-shadow: 0 6px 24px rgba(255, 107, 157, 0.4); transition: all 0.25s; display: flex; align-items: center; justify-content: center; }
.fab-add:hover { transform: scale(1.1); }
.fab-add:disabled { opacity: 0.45; cursor: not-allowed; transform: none; box-shadow: none; }

/* Detail Card */
.detail-backdrop { position: fixed; inset: 0; z-index: 25; background: rgba(0, 0, 0, 0.4); opacity: 0; pointer-events: none; transition: opacity 0.3s; }
.detail-backdrop.is-visible { opacity: 1; pointer-events: auto; }
.detail-card {
  position: fixed; bottom: 0; left: 0; right: 0; z-index: 30;
  min-width: 0; background: rgba(30, 30, 50, 0.95); backdrop-filter: blur(30px);
  border-top: 1px solid var(--glass-border); border-radius: 24px 24px 0 0;
  padding: 20px 24px calc(36px + var(--safe-bottom));
  transform: translateY(100%); transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1);
  max-height: 70dvh; overflow-y: auto; overflow-wrap: anywhere; word-break: break-word;
}
.detail-card.is-visible { transform: translateY(0); }
.detail-handle { width: 40px; height: 4px; border-radius: 2px; background: rgba(255, 255, 255, 0.2); margin: 0 auto 16px; }
.detail-photo { width: 100%; max-height: 240px; object-fit: cover; border-radius: 16px; margin-bottom: 16px; }
.detail-title { min-width: 0; font-size: 20px; font-weight: 700; margin-bottom: 6px; }
.detail-date { min-width: 0; font-size: 13px; color: var(--accent); margin-bottom: 10px; }
.detail-note { min-width: 0; font-size: 14px; color: var(--text-secondary); line-height: 1.6; margin-bottom: 20px; }
.detail-actions { display: flex; gap: 12px; flex-wrap: wrap; }
.detail-actions button { flex: 1; padding: 12px; border-radius: 12px; border: none; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
.btn-edit { background: rgba(255, 255, 255, 0.1); color: #fff; border: 1px solid rgba(255, 255, 255, 0.2) !important; }
.btn-edit:hover { background: rgba(255, 255, 255, 0.18); }
.btn-delete { background: rgba(220, 38, 38, 0.2); color: #f87171; }
.btn-delete:hover { background: rgba(220, 38, 38, 0.35); }

/* Form */
.form-group { min-width: 0; margin-bottom: 14px; }
.form-group label { display: block; font-size: 13px; color: var(--text-secondary); margin-bottom: 6px; }
.form-group input, .form-group textarea { width: 100%; min-height: 44px; padding: 10px 14px; border-radius: 10px; border: 1px solid var(--glass-border); background: rgba(255, 255, 255, 0.06); color: #fff; font-size: 14px; outline: none; transition: border-color 0.2s; }
.form-group input:focus, .form-group textarea:focus { border-color: var(--primary); }
.form-group textarea { resize: vertical; min-height: 60px; }
.form-btns { display: flex; gap: 12px; margin-top: 20px; }
.form-btns button { flex: 1; min-height: 44px; padding: 12px; border-radius: 12px; border: none; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
.btn-cancel { background: rgba(255, 255, 255, 0.1); color: #fff; }

:deep(.love-marker) { width: 44px; height: 44px; display: flex; align-items: center; justify-content: center; font-size: 24px; filter: drop-shadow(0 2px 6px rgba(255, 107, 157, 0.5)); cursor: pointer; transition: transform 0.2s; touch-action: manipulation; }
:deep(.love-marker:hover) { transform: scale(1.3); }

@media (max-width: 720px) {
  .search-wrap {
    left: 10px;
    right: 10px;
  }

  .search-box {
    padding: 6px 12px;
    border-radius: 12px;
  }

  .search-box input {
    font-size: 16px;
  }

  .fab-add {
    width: 48px;
    height: 48px;
    font-size: 24px;
  }

  .detail-card {
    padding: 16px 18px calc(16px + var(--tabbar-height));
  }

  .detail-title {
    font-size: 18px;
  }

  .detail-actions button {
    padding: 10px;
    font-size: 13px;
  }

  .marker-count {
    font-size: 12px;
  }
}

/* 照片上传区 */
.photo-upload-area { margin-top: 4px; }
.photo-thumbs { display: flex; flex-wrap: wrap; gap: 8px; }
.photo-thumb-item {
  position: relative; width: 72px; height: 72px; border-radius: 10px; overflow: hidden;
  border: 1px solid rgba(255,255,255,0.1);
}
.photo-thumb-item img { width: 100%; height: 100%; object-fit: cover; }
.photo-remove-btn {
  position: absolute; top: 0; right: 0; width: 44px; height: 44px;
  padding: 2px; border-radius: 0; border: none; background: transparent; color: #fff;
  cursor: pointer; display: flex; align-items: flex-start; justify-content: flex-end;
}
.photo-remove-glyph {
  width: 20px; height: 20px; border-radius: 50%;
  background: rgba(0, 0, 0, 0.7); font-size: 11px;
  display: flex; align-items: center; justify-content: center;
}
.photo-remove-btn:hover .photo-remove-glyph { background: #ef4444; }
.photo-add-btn {
  width: 72px; height: 72px; border-radius: 10px; border: 2px dashed rgba(255,255,255,0.2);
  display: flex; align-items: center; justify-content: center; cursor: pointer;
  color: rgba(255,255,255,0.4); font-size: 24px; transition: all 0.2s;
}
.photo-add-btn:hover { border-color: var(--primary); color: var(--primary); }
.photo-add-btn input { display: none; }

/* 照片轮播 */
.detail-carousel { position: relative; min-width: 0; overflow: hidden; border-radius: 16px; margin-bottom: 16px; background: rgba(0,0,0,0.3); }
.carousel-track { display: flex; transition: transform 0.3s ease; }
.carousel-track .detail-photo {
  min-width: 100%; height: 320px; object-fit: contain; flex-shrink: 0;
  background: rgba(0,0,0,0.2);
}
.carousel-nav {
  display: flex; align-items: center; justify-content: center; gap: 12px;
  padding: 8px 0;
}
.carousel-btn {
  width: 44px; height: 44px; border-radius: 50%; border: none;
  padding: 0; background: transparent; color: #fff; font-size: 18px;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: background 0.2s;
}
.carousel-glyph {
  width: 32px; height: 32px; border-radius: 50%;
  background: rgba(255,255,255,0.1);
  display: flex; align-items: center; justify-content: center;
}
.carousel-btn:hover:not(:disabled) .carousel-glyph { background: rgba(255,255,255,0.2); }
.carousel-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.carousel-counter { font-size: 13px; color: var(--text-secondary); }
</style>
