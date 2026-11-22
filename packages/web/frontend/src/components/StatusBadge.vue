<script setup>
import { computed } from 'vue'

import { statusLabel } from '../format.js'
import { iconPath, statusStyle } from '../status.js'

const props = defineProps({ status: { type: String, required: true }, large: Boolean })
const style = computed(() => statusStyle(props.status))
</script>

<template>
  <span class="badge" :class="{ large }">
    <span class="lamp" :class="`fx-${style.effect}`" :style="{ '--lamp': style.color }" aria-hidden="true">
      <svg viewBox="0 0 24 24"><path :d="iconPath(status)" /></svg>
    </span>
    <span class="label">{{ statusLabel(status) }}</span>
  </span>
</template>

<style scoped>
.badge { display: inline-flex; align-items: center; gap: 0.5rem; font-weight: 600; }
.lamp {
  display: grid; place-items: center; width: 1.75rem; height: 1.75rem; flex: none;
  border-radius: 50%; background: color-mix(in srgb, var(--lamp) 22%, var(--surface));
  border: 2px solid var(--lamp); color: var(--text);
}
.lamp svg { width: 1rem; height: 1rem; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.large .lamp { width: 2.5rem; height: 2.5rem; }
.large .lamp svg { width: 1.4rem; height: 1.4rem; }
.large .label { font-size: 1.25rem; }
/* The same effects the LED segment shows. */
.fx-breathe { animation: breathe 4s ease-in-out infinite; }
.fx-blink { animation: blink 1s steps(1) infinite; }
.fx-blink_slow { animation: blink 3s steps(1) infinite; }
.fx-off { border-style: dashed; }
@keyframes breathe { 50% { box-shadow: 0 0 0 5px color-mix(in srgb, var(--lamp) 35%, transparent); } }
@keyframes blink { 50% { background: var(--surface); border-color: color-mix(in srgb, var(--lamp) 35%, var(--surface)); } }
@media (prefers-reduced-motion: reduce) { .lamp { animation: none; } }
</style>
