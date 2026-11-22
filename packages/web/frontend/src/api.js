// Data access: plain fetches, plus one shared event stream that tells views when to refetch.
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'

export async function get(path, params) {
  const query = params ? '?' + new URLSearchParams(params) : ''
  const response = await fetch(`/api${path}${query}`)
  if (!response.ok) {
    let detail = response.statusText
    try { detail = (await response.json()).detail ?? detail } catch { /* not JSON */ }
    throw new Error(detail)
  }
  return response.json()
}

// ---- site description (fetched once)
export const site = ref(null)
let sitePromise = null
export function loadSite() {
  sitePromise ??= get('/site').then((data) => (site.value = data))
  return sitePromise
}

// ---- live event stream
export const connection = reactive({ live: false, lastEvent: null })
const listeners = new Set()
let source = null

function connect() {
  if (source) return
  source = new EventSource('/api/stream')
  source.onopen = () => { connection.live = true }
  source.onerror = () => { connection.live = false }     // the browser reconnects by itself
  source.onmessage = (message) => {
    connection.live = true
    const event = JSON.parse(message.data)
    connection.lastEvent = Date.now()
    for (const listener of listeners) listener(event)
  }
}

/**
 * Fetch with `load`, then again whenever a live event passes `wants`, at most once per
 * `every` ms (a simulated site at 600x speed sends many events a second). Also refetches
 * on a slow timer so a broken stream does not leave the page stale.
 */
export function useLive(load, { wants = () => true, every = 2000, fallback = 30000 } = {}) {
  const error = ref(null)
  const loading = ref(true)
  let timer = null
  let last = 0
  let stopped = false

  async function run() {
    timer = null
    last = Date.now()
    try {
      await load()
      error.value = null
    } catch (err) {
      error.value = err.message
    } finally {
      loading.value = false
    }
  }
  function schedule() {
    if (timer || stopped) return
    timer = setTimeout(run, Math.max(0, every - (Date.now() - last)))
  }
  const onEvent = (event) => { if (wants(event)) schedule() }
  let slow = null

  onMounted(() => {
    connect()
    listeners.add(onEvent)
    run()
    slow = setInterval(schedule, fallback)
  })
  onBeforeUnmount(() => {
    stopped = true
    listeners.delete(onEvent)
    clearTimeout(timer)
    clearInterval(slow)
  })
  return { error, loading, refresh: run }
}
