// Data access: plain fetches, plus one shared event stream that tells views when to refetch.
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'

// ---- who is looking: { login_required, authenticated, can_read, can_act, name, csrf, password_configured }
export const session = ref(null)

async function parse(response) {
  if (response.status === 401 && session.value?.authenticated) loadSession()      // the session ran out
  if (!response.ok) {
    let detail = response.statusText
    try { detail = (await response.json()).detail ?? detail } catch { /* not JSON */ }
    throw new Error(detail)
  }
  return response.json()
}

export async function get(path, params) {
  const query = params ? '?' + new URLSearchParams(params) : ''
  return parse(await fetch(`/api${path}${query}`))
}

export async function post(path, body) {
  return parse(await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.value?.csrf ?? '' },
    body: JSON.stringify(body ?? {}),
  }))
}

export async function loadSession() {
  session.value = await get('/session')
  return session.value
}
export async function login(password, name) {
  session.value = await post('/login', { password, name })
}
export async function logout() {
  session.value = await post('/logout')
  source?.close()
  source = null
}
/** Send one operator command to the hub; resolves with its reply { ok, result | error }. */
export const act = (command) => post('/commands', command)

// ---- site description (fetched once)
export const site = ref(null)
export const simulated = ref(false)        // a simulator is on the bus: show its page
export const scenario = ref(null)          // set when this dashboard shows a finished scenario run
let sitePromise = null
export function loadSite() {
  get('/sim').then((sim) => { simulated.value = sim.present }).catch(() => {})
  get('/scenario').then((run) => { scenario.value = run.present ? run : null }).catch(() => {})
  sitePromise ??= get('/site').then((data) => (site.value = data)).catch((err) => { sitePromise = null; throw err })
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
