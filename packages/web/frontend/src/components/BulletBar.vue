<script setup>
// One reading against its target band: shaded band, tick at the target, dot at the value.
import { computed } from 'vue'

import { ago, quantityLabel, reading } from '../format.js'

const props = defineProps({ item: { type: Object, required: true }, staleAfter: { type: Number, default: 600 } })

const scale = computed(() => {
  const { value, band } = props.item
  const points = [value, band?.min, band?.target, band?.max].filter((v) => v !== null && v !== undefined)
  if (!points.length) return null
  let lo = Math.min(...points)
  let hi = Math.max(...points)
  const pad = Math.max((hi - lo) * 0.35, Math.abs(hi) * 0.05, 1)
  lo -= pad
  hi += pad
  if (props.item.unit === 'percent') { lo = Math.max(0, lo); hi = Math.min(100, hi) }
  const pos = (v) => `${Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100))}%`
  return { pos }
})
const band = computed(() => {
  const b = props.item.band
  if (!b || !scale.value) return null
  return { left: b.min === undefined ? '0%' : scale.value.pos(b.min), right: b.max === undefined ? '100%' : scale.value.pos(b.max) }
})
const outside = computed(() => {
  const { value, band: b } = props.item
  if (value === null || !b) return false
  return (b.min !== undefined && value < b.min) || (b.max !== undefined && value > b.max)
})
const stale = computed(() => props.item.age_s === null || props.item.age_s > props.staleAfter)
const range = computed(() => {
  const b = props.item.band
  if (!b) return ''
  if (b.min !== undefined && b.max !== undefined) return `${b.min}–${b.max}`
  return b.min !== undefined ? `above ${b.min}` : `below ${b.max}`
})
</script>

<template>
  <div class="bullet" :class="{ outside, stale }">
    <div class="head">
      <span class="name">{{ quantityLabel(item.quantity) }}</span>
      <span class="value">{{ reading(item.value, item.quantity, item.unit) }}</span>
    </div>
    <div v-if="scale && item.band" class="track" role="img"
         :aria-label="`${quantityLabel(item.quantity)} ${reading(item.value, item.quantity, item.unit)}, target ${range}`">
      <span v-if="band" class="band" :style="{ left: band.left, width: `calc(${band.right} - ${band.left})` }"></span>
      <span v-if="item.band.target !== undefined" class="target" :style="{ left: scale.pos(item.band.target) }"></span>
      <span v-if="item.value !== null" class="dot" :style="{ left: scale.pos(item.value) }"></span>
    </div>
    <div class="foot">
      <span v-if="item.band">target {{ range }}<template v-if="item.band.overridden"> · overridden</template></span>
      <span v-else>&nbsp;</span>
      <span v-if="stale" class="warn">{{ item.age_s === null ? 'no reading yet' : `last reading ${ago(item.age_s)}` }}</span>
    </div>
  </div>
</template>

<style scoped>
.bullet { display: grid; gap: 0.2rem; }
.head { display: flex; justify-content: space-between; gap: 1rem; align-items: baseline; }
.name { color: var(--muted-text); }
.value { font-variant-numeric: tabular-nums; font-weight: 600; }
.outside .value { color: var(--warn-text); }
.stale .value { color: var(--muted-text); font-weight: 400; }
.track { position: relative; height: 0.5rem; border-radius: 0.25rem; background: var(--track); }
.band { position: absolute; top: 0; bottom: 0; border-radius: 0.25rem; background: var(--band); }
.target { position: absolute; top: -0.15rem; bottom: -0.15rem; width: 2px; margin-left: -1px; background: var(--muted-text); }
.dot {
  position: absolute; top: 50%; width: 0.8rem; height: 0.8rem; margin: -0.4rem 0 0 -0.4rem;
  border-radius: 50%; background: var(--accent); border: 2px solid var(--surface);
}
.outside .dot { background: var(--warn); }
.stale .dot { background: var(--muted); }
.foot { display: flex; justify-content: space-between; gap: 1rem; font-size: 0.8rem; color: var(--muted-text); }
.warn { color: var(--warn-text); }
</style>
