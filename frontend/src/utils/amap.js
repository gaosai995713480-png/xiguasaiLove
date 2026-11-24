import { tripstarApi } from '../api'

const SCRIPT_ID = 'shared-amap-js-sdk'
const DEFAULT_TIMEOUT_MS = 12_000

let sdkPromise = null
let sdkSignature = ''

function waitForExistingScript(script, timeoutMs) {
  if (window.AMap) return Promise.resolve(window.AMap)

  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (handler, value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      script.removeEventListener('load', onLoad)
      script.removeEventListener('error', onError)
      handler(value)
    }
    const onLoad = () => {
      if (window.AMap) finish(resolve, window.AMap)
      else finish(reject, new Error('高德地图 SDK 加载完成但未初始化'))
    }
    const onError = () => finish(reject, new Error('高德地图 SDK 加载失败'))
    const timer = setTimeout(
      () => finish(reject, new Error('高德地图 SDK 加载超时')),
      timeoutMs,
    )
    script.addEventListener('load', onLoad, { once: true })
    script.addEventListener('error', onError, { once: true })
  })
}

function loadScript(config, plugins, timeoutMs) {
  window._AMapSecurityConfig = {
    ...(window._AMapSecurityConfig || {}),
    securityJsCode: config.amap_security_js_code,
  }

  if (window.AMap?.Map) return Promise.resolve(window.AMap)

  const params = new URLSearchParams({
    v: '2.0',
    key: config.amap_web_js_key,
  })
  if (plugins.length) params.set('plugin', plugins.join(','))

  let script = document.getElementById(SCRIPT_ID)
  if (script) {
    script.remove()
  }
  script = document.createElement('script')
  script.id = SCRIPT_ID
  script.async = true
  script.src = `https://webapi.amap.com/maps?${params.toString()}`

  const promise = waitForExistingScript(script, timeoutMs)
  document.head.appendChild(script)
  return promise
}

function loadPlugins(AMap, plugins, timeoutMs) {
  if (!plugins.length || !AMap?.plugin) return Promise.resolve()
  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (handler, value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      handler(value)
    }
    const timer = setTimeout(
      () => finish(reject, new Error('高德地图插件加载超时')),
      timeoutMs,
    )
    try {
      AMap.plugin(plugins, () => finish(resolve))
    } catch (error) {
      finish(reject, error)
    }
  })
}

export async function loadAmapFromConfig({
  plugins = [],
  timeoutMs = DEFAULT_TIMEOUT_MS,
} = {}) {
  let configTimer
  let config
  try {
    config = await Promise.race([
      tripstarApi.getMapConfig(),
      new Promise((_, reject) => {
        configTimer = setTimeout(
          () => reject(new Error('高德地图配置加载超时')),
          timeoutMs,
        )
      }),
    ])
  } finally {
    clearTimeout(configTimer)
  }
  if (!config.configured || !config.amap_web_js_key || !config.amap_security_js_code) {
    throw new Error(config.message || '高德地图前端配置未完成')
  }

  const signature = `${config.amap_web_js_key}:${config.amap_security_js_code}`
  if (!sdkPromise || signature !== sdkSignature) {
    sdkSignature = signature
    sdkPromise = loadScript(config, plugins, timeoutMs).catch((error) => {
      sdkPromise = null
      sdkSignature = ''
      throw error
    })
  }

  const AMap = await sdkPromise
  await loadPlugins(AMap, plugins, timeoutMs)
  return AMap
}
