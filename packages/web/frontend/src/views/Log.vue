<script setup>
// The event log and the decision trace in one filterable table that follows live.
import { computed, reactive, ref, watch } from 'vue'

import { get, site, useLive } from '../api.js'
import { clock, sentence } from '../format.js'

const filters = reactive({ level: 'info', group: '', zone: '', device: '', q: '' })
const follow = ref(true)
const rows = ref([])
const groups = ref([])
const open = ref(new Set())

const params = computed(() => {
  const out = { level: filters.level, limit: 300 }
  for (const key of ['group', 'zone', 'device', 'q']) if (filters[key]) out[key] = filters[key]
  return out
})
const { error, loading, refresh } = useLive(async () => {
  if (!follow.value && rows.value.length) return
  const body = await get('/log', params.value)
  rows.value = body.rows.slice().reverse()            // newest on top
  groups.value = body.groups
}, { every: 3000, wants: (event) => event.kind !== 'device' })

let typing = null
watch(params, () => {
  clearTimeout(typing)
  typing = setTimeout(() => { const was = follow.value; follow.value = true; refresh().finally(() => (follow.value = was)) }, 250)
})
watch(follow, (on) => on && refresh())

const devices = computed(() => (site.value?.zones ?? []).flatMap((z) => z.devices).filter((d, i, all) => all.indexOf(d) === i).sort())
const exportUrl = (format) => `/api/log?${new URLSearchParams({ ...params.value, limit: 5000, format })}`
function toggle(id) {
  const next = new Set(open.value)
  next.has(id) ? next.delete(id) : next.add(id)
  open.value = next
}
</script>

<template>
  <div class="row spread">
    <h1>Log</h1>
    <div class="row">
      <label class="check"><input v-model="follow" type="checkbox" /> Follow</label>
      <a class="button" :href="exportUrl('csv')">CSV</a>
      <a class="button" :href="exportUrl('jsonl')">JSON Lines</a>
    </div>
  </div>

  <form class="card filters" @submit.prevent>
    <label>Level
      <select v-model="filters.level">
        <option value="debug">Everything (debug)</option>
        <option value="info">Info and above</option>
        <option value="warn">Warnings and errors</option>
        <option value="error">Errors</option>
      </select>
    </label>
    <label>Kind
      <select v-model="filters.group">
        <option value="">All kinds</option>
        <option v-for="g in groups" :key="g" :value="g">{{ sentence(g) }}</option>
      </select>
    </label>
    <label>Zone
      <select v-model="filters.zone">
        <option value="">All zones</option>
        <option v-for="z in site?.zones ?? []" :key="z.id" :value="z.id">{{ z.id }}</option>
      </select>
    </label>
    <label>Device
      <select v-model="filters.device">
        <option value="">All devices</option>
        <option v-for="d in devices" :key="d" :value="d">{{ d }}</option>
      </select>
    </label>
    <label class="grow">Contains
      <input v-model="filters.q" type="search" placeholder="any text, e.g. reservoir" />
    </label>
  </form>

  <p v-if="error" class="error">Could not load the log: {{ error }}</p>
  <p v-else-if="loading" class="muted">Loading…</p>
  <p v-else-if="!rows.length" class="muted">Nothing matches these filters.</p>

  <ul class="card log" aria-label="Log entries">
    <li v-for="row in rows" :key="row.id" :class="row.level">
      <button type="button" class="line" :aria-expanded="open.has(row.id)" @click="toggle(row.id)">
        <time class="tnum">{{ clock(row.t, site?.timezone, true) }}</time>
        <span class="pill" :class="{ bad: row.level === 'warn' || row.level === 'error' }">{{ row.level }}</span>
        <span class="kind">{{ sentence(row.group) }}</span>
        <span class="text">{{ row.text }}</span>
        <span class="where muted">{{ [row.zone, row.planting].filter(Boolean).join(' · ') }}</span>
      </button>
      <div v-if="open.has(row.id)" class="detail">
        <pre>{{ JSON.stringify({ kind: row.kind, ...row.data }, null, 2) }}</pre>
        <RouterLink v-if="row.zone" :to="`/zones/${row.zone}`">Charts for {{ row.zone }}</RouterLink>
        <RouterLink v-if="row.data.status" :to="`/help/${row.data.status}`">What to check for {{ row.data.status.replaceAll('_', ' ') }}</RouterLink>
        <RouterLink v-else-if="row.kind === 'status_changed'" :to="`/help/${row.data.state}`">What {{ row.data.state.replaceAll('_', ' ') }} means</RouterLink>
      </div>
    </li>
  </ul>
  <p v-if="rows.length" class="small muted">Newest first, up to 300 entries. Decisions are kept for 14 days, events for good.</p>
</template>

<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: 0.75rem 1rem; }
.filters label { display: grid; gap: 0.2rem; font-size: 0.8rem; color: var(--muted-text); }
.filters .grow { flex: 1 1 12rem; }
.filters select, .filters input, .field select, .field input { width: auto; }
.check { display: inline-flex; gap: 0.35rem; align-items: center; }
.button { border: 1px solid var(--line); border-radius: 0.4rem; padding: 0.25rem 0.6rem; text-decoration: none; font-size: 0.9rem; }
.log { list-style: none; margin: 0; padding: 0.25rem 0; }
.log li + li { border-top: 1px solid var(--line); }
.line {
  display: grid; grid-template-columns: 7.5rem 3.6rem 5.5rem 1fr auto; gap: 0.75rem; align-items: baseline;
  width: 100%; padding: 0.45rem 1rem; border: 0; background: none; text-align: left; cursor: pointer;
}
.line:hover { background: var(--track); }
.kind { color: var(--muted-text); font-size: 0.85rem; }
.text { overflow-wrap: anywhere; }
.debug .text { color: var(--muted-text); }
.warn .text, .error .text { color: var(--warn-text); }
.where { font-size: 0.85rem; white-space: nowrap; }
.detail { padding: 0 1rem 0.75rem; display: grid; gap: 0.5rem; }
pre { margin: 0; padding: 0.75rem; background: var(--bg); border-radius: 0.5rem; overflow-x: auto; font-size: 0.8rem; }
@media (max-width: 46rem) {
  .line { grid-template-columns: auto auto 1fr; }
  .text { grid-column: 1 / -1; }
  .where { grid-column: 1 / -1; white-space: normal; }
}
</style>
