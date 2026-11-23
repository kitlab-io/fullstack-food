<script setup>
// Shown only on a simulated site: time control and fault injection, for demos and manual tests.
import { computed, reactive, ref } from 'vue'

import { get, post, session, site, useLive } from '../api.js'
import { clock, quantityLabel, sentence } from '../format.js'

const sim = ref(null)
const nodes = ref([])
const message = ref(null)
const ambient = reactive({ air_temperature: null, relative_humidity: null })
const stuck = reactive({})          // device -> { quantity, value }
const reservoir = reactive({})      // device -> percent

const { error } = useLive(async () => {
  const [state, devices] = await Promise.all([get('/sim'), get('/devices')])
  sim.value = state
  nodes.value = devices.nodes
  if (ambient.air_temperature === null && state.present) Object.assign(ambient, state.ambient)
}, { every: 1500, wants: (event) => event.kind === 'sim' || event.kind === 'node' })

const faults = computed(() => sim.value?.faults ?? { dropouts: [], stuck: [], offline_nodes: [], no_flow: [], ignoring: [], weak: {} })
const count = computed(() => {
  const f = faults.value
  return f.dropouts.length + f.stuck.length + f.offline_nodes.length + f.no_flow.length + f.ignoring.length + Object.keys(f.weak).length
})
const isStuck = (device) => faults.value.stuck.find((s) => s.device === device)

async function send(command, done) {
  message.value = null
  try {
    await post('/sim', command)
    message.value = { ok: true, text: done }
  } catch (err) {
    message.value = { ok: false, text: err.message }
  }
}
function stick(device) {
  const quantity = stuck[device.id]?.quantity ?? device.values[0].quantity
  const value = Number(stuck[device.id]?.value)
  if (Number.isNaN(value)) { message.value = { ok: false, text: 'Give the value the sensor should repeat.' }; return }
  send({ name: 'sensor_stuck', device: device.id, quantity, value }, `${device.id} now always reports ${quantityLabel(quantity).toLowerCase()} ${value}.`)
}
const SPEEDS = [[1, 'real time'], [60, '1 min per second'], [600, '10 min per second'], [3600, '1 hour per second']]
</script>

