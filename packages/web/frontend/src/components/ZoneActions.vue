<script setup>
// What a person can do to a zone. Every button sends one command to the hub, which
// applies its own limits and interlocks and may refuse; its answer is shown as it is.
import { computed, reactive, ref } from 'vue'

import { act, session } from '../api.js'
import { quantityLabel, sentence, unit } from '../format.js'
import ConfirmDialog from './ConfirmDialog.vue'

const props = defineProps({ zone: { type: Object, required: true } })
const emit = defineEmits(['done', 'login'])

const result = ref(null)        // { ok, text }
const busy = ref(false)
const advanceDialog = ref(null)
const waterDialog = ref(null)
const pauseDialog = ref(null)
const overrideDialog = ref(null)
const modeDialog = ref(null)

const pause = reactive({ duration: '' })
const override = reactive({ quantity: '', target: null, min: null, max: null, duration: '4h' })

const advance = computed(() => props.zone.actions.advance)
const water = computed(() => props.zone.actions.water)
const bands = computed(() => props.zone.readings.filter((r) => r.band))
const chosenBand = computed(() => bands.value.find((r) => r.quantity === override.quantity))

async function send(command, done) {
  busy.value = true
  result.value = null
  try {
    const reply = await act(command)
    result.value = reply.ok ? { ok: true, text: done(reply.result) } : { ok: false, text: `The hub refused: ${reply.error}` }
    if (reply.ok) emit('done')
  } catch (err) {
    result.value = { ok: false, text: err.message }
  } finally {
    busy.value = false
  }
}

async function doAdvance() {
  if (!(await advanceDialog.value.ask())) return
  send({ name: 'advance_stage', planting: advance.value.planting },
    (r) => (r.stage ? `Moved to stage ${sentence(r.stage).toLowerCase()}.` : 'Planting finished; the zone is free.'))
}
async function doWater() {
  if (!(await waterDialog.value.ask())) return
  send({ name: 'water_now', zone: props.zone.id }, (r) => `Dosing ${r.volume_ml} ml with ${r.device} (${r.duration_s} s).`)
}
async function doPause() {
  pause.duration = ''
  if (!(await pauseDialog.value.ask())) return
  send({ name: 'pause_zone', zone: props.zone.id, duration: pause.duration || undefined },
    (r) => (r.until ? 'Paused; it resumes by itself.' : 'Paused until someone resumes it.'))
}
function doResume() {
  send({ name: 'resume_zone', zone: props.zone.id }, () => 'Resumed.')
}
async function doOverride() {
  const first = bands.value[0]
  Object.assign(override, { quantity: first.quantity, target: first.band.target ?? null, min: first.band.min ?? null, max: first.band.max ?? null, duration: '4h' })
  if (!(await overrideDialog.value.ask())) return
  const values = Object.fromEntries(['target', 'min', 'max'].filter((k) => override[k] !== null && override[k] !== '').map((k) => [k, Number(override[k])]))
  send({ name: 'set_override', zone: props.zone.id, quantity: override.quantity, duration: override.duration, ...values },
    () => `${quantityLabel(override.quantity)} overridden for ${override.duration}.`)
}
function pickQuantity() {
  const band = chosenBand.value.band
  Object.assign(override, { target: band.target ?? null, min: band.min ?? null, max: band.max ?? null })
}
function clearOverrides() {
  send({ name: 'clear_override', zone: props.zone.id }, () => 'Overrides cleared; the recipe targets apply again.')
}
async function doMode() {
  if (!(await modeDialog.value.ask())) return
  send({ name: 'set_zone_mode', zone: props.zone.id, mode: props.zone.observing ? 'active' : 'observe' },
    (r) => (r.mode === 'observe' ? 'Observe mode: nothing will be switched.' : 'Active: the hub is switching again.'))
}
</script>

