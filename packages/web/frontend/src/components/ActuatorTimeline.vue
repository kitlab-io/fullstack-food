<script setup>
// When each actuator was on, on the same time range as the charts above it.
import { computed } from 'vue'

import { sentence, span } from '../format.js'

const props = defineProps({ history: { type: Object, required: true } })   // response of /api/zones/<id>/actuators

const range = computed(() => {
  const from = Date.parse(props.history.from) / 1e3
  const to = Date.parse(props.history.to) / 1e3
  return { from, width: to - from }
})
const x = (t) => `${Math.min(100, Math.max(0, ((t - range.value.from) / range.value.width) * 100))}%`
const w = (a, b) => `${Math.max(0.15, ((b - a) / range.value.width) * 100)}%`
const role = (roles) => sentence(roles[0].split('.')[1])
</script>

<template>
  <div class="timeline">
    <div v-for="actuator in history.actuators" :key="actuator.id" class="row">
      <div class="who">
        <strong>{{ actuator.id }}</strong>
        <span>{{ role(actuator.roles) }} · on {{ span(actuator.on_s) }}<template v-if="actuator.doses.length"> · {{ actuator.doses.length }} dose{{ actuator.doses.length === 1 ? '' : 's' }}</template></span>
      </div>
      <div class="lane" role="img" :aria-label="`${actuator.id} was on ${actuator.intervals.length} times, ${span(actuator.on_s)} in total`">
        <span v-for="(run, i) in actuator.intervals" :key="i" class="run" :style="{ left: x(run[0]), width: w(run[0], run[1]) }"></span>
        <span v-for="dose in actuator.doses" :key="dose.t" class="dose" :style="{ left: x(dose.t) }"
              :title="`${dose.volume_ml} ml${dose.by === 'operator' ? ', by hand' : ''}`"></span>
      </div>
    </div>
    <p v-if="!history.actuators.length" class="empty">This zone has no actuators.</p>
  </div>
</template>

<style scoped>
.timeline { display: grid; gap: 0.75rem; }
.row { display: grid; grid-template-columns: minmax(8rem, 14rem) 1fr; gap: 0.75rem; align-items: center; }
.who { display: grid; }
.who span { color: var(--muted-text); font-size: 0.8rem; }
.lane { position: relative; height: 1.25rem; border-radius: 0.25rem; background: var(--track); overflow: hidden; }
.run { position: absolute; top: 0; bottom: 0; background: var(--accent); }
.dose { position: absolute; top: 0; bottom: 0; width: 3px; margin-left: -1px; background: var(--text); }
.empty { color: var(--muted-text); }
@media (max-width: 40rem) { .row { grid-template-columns: 1fr; gap: 0.25rem; } }
</style>
