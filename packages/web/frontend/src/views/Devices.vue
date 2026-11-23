<script setup>
import { ref } from 'vue'

import { act, get, session, site, useLive } from '../api.js'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import { ago, clock, reading, sentence, span } from '../format.js'

const nodes = ref([])
const { error, loading, refresh } = useLive(async () => { nodes.value = (await get('/devices')).nodes }, { every: 3000 })

// Test pulse: a short leased on-command through the hub, for commissioning.
const pulseDialog = ref(null)
const pulsing = ref(null)
const pulseResult = ref(null)
async function pulse(device) {
  pulsing.value = device
  pulseResult.value = null
  if (!(await pulseDialog.value.ask())) return
  try {
    const reply = await act({ name: 'actuator_test', device: device.id, duration_s: 2 })
    pulseResult.value = { id: device.id, ok: reply.ok, text: reply.ok ? 'Pulsed for 2 s.' : `The hub refused: ${reply.error}` }
    refresh()
  } catch (err) {
    pulseResult.value = { id: device.id, ok: false, text: err.message }
  }
}

const DRIVER = {
  verified: 'passes the test suite',
  bench: 'run by hand on a bench',
  untested: 'expected to work, never run',
}
const role = (device) => device.roles.map((r) => sentence(r.split('.')[1])).join(', ')
const pins = (device) => Object.entries(device.pins).map(([signal, pin]) => `${signal} ${pin}`).join(' · ')

function now(device) {
  if (device.class === 'sensor') {
    const shown = device.values.filter((v) => typeof v.value === 'number')
    return shown.length ? shown.map((v) => reading(v.value, v.quantity, v.unit)).join(' · ') : 'no reading'
  }
  if (device.class === 'actuator') {
    if (device.on === null || device.on === undefined) return 'not reported'
    const lease = device.on && device.lease_remaining_s !== null ? `, lease ${span(device.lease_remaining_s)}` : ''
    return device.on ? `on${lease}` : 'off'
  }
  return device.age_s === null ? 'not reported' : 'showing status'
}
</script>

<template>
  <h1>Devices</h1>
  <p v-if="error" class="error">Could not load devices: {{ error }}</p>
  <p v-else-if="loading" class="muted">Loading…</p>

  <section v-for="node in nodes" :key="node.id" class="card node">
    <header class="row spread">
      <div>
        <h2>{{ node.id }}</h2>
        <p class="muted small">{{ node.board }} · runtime {{ node.runtime }}</p>
      </div>
      <span class="pill" :class="{ good: node.online, bad: node.online === false }">
        {{ node.online ? 'online' : node.online === false ? 'offline' : 'not seen' }}
        <template v-if="node.since"> since {{ clock(node.since, site?.timezone, true) }}</template>
      </span>
    </header>

    <div class="table" role="table" :aria-label="`Devices on ${node.id}`">
      <div class="tr th" role="row">
        <span role="columnheader">Device</span><span role="columnheader">Now</span>
        <span role="columnheader">Last heard</span><span role="columnheader">Driver</span>
      </div>
      <div v-for="device in node.devices" :key="device.id" class="tr" role="row">
        <span role="cell">
          <strong>{{ device.id }}</strong>
          <span class="muted small block">{{ role(device) }} · {{ device.model_name ?? device.model }}</span>
          <span v-if="pins(device)" class="muted small block">{{ pins(device) }}</span>
        </span>
        <span role="cell" class="tnum">
          <span class="label">Now</span>{{ now(device) }}
          <span v-if="device.class === 'actuator' && device.switched_on_24h !== undefined" class="muted small block">
            {{ device.switched_on_24h }}× on in 24 h, {{ span(device.on_s_24h) }} in total
          </span>
          <button v-if="device.class === 'actuator' && session?.can_act" type="button" class="small block-button" @click="pulse(device)">
            Test pulse
          </button>
          <span v-if="pulseResult?.id === device.id" class="small block" :class="{ warn: !pulseResult.ok }" role="status">{{ pulseResult.text }}</span>
          <span v-if="device.unacked" class="pill bad">{{ device.unacked }} unanswered command{{ device.unacked === 1 ? '' : 's' }}</span>
        </span>
        <span role="cell" class="tnum"><span class="label">Last heard</span>{{ ago(device.age_s) }}</span>
        <span role="cell">
          <span class="label">Driver</span>
          <span class="pill" :class="{ good: device.driver_status === 'verified', bad: !device.driver_status }">
            {{ device.driver_status ?? 'none' }}
          </span>
          <span class="muted small block">{{ DRIVER[device.driver_status] ?? `no ${node.runtime} driver` }}</span>
          <span v-if="device.datasheet_checked === false" class="muted small block">wiring data not yet checked against the datasheet</span>
          <span v-for="(record, step) in device.commissioning" :key="step" class="pill" :class="record.ok ? 'good' : 'bad'"
                :title="`${clock(record.t, site?.timezone, true)} by ${record.by ?? 'unknown'}`">
            {{ sentence(step) }} {{ record.ok ? 'passed' : 'failed' }}
          </span>
        </span>
      </div>
    </div>
  </section>

  <ConfirmDialog ref="pulseDialog" title="Test pulse" confirm-label="Switch on for 2 s">
    <p><strong>{{ pulsing?.id }}</strong> ({{ pulsing?.model_name ?? pulsing?.model }}) is switched on for 2 seconds, then off.</p>
    <p class="muted">Make sure it is safe for it to run: water in the reservoir for a pump, nothing touching a heater.</p>
  </ConfirmDialog>
</template>

<style scoped>
.node { display: grid; gap: 0.75rem; }
.table { display: grid; }
.tr { display: grid; grid-template-columns: 2.2fr 1.6fr 0.9fr 1.6fr; gap: 0.75rem; padding: 0.6rem 0; border-top: 1px solid var(--line); align-items: start; }
.th { color: var(--muted-text); font-size: 0.8rem; border-top: 0; padding-bottom: 0.25rem; }
.block { display: block; }
.block-button { display: block; margin-top: 0.35rem; }
.warn { color: var(--warn-text); }
.label { display: none; }
@media (max-width: 46rem) {
  .th { display: none; }
  .tr { grid-template-columns: 1fr; gap: 0.35rem; }
  .label { display: inline-block; min-width: 6rem; color: var(--muted-text); font-size: 0.8rem; }
}
</style>
