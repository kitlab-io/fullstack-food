<script setup>
import { computed, ref, watch } from 'vue'

import { get, site, useLive } from '../api.js'
import ActuatorTimeline from '../components/ActuatorTimeline.vue'
import BulletBar from '../components/BulletBar.vue'
import SeriesChart from '../components/SeriesChart.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { ago, clock, sentence, span, statusLabel } from '../format.js'
import { ledColor } from '../status.js'

const props = defineProps({ id: { type: String, required: true } })

const RANGES = [
  { key: '6h', label: '6 hours', seconds: 6 * 3600 },
  { key: '24h', label: '24 hours', seconds: 24 * 3600 },
  { key: '7d', label: '7 days', seconds: 7 * 86400 },
  { key: 'grow', label: 'Whole grow', seconds: null },
]
const range = ref('24h')
const zone = ref(null)
const charts = ref([])
const history = ref(null)

async function load() {
  const view = await get(`/zones/${props.id}`)
  const now = Date.parse(view.now)
  const chosen = RANGES.find((r) => r.key === range.value)
  const started = view.stage_history[0] ? Date.parse(view.stage_history[0].t) : now - 7 * 86400e3
  const from = new Date(chosen.seconds ? now - chosen.seconds * 1e3 : started).toISOString()
  const window = { from, to: view.now }
  const quantities = [...new Set(view.readings.map((r) => r.quantity))]
  const [series, actuators] = await Promise.all([
    Promise.all(quantities.map((quantity) => get(`/zones/${props.id}/series`, { quantity, ...window }))),
    get(`/zones/${props.id}/actuators`, window),
  ])
  zone.value = view
  charts.value = series
  history.value = actuators
}
const { error, loading, refresh } = useLive(load, {
  every: 5000,
  wants: (event) => event.kind !== 'device' || zone.value?.readings.some((r) => r.device === event.device),
})
watch(() => [props.id, range.value], refresh)

const tz = computed(() => site.value?.timezone)
const bandOf = (quantity) => zone.value.readings.find((r) => r.quantity === quantity)?.band ?? null
const marks = computed(() => zone.value.stage_history
  .filter((e) => e.planting === zone.value.planting?.id)
  .map((e) => ({ t: Date.parse(e.t) / 1e3, label: sentence(e.stage ?? 'start') })))
const others = computed(() => zone.value.active.filter((s) => s !== zone.value.status))
const led = computed(() => zone.value.led)
</script>

