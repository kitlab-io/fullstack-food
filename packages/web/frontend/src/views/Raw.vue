<script setup>
// For developers and for debugging a real node: live MQTT traffic, raw samples, downloads.
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { get, site } from '../api.js'
import SeriesChart from '../components/SeriesChart.vue'
import { clock, quantityLabel } from '../format.js'

// ---- MQTT tail
const KEEP = 500
const messages = ref([])
const topic = ref('')
const paused = ref(false)
const onlyBad = ref(false)
const open = ref(new Set())
const tailError = ref(null)
let source = null
let pending = []
let flush = null

function matches(message) {
  return !topic.value || message.topic.includes(topic.value)
}
const shown = computed(() => messages.value.filter((m) => matches(m) && (!onlyBad.value || m.errors.length)))
const badCount = computed(() => messages.value.filter((m) => m.errors.length).length)

onMounted(async () => {
  try {
    messages.value = (await get('/mqtt/recent', { limit: KEEP })).messages.reverse()
  } catch (err) {
    tailError.value = err.message
  }
  source = new EventSource('/api/stream?raw=true')
  source.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.kind === 'mqtt' && !paused.value) pending.push(data)
  }
  // A simulated site at 600x sends hundreds of messages a second: draw at most four times a second.
  flush = setInterval(() => {
    if (!pending.length) return
    messages.value = pending.reverse().concat(messages.value).slice(0, KEEP)
    pending = []
  }, 250)
})
onBeforeUnmount(() => { source?.close(); clearInterval(flush) })

function toggle(n) {
  const next = new Set(open.value)
  next.has(n) ? next.delete(n) : next.add(n)
  open.value = next
}
const preview = (payload) => (typeof payload === 'string' ? payload : JSON.stringify(payload))

// ---- readings browser
const pick = reactive({ device: '', quantity: '', hours: 6 })
const samples = ref(null)
const readError = ref(null)
const sensors = ref([])
onMounted(async () => {
  const nodes = (await get('/devices')).nodes
  sensors.value = nodes.flatMap((n) => n.devices).filter((d) => d.class === 'sensor' && d.values.length)
  if (sensors.value.length) {
    pick.device = sensors.value[0].id
    pick.quantity = sensors.value[0].values[0].quantity
  }
})
const quantities = computed(() => {
  const device = sensors.value.find((d) => d.id === pick.device)
  return device ? [...device.values.map((v) => v.quantity), 'raw'] : []
})
watch(() => pick.device, () => { if (!quantities.value.includes(pick.quantity)) pick.quantity = quantities.value[0] ?? '' })

async function loadSamples() {
  if (!pick.device || !pick.quantity) return
  readError.value = null
  try {
    const now = new Date((await get('/health')).now)
    const from = new Date(now - pick.hours * 3600e3).toISOString()
    samples.value = await get('/readings', { device: pick.device, quantity: pick.quantity, from })
  } catch (err) {
    readError.value = err.message
    samples.value = null
  }
}
watch(() => [pick.device, pick.quantity, pick.hours], loadSamples)
const series = computed(() => samples.value && {
  quantity: samples.value.quantity, unit: sensors.value.find((d) => d.id === pick.device)?.values.find((v) => v.quantity === pick.quantity)?.unit,
  device: samples.value.device, resolution: 'raw', from: samples.value.from, to: samples.value.to,
  t: samples.value.samples.map((s) => Date.parse(s.t) / 1e3), mean: samples.value.samples.map((s) => s.value), min: null, max: null,
})
const csvUrl = computed(() => samples.value && `/api/readings?${new URLSearchParams({
  device: pick.device, quantity: pick.quantity, from: samples.value.from, to: samples.value.to, format: 'csv' })}`)

// ---- downloads
const meta = ref({ developer: false })
onMounted(async () => { meta.value = await get('/meta') })
</script>