<template>
  <h1>Simulator</h1>
  <p v-if="error" class="error">{{ error }}</p>
  <p v-if="sim && !sim.present" class="card">No simulator is running on this site: these are real nodes.</p>

  <template v-if="sim?.present">
    <p class="muted">This site is simulated. What you break here is what the hub sees; nothing real is switched.</p>
    <p v-if="message" class="result" :class="{ bad: !message.ok }" role="status">{{ message.text }}</p>

    <section class="card block" :inert="!session?.can_act">
      <h2>Time</h2>
      <p>Simulated time is <strong class="tnum">{{ clock(sim.now, site?.timezone, true) }}</strong>,
        {{ sim.paused ? 'paused' : `running at ${sim.speed}× real time` }}.</p>
      <div class="row">
        <button v-if="!sim.paused" type="button" @click="send({ name: 'pause' }, 'Paused.')">Pause</button>
        <button v-else type="button" class="primary" @click="send({ name: 'resume' }, 'Running again.')">Resume</button>
        <button v-for="[speed, label] in SPEEDS" :key="speed" type="button" :aria-pressed="sim.speed === speed"
                @click="send({ name: 'set_speed', speed }, `Speed set to ${label}.`)">{{ label }}</button>
      </div>
    </section>

    <section class="card block" :inert="!session?.can_act">
      <div class="row spread">
        <h2>Faults <span class="pill" :class="{ bad: count }">{{ count }} active</span></h2>
        <button type="button" :disabled="!count" @click="send({ name: 'clear_faults' }, 'All faults removed.')">Remove all faults</button>
      </div>
      <div v-for="node in nodes" :key="node.id" class="node">
        <div class="row spread">
          <h3>{{ node.id }}</h3>
          <button v-if="!faults.offline_nodes.includes(node.id)" type="button"
                  @click="send({ name: 'node_offline', node: node.id, active: true }, `${node.id} dropped off the network.`)">Take offline</button>
          <button v-else type="button" class="primary"
                  @click="send({ name: 'node_offline', node: node.id, active: false }, `${node.id} is back.`)">Bring back online</button>
        </div>
        <ul>
          <li v-for="device in node.devices.filter((d) => d.class !== 'indicator' && (d.class !== 'sensor' || d.zones.length))" :key="device.id">
            <span><strong>{{ device.id }}</strong> <span class="muted small">{{ sentence(device.roles[0].split('.')[1]) }}</span></span>
            <span v-if="device.class === 'sensor'" class="row">
              <button v-if="!faults.dropouts.includes(device.id)" type="button" class="small"
                      @click="send({ name: 'sensor_dropout', device: device.id, active: true }, `${device.id} stopped reporting.`)">Stop reporting</button>
              <button v-else type="button" class="small primary"
                      @click="send({ name: 'sensor_dropout', device: device.id, active: false }, `${device.id} reports again.`)">Report again</button>
              <template v-if="!isStuck(device.id)">
                <select v-model="(stuck[device.id] ??= { quantity: device.values[0].quantity, value: '' }).quantity" :aria-label="`Quantity of ${device.id} to freeze`">
                  <option v-for="v in device.values" :key="v.quantity" :value="v.quantity">{{ quantityLabel(v.quantity) }}</option>
                </select>
                <input v-model="stuck[device.id].value" type="number" step="any" placeholder="value" :aria-label="`Value ${device.id} should repeat`" />
                <button type="button" class="small" @click="stick(device)">Freeze at this value</button>
              </template>
              <button v-else type="button" class="small primary"
                      @click="send({ name: 'sensor_stuck', device: device.id, quantity: isStuck(device.id).quantity, value: null }, `${device.id} measures again.`)">
                Unfreeze ({{ isStuck(device.id).value }})
              </button>
              <template v-if="device.roles.includes('sensor.water_level')">
                <input v-model.number="reservoir[device.id]" type="number" min="0" max="100" placeholder="%" :aria-label="`Reservoir level for ${device.id} in percent`" />
                <button type="button" class="small" :disabled="reservoir[device.id] === undefined || reservoir[device.id] === ''"
                        @click="send({ name: 'set_reservoir', device: device.id, percent: reservoir[device.id] }, `Reservoir set to ${reservoir[device.id]} %.`)">Set level</button>
              </template>
            </span>
            <span v-else class="row">
              <button v-if="!faults.ignoring.includes(device.id)" type="button" class="small"
                      @click="send({ name: 'actuator_ignores', device: device.id, active: true }, `${device.id} no longer answers.`)">Stop answering</button>
              <button v-else type="button" class="small primary"
                      @click="send({ name: 'actuator_ignores', device: device.id, active: false }, `${device.id} answers again.`)">Answer again</button>
              <button v-if="!(device.id in faults.weak)" type="button" class="small"
                      @click="send({ name: 'actuator_weak', device: device.id, fraction: 0 }, `${device.id} runs but has no effect.`)">Run without effect</button>
              <button v-else type="button" class="small primary"
                      @click="send({ name: 'actuator_weak', device: device.id, fraction: null }, `${device.id} works again.`)">Restore effect</button>
            </span>
          </li>
        </ul>
      </div>
    </section>

    <section class="card block" :inert="!session?.can_act">
      <h2>Room</h2>
      <form class="row" @submit.prevent="send({ name: 'set_ambient', air_temperature: Number(ambient.air_temperature), relative_humidity: Number(ambient.relative_humidity) }, 'Room conditions changed.')">
        <label>Air temperature, °C <input v-model="ambient.air_temperature" type="number" step="0.5" /></label>
        <label>Humidity, % <input v-model="ambient.relative_humidity" type="number" min="0" max="100" /></label>
        <button type="submit">Apply</button>
      </form>
    </section>
    <p v-if="!session?.can_act" class="muted">Log in to change the simulation.</p>
  </template>
</template>

<style scoped>
.block { display: grid; gap: 0.75rem; }
.node { border-top: 1px solid var(--line); padding-top: 0.75rem; display: grid; gap: 0.5rem; }
h3 { font-size: 1rem; }
ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.5rem; }
li { display: grid; grid-template-columns: minmax(10rem, 16rem) 1fr; gap: 0.5rem 1rem; align-items: center; }
li input, li select { width: auto; max-width: 9rem; padding: 0.15rem 0.4rem; font-size: 0.85rem; }
label { display: grid; gap: 0.2rem; font-size: 0.85rem; color: var(--muted-text); }
form.row { align-items: end; }
form input { max-width: 8rem; }
button[aria-pressed='true'] { background: var(--track); font-weight: 600; }
.result { background: var(--band); border-radius: 0.5rem; padding: 0.5rem 0.75rem; }
.result.bad { background: var(--warn-surface); color: var(--warn-text); }
@media (max-width: 46rem) { li { grid-template-columns: 1fr; } }
</style>
