<script setup>
// One quantity over time: mean line, min/max envelope when the data is rolled up, the
// target band shaded behind it, and a vertical line where each stage began.
import uPlot from 'uplot'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { number, quantityLabel, unit } from '../format.js'

const props = defineProps({
  series: { type: Object, required: true },      // response of /api/zones/<id>/series
  band: { type: Object, default: null },         // { min, target, max }
  marks: { type: Array, default: () => [] },     // [{ t: epoch seconds, label }]
  timeZone: { type: String, default: 'UTC' },
})

const host = ref(null)
let plot = null
let observer = null

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

// Tick labels in the site's timezone and 24-hour time, like the rest of the page.
function timeTicks(u, ticks) {
  const step = ticks.length > 1 ? ticks[1] - ticks[0] : 3600
  const options = step >= 86400
    ? { day: 'numeric', month: 'short' }
    : { hour: '2-digit', minute: '2-digit', hour12: false }
  let format
  try { format = new Intl.DateTimeFormat(undefined, { ...options, timeZone: props.timeZone }) } catch { format = new Intl.DateTimeFormat(undefined, options) }
  const day = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', timeZone: format.resolvedOptions().timeZone })
  let lastDay = null
  return ticks.map((t) => {
    const date = new Date(t * 1e3)
    const label = format.format(date)
    if (step >= 86400) return label
    const today = day.format(date)
    const show = today !== lastDay          // name the day under the first tick of each day
    lastDay = today
    return show ? `${label}\n${today}` : label
  })
}

function draw() {
  plot?.destroy()
  plot = null
  const s = props.series
  if (!host.value || !s.t.length) return
  const rolled = Array.isArray(s.min)
  const data = rolled ? [s.t, s.mean, s.max, s.min] : [s.t, s.mean]
  const accent = css('--accent')
  const grid = { stroke: css('--line'), width: 1 }
  const axis = { stroke: css('--muted-text'), grid, ticks: grid, font: '12px system-ui, sans-serif' }
  const band = props.band
  let tz
  try { tz = (ts) => uPlot.tzDate(new Date(ts * 1e3), props.timeZone) } catch { tz = undefined }

  plot = new uPlot({
    width: host.value.clientWidth,
    height: 220,
    tzDate: tz,
    cursor: { y: false },
    legend: { live: true },
    scales: {
      x: { time: true, range: [Date.parse(s.from) / 1e3, Date.parse(s.to) / 1e3] },
      y: {
        range: (u, lo, hi) => {      // always show the whole target band
          const points = [lo, hi, band?.min, band?.max].filter((v) => v !== null && v !== undefined)
          const low = Math.min(...points)
          const high = Math.max(...points)
          const pad = Math.max((high - low) * 0.12, 0.5)
          return [low - pad, high + pad]
        },
      },
    },
    axes: [{ ...axis, values: timeTicks }, { ...axis, size: 52, values: (u, ticks) => ticks.map((v) => number(v, s.quantity)) }],
    series: [
      {},
      { label: quantityLabel(s.quantity), stroke: accent, width: 2, points: { show: false },
        value: (u, v) => (v === null ? '–' : `${number(v, s.quantity)} ${unit(s.unit)}`) },
      ...(rolled ? [
        { label: 'max', stroke: 'transparent', points: { show: false }, value: (u, v) => (v === null ? '–' : number(v, s.quantity)) },
        { label: 'min', stroke: 'transparent', points: { show: false }, value: (u, v) => (v === null ? '–' : number(v, s.quantity)) },
      ] : []),
    ],
    bands: rolled ? [{ series: [2, 3], fill: css('--envelope') }] : [],
    hooks: {
      drawClear: [(u) => {
        if (!band) return
        const { ctx, bbox } = u
        const top = band.max === undefined ? bbox.top : Math.max(bbox.top, u.valToPos(band.max, 'y', true))
        const bottom = band.min === undefined ? bbox.top + bbox.height : Math.min(bbox.top + bbox.height, u.valToPos(band.min, 'y', true))
        ctx.save()
        ctx.fillStyle = css('--band')
        ctx.fillRect(bbox.left, top, bbox.width, Math.max(0, bottom - top))
        if (band.target !== undefined) {
          const y = u.valToPos(band.target, 'y', true)
          ctx.strokeStyle = css('--muted-text')
          ctx.setLineDash([4, 4])
          ctx.beginPath(); ctx.moveTo(bbox.left, y); ctx.lineTo(bbox.left + bbox.width, y); ctx.stroke()
        }
        ctx.restore()
      }],
      draw: [(u) => {
        const { ctx, bbox } = u
        ctx.save()
        ctx.strokeStyle = css('--muted-text')
        ctx.fillStyle = css('--muted-text')
        ctx.font = '11px system-ui, sans-serif'
        for (const mark of props.marks) {
          const x = u.valToPos(mark.t, 'x', true)
          if (x < bbox.left || x > bbox.left + bbox.width) continue
          ctx.beginPath(); ctx.moveTo(x, bbox.top); ctx.lineTo(x, bbox.top + bbox.height); ctx.stroke()
          ctx.fillText(mark.label, x + 4 * devicePixelRatio, bbox.top + 12 * devicePixelRatio)
        }
        ctx.restore()
      }],
    },
  }, data, host.value)
}

onMounted(() => {
  draw()
  observer = new ResizeObserver(() => plot?.setSize({ width: host.value.clientWidth, height: 220 }))
  observer.observe(host.value)
})
onBeforeUnmount(() => { observer?.disconnect(); plot?.destroy() })
watch(() => [props.series, props.band, props.marks], draw)
</script>

<template>
  <figure class="chart">
    <figcaption>
      <strong>{{ quantityLabel(series.quantity) }}</strong>
      <span class="hint">{{ series.device }} · {{ series.resolution === 'raw' ? 'every sample' : `${series.resolution} averages with min and max` }}</span>
    </figcaption>
    <div ref="host" class="plot"></div>
    <p v-if="!series.t.length" class="empty">No readings in this range yet.</p>
  </figure>
</template>

<style scoped>
.chart { margin: 0; }
figcaption { display: flex; flex-wrap: wrap; gap: 0.25rem 0.75rem; align-items: baseline; margin-bottom: 0.25rem; }
.hint { color: var(--muted-text); font-size: 0.8rem; }
.plot { min-height: 0; }
.empty { color: var(--muted-text); padding: 2rem 0; text-align: center; }
</style>