<template>
  <p><RouterLink to="/">← All zones</RouterLink></p>
  <p v-if="error" class="error">Could not load this zone: {{ error }}</p>
  <p v-else-if="loading && !zone" class="muted">Loading…</p>

  <template v-if="zone">
    <section class="card head">
      <div class="row spread">
        <div>
          <h1>{{ zone.name }}</h1>
          <p class="muted">{{ sentence(zone.kind) }}<template v-if="zone.role"> · {{ zone.role }}</template></p>
        </div>
        <StatusBadge :status="zone.status" large />
      </div>
      <p v-if="others.length" class="muted">Also: {{ others.map(statusLabel).join(', ') }}</p>
      <p v-if="zone.observing" class="banner">
        Observe mode ({{ zone.observing }}): decisions below are what the hub would do; nothing is switched.
      </p>
      <p v-if="zone.paused" class="banner">
        Paused{{ zone.paused_until ? ` until ${clock(zone.paused_until, tz, true)}` : ' until someone resumes it' }}: every actuator is off.
      </p>

      <div v-if="zone.planting" class="planting">
        <p>
          <strong>{{ zone.planting.species ?? zone.planting.id }}</strong>
          <span class="muted"> · {{ zone.planting.recipe }} · day {{ zone.planting.day }} of this stage</span>
        </p>
        <ol class="stages" aria-label="Stages">
          <li v-for="(stage, i) in zone.planting.stages" :key="stage"
              :class="{ done: i < zone.planting.stage_index, current: i === zone.planting.stage_index }"
              :aria-current="i === zone.planting.stage_index ? 'step' : undefined">
            {{ sentence(stage) }}
          </li>
        </ol>
        <p v-if="zone.planting.ready" class="banner">
          <strong>Ready for the next stage.</strong>
          <template v-if="zone.planting.hint"> Check first: {{ zone.planting.hint }}.</template>
        </p>
        <p v-else-if="zone.planting.due_in_s !== null" class="muted small">
          This stage typically lasts about {{ zone.planting.typical_days }} days:
          {{ zone.planting.due_in_s > 0 ? `${span(zone.planting.due_in_s)} to go` : 'it is due' }}.
        </p>
      </div>
      <p v-else class="muted">Nothing planted here.</p>
    </section>

    <section class="card">
      <h2>Now</h2>
      <div class="now">
        <BulletBar v-for="item in zone.readings" :key="item.device + item.quantity" :item="item" />
      </div>
      <p class="small muted">Last reading {{ ago(zone.last_reading_age_s) }}.</p>
    </section>

    <section class="card">
      <div class="row spread">
        <h2>History</h2>
        <div class="ranges" role="group" aria-label="Time range">
          <button v-for="r in RANGES" :key="r.key" type="button" :aria-pressed="range === r.key" @click="range = r.key">{{ r.label }}</button>
        </div>
      </div>
      <div class="charts">
        <SeriesChart v-for="series in charts" :key="series.quantity" :series="series" :band="bandOf(series.quantity)"
                     :marks="marks" :time-zone="tz" />
      </div>
      <h3 class="sub">Actuators</h3>
      <ActuatorTimeline v-if="history" :history="history" />
      <p class="small muted">Bars show when the hub held each actuator on; dark ticks are doses. Rebuilt from the commands the hub sent, kept for 14 days.</p>
    </section>

    <section class="card">
      <h2>Why it is doing what it is doing</h2>
      <p v-if="!zone.decisions.length" class="muted">No control loop has run here in the last two days.</p>
      <ul class="why">
        <li v-for="d in zone.decisions" :key="d.loop + d.device">
          <span class="pill" :class="{ good: d.action === 'on' }">{{ d.action }}</span>
          <div>
            <p><strong>{{ sentence(d.loop) }}</strong> <span class="muted">({{ d.device }})</span>: {{ d.reason }}</p>
            <p class="small muted">
              since {{ clock(d.t, tz, true) }}
              <template v-if="d.inputs.quantity"> · {{ d.inputs.quantity }} was {{ d.inputs.value ?? 'not available' }}</template>
              <template v-if="d.inputs.target !== undefined"> · target {{ d.inputs.target }}</template>
              <template v-if="d.want && d.action === 'off'"> · wants on but is held off</template>
              <template v-if="d.inputs.observed"> · observe mode: not carried out</template>
            </p>
          </div>
        </li>
      </ul>
    </section>

    <section v-if="led" class="card">
      <h2>Status light</h2>
      <div class="row">
        <span class="strip" :class="`fx-${led.effect}`" :style="{ '--lamp': ledColor(led.color) }" aria-hidden="true"></span>
        <span>LEDs {{ led.leds[0] }}–{{ led.leds[1] }} show <strong>{{ statusLabel(led.status) }}</strong> ({{ led.effect.replace('_', ' ') }}).</span>
      </div>
    </section>
  </template>
</template>

<style scoped>
.head, .planting { display: grid; gap: 0.75rem; }
.banner { background: var(--warn-surface); color: var(--warn-text); border-radius: 0.5rem; padding: 0.5rem 0.75rem; }
.stages { display: flex; flex-wrap: wrap; gap: 0.4rem; list-style: none; margin: 0; padding: 0; }
.stages li { padding: 0.2rem 0.75rem; border-radius: 1rem; border: 1px solid var(--line); color: var(--muted-text); font-size: 0.9rem; }
.stages li.done { background: var(--track); }
.stages li.current { border-color: var(--accent); color: var(--text); font-weight: 600; }
.card { display: grid; gap: 0.85rem; }
.now { display: grid; gap: 1rem 2rem; grid-template-columns: repeat(auto-fill, minmax(min(100%, 18rem), 1fr)); }
.ranges { display: inline-flex; border: 1px solid var(--line); border-radius: 0.5rem; overflow: hidden; }
.ranges button { border: 0; background: none; padding: 0.3rem 0.7rem; cursor: pointer; font-size: 0.9rem; }
.ranges button + button { border-left: 1px solid var(--line); }
.ranges button[aria-pressed='true'] { background: var(--track); font-weight: 600; }
.charts { display: grid; gap: 1.5rem; min-width: 0; }
.charts > * { min-width: 0; }
.sub { font-size: 0.95rem; margin-top: 0.5rem; }
.why { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.75rem; }
.why li { display: grid; grid-template-columns: 2.5rem 1fr; gap: 0.75rem; align-items: start; }
.why .pill { text-align: center; }
.strip { width: 6rem; height: 0.9rem; border-radius: 0.45rem; background: var(--lamp); border: 1px solid var(--line); }
.strip.fx-breathe { animation: fade 4s ease-in-out infinite; }
.strip.fx-blink { animation: flash 1s steps(1) infinite; }
.strip.fx-blink_slow { animation: flash 3s steps(1) infinite; }
@keyframes fade { 50% { opacity: 0.25; } }
@keyframes flash { 50% { opacity: 0.1; } }
@media (prefers-reduced-motion: reduce) { .strip { animation: none; } }
</style>