<template>
  <section class="card actions" aria-label="Actions">
    <h2>Actions</h2>
    <p v-if="!session?.can_act" class="muted">
      Log in to act on this zone. <button type="button" class="link" @click="emit('login')">Log in</button>
    </p>
    <template v-else>
      <div class="row">
        <button v-if="advance" type="button" :class="{ primary: advance.to_stage }" :disabled="busy || !!advance.blocked" @click="doAdvance">
          {{ advance.to_stage ? `Advance to ${sentence(advance.to_stage).toLowerCase()}` : 'Finish planting' }}
        </button>
        <button v-if="water" type="button" :disabled="busy || zone.paused" @click="doWater">Water now</button>
        <button v-if="bands.length && zone.planting" type="button" :disabled="busy" @click="doOverride">Override a target</button>
        <button v-if="Object.keys(zone.overrides).length" type="button" :disabled="busy" @click="clearOverrides">Clear overrides</button>
        <button v-if="!zone.paused" type="button" :disabled="busy" @click="doPause">Pause zone</button>
        <button v-else type="button" :disabled="busy" @click="doResume">Resume zone</button>
        <button type="button" :disabled="busy" @click="doMode">{{ zone.observing ? 'Switch to active' : 'Switch to observe' }}</button>
      </div>
      <p v-if="advance?.blocked" class="small muted">Cannot advance yet: {{ advance.blocked }}.</p>
      <p v-if="result" class="result" :class="{ bad: !result.ok }" role="status">{{ result.text }}</p>
    </template>

    <ConfirmDialog v-if="advance" ref="advanceDialog" :title="advance.to_stage ? 'Advance stage' : 'Finish planting'"
                   :confirm-label="advance.to_stage ? 'Advance' : 'Finish'">
      <p v-if="advance.to_stage">
        <strong>{{ zone.planting?.species ?? advance.planting }}</strong> goes from
        {{ sentence(zone.planting?.stage).toLowerCase() }} to <strong>{{ sentence(advance.to_stage).toLowerCase() }}</strong><template
          v-if="advance.to_zone !== zone.id"> and moves to <strong>{{ advance.to_zone }}</strong>. Carry it there first: this zone
          stops being controlled for it</template>.
      </p>
      <p v-else>The planting ends and <strong>{{ zone.id }}</strong> is freed. Its actuators are switched off.</p>
      <p v-if="zone.planting?.hint" class="muted">Check first: {{ zone.planting.hint }}.</p>
      <p v-if="zone.planting && !zone.planting.ready && zone.planting.due_in_s > 0" class="muted">This stage is not due yet.</p>
    </ConfirmDialog>

    <ConfirmDialog v-if="water" ref="waterDialog" title="Water now" confirm-label="Water">
      <p>Give <strong>{{ zone.id }}</strong> one dose of {{ water.volume_ml }} ml now, without waiting for the soil to dry.</p>
      <p class="muted">The reservoir check and the daily limit still apply, and the dose counts towards them.</p>
    </ConfirmDialog>

    <ConfirmDialog ref="pauseDialog" title="Pause zone" confirm-label="Pause">
      <p>Every actuator in <strong>{{ zone.id }}</strong> is switched off and stays off.</p>
      <label>Resume
        <select v-model="pause.duration">
          <option value="">when someone resumes it</option>
          <option value="30m">after 30 minutes</option><option value="2h">after 2 hours</option><option value="12h">after 12 hours</option>
        </select>
      </label>
    </ConfirmDialog>

    <ConfirmDialog ref="overrideDialog" title="Override a target" confirm-label="Override">
      <label>Quantity
        <select v-model="override.quantity" @change="pickQuantity">
          <option v-for="r in bands" :key="r.quantity" :value="r.quantity">{{ quantityLabel(r.quantity) }}</option>
        </select>
      </label>
      <div class="three">
        <label>Minimum <input v-model="override.min" type="number" step="any" /></label>
        <label>Target <input v-model="override.target" type="number" step="any" /></label>
        <label>Maximum <input v-model="override.max" type="number" step="any" /></label>
      </div>
      <label>For
        <select v-model="override.duration">
          <option value="1h">1 hour</option><option value="4h">4 hours</option><option value="1d">1 day</option><option value="3d">3 days</option>
        </select>
      </label>
      <p class="muted small">In {{ unit(chosenBand?.unit) }}. Empty fields keep the recipe's value. The override ends by itself, and when the stage advances.</p>
    </ConfirmDialog>

    <ConfirmDialog ref="modeDialog" :title="zone.observing ? 'Switch to active' : 'Switch to observe'" confirm-label="Switch">
      <p v-if="zone.observing">The hub starts switching the actuators of <strong>{{ zone.id }}</strong> for real.</p>
      <p v-else>Every actuator in <strong>{{ zone.id }}</strong> is switched off. The hub keeps deciding and logging what it would do, but sends nothing.</p>
    </ConfirmDialog>
  </section>
</template>

<style scoped>
.actions { display: grid; gap: 0.75rem; }
.result { background: var(--band); border-radius: 0.5rem; padding: 0.5rem 0.75rem; }
.result.bad { background: var(--warn-surface); color: var(--warn-text); }
.three { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; }
label { display: grid; gap: 0.2rem; font-size: 0.85rem; color: var(--muted-text); }
.link { border: 0; background: none; text-decoration: underline; cursor: pointer; padding: 0; }
</style>