<template>
  <h1>Raw data</h1>

  <section class="card">
    <div class="row spread">
      <h2>MQTT traffic</h2>
      <div class="row">
        <label class="check"><input v-model="onlyBad" type="checkbox" /> Only contract violations ({{ badCount }})</label>
        <button type="button" class="button" :aria-pressed="paused" @click="paused = !paused">{{ paused ? 'Resume' : 'Pause' }}</button>
      </div>
    </div>
    <label class="field">Topic contains
      <input v-model="topic" type="search" :placeholder="`e.g. ${site?.zones[0]?.devices[0] ?? 'state'}`" />
    </label>
    <p v-if="tailError" class="error">Could not load recent traffic: {{ tailError }}</p>
    <ul class="tail" aria-label="MQTT messages, newest first">
      <li v-for="m in shown" :key="m.n">
        <button type="button" class="line" :aria-expanded="open.has(m.n)" @click="toggle(m.n)">
          <time class="tnum muted">{{ clock(m.t, site?.timezone) }}</time>
          <span class="topic">{{ m.topic }}</span>
          <span v-if="m.errors.length" class="pill bad" :title="m.errors.join('; ')">breaks {{ m.schema }}</span>
          <span v-else-if="m.schema" class="pill good">{{ m.schema }}</span>
          <span v-else class="pill">no schema</span>
          <span class="payload muted">{{ preview(m.payload) }}</span>
        </button>
        <div v-if="open.has(m.n)" class="detail">
          <p v-for="e in m.errors" :key="e" class="error small">{{ e }}</p>
          <pre>{{ typeof m.payload === 'string' ? m.payload : JSON.stringify(m.payload, null, 2) }}</pre>
        </div>
      </li>
    </ul>
    <p v-if="!shown.length" class="muted">No messages{{ topic || onlyBad ? ' match' : ' yet' }}.</p>
    <p class="small muted">The last {{ KEEP }} messages, checked against schemas/mqtt. The simulator's clock ticks are left out.</p>
  </section>

  <section class="card">
    <h2>Readings</h2>
    <form class="row" @submit.prevent>
      <label class="field">Device
        <select v-model="pick.device"><option v-for="d in sensors" :key="d.id" :value="d.id">{{ d.id }}</option></select>
      </label>
      <label class="field">Quantity
        <select v-model="pick.quantity"><option v-for="q in quantities" :key="q" :value="q">{{ q === 'raw' ? 'Raw (uncalibrated)' : quantityLabel(q) }}</option></select>
      </label>
      <label class="field">Range
        <select v-model.number="pick.hours">
          <option :value="1">1 hour</option><option :value="6">6 hours</option><option :value="24">24 hours</option><option :value="72">3 days</option>
        </select>
      </label>
      <a v-if="csvUrl" class="button" :href="csvUrl">Download CSV</a>
    </form>
    <p v-if="readError" class="error">{{ readError }}</p>
    <SeriesChart v-if="series" :series="series" :time-zone="site?.timezone" />
    <p v-if="samples" class="small muted">{{ samples.samples.length }} samples, exactly as stored (no averaging). Kept for 30 days.</p>
  </section>

  <section class="card">
    <h2>Downloads</h2>
    <p><a class="button" href="/api/export/diagnostics">Diagnostics bundle</a>
      <span class="muted small"> Site file with secrets replaced, hub state, and the last 24 hours of the log. Safe to attach to an issue.</span></p>
    <p v-if="meta.developer"><a class="button" href="/api/export/db">Whole database</a>
      <span class="muted small"> A consistent copy of the hub's SQLite file.</span></p>
    <p v-else class="muted small">Database download is off. Start the dashboard with <code>--developer</code> to allow it.</p>
  </section>
</template>

<style scoped>
.card { display: grid; gap: 0.75rem; min-width: 0; }
.field { display: grid; gap: 0.2rem; font-size: 0.8rem; color: var(--muted-text); }
.filters select, .filters input, .field select, .field input { width: auto; }
.check { display: inline-flex; gap: 0.35rem; align-items: center; font-size: 0.9rem; }
.button { border: 1px solid var(--line); border-radius: 0.4rem; padding: 0.25rem 0.6rem; text-decoration: none; font-size: 0.9rem; background: none; cursor: pointer; align-self: end; }
.tail { list-style: none; margin: 0; padding: 0; max-height: 28rem; overflow-y: auto; border: 1px solid var(--line); border-radius: 0.5rem; }
.tail li + li { border-top: 1px solid var(--line); }
.line {
  display: grid; grid-template-columns: 3.2rem minmax(10rem, 22rem) auto 1fr; gap: 0.6rem; align-items: baseline;
  width: 100%; padding: 0.3rem 0.6rem; border: 0; background: none; text-align: left; cursor: pointer; font-size: 0.85rem;
}
.line:hover { background: var(--track); }
.topic { font-family: ui-monospace, Consolas, monospace; overflow-wrap: anywhere; }
.payload { font-family: ui-monospace, Consolas, monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.detail { padding: 0 0.6rem 0.6rem; display: grid; gap: 0.4rem; }
pre { margin: 0; padding: 0.6rem; background: var(--bg); border-radius: 0.5rem; overflow-x: auto; font-size: 0.8rem; }
@media (max-width: 46rem) {
  .line { grid-template-columns: auto 1fr; }
  .payload { display: none; }
}
</style>
