<script setup>
import { ref } from 'vue'

import { get, useLive } from '../api.js'
import BulletBar from '../components/BulletBar.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { ago, sentence, span, statusLabel } from '../format.js'
import { NEEDS_PERSON, statusStyle } from '../status.js'

const zones = ref([])
const { error, loading } = useLive(async () => { zones.value = (await get('/zones')).zones })

const banners = (zone) => zone.active.filter((s) => s in NEEDS_PERSON)
const others = (zone) => zone.active.filter((s) => s !== zone.status)
const offline = (zone) => zone.nodes.filter((n) => n.online === false)

function progress(planting) {
  const days = planting.typical_days ? ` of about ${planting.typical_days}` : ''
  return `day ${planting.day}${days}`
}
function due(planting) {
  if (planting.due_in_s === null) return null
  if (planting.ready) return planting.hint ? `Check: ${planting.hint}` : 'Ready when you are'
  return planting.due_in_s > 0 ? `stage due in ${span(planting.due_in_s)}` : 'stage due'
}
</script>

<template>
  <p v-if="error" class="error">Could not load the zones: {{ error }}</p>
  <p v-else-if="loading" class="muted">Loading…</p>
  <section class="grid" aria-label="Zones">
    <article v-for="zone in zones" :key="zone.id" class="card zone" :style="{ '--status': statusStyle(zone.status).color }">
      <header class="row spread">
        <div>
          <h2><RouterLink :to="`/zones/${zone.id}`">{{ zone.name }}</RouterLink></h2>
          <p class="muted small">{{ sentence(zone.kind) }}<template v-if="zone.role"> · {{ zone.role }}</template></p>
        </div>
        <StatusBadge :status="zone.status" />
      </header>

      <p v-for="status in banners(zone)" :key="status" class="banner">
        <strong>{{ statusLabel(status) }}.</strong> {{ NEEDS_PERSON[status] }}
      </p>
      <p v-if="others(zone).length" class="small muted">
        Also: {{ others(zone).map(statusLabel).join(', ') }}
      </p>

      <p v-if="zone.planting" class="planting">
        <strong>{{ zone.planting.species ?? zone.planting.id }}</strong>
        <span class="muted"> · {{ sentence(zone.planting.stage) }} · {{ progress(zone.planting) }}</span>
        <span v-if="due(zone.planting)" class="small muted due">{{ due(zone.planting) }}</span>
      </p>
      <p v-else class="muted">Nothing planted here.</p>

      <div class="readings">
        <BulletBar v-for="item in zone.readings" :key="item.device + item.quantity" :item="item" />
      </div>

      <footer class="row small muted">
        <span v-for="node in zone.nodes" :key="node.id" class="pill" :class="{ bad: node.online === false, good: node.online }">
          {{ node.id }} {{ node.online === false ? 'offline' : node.online ? 'online' : 'not seen' }}
        </span>
        <span v-if="!offline(zone).length">last reading {{ ago(zone.last_reading_age_s) }}</span>
        <RouterLink :to="`/zones/${zone.id}`" class="more">Charts and details</RouterLink>
      </footer>
    </article>
  </section>
</template>

<style scoped>
.grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(min(100%, 22rem), 1fr)); align-items: start; }
.zone { display: grid; gap: 0.85rem; border-top: 0.35rem solid var(--status); }
h2 a { text-decoration: none; }
h2 a:hover { text-decoration: underline; }
.banner { background: var(--warn-surface); color: var(--warn-text); border-radius: 0.5rem; padding: 0.5rem 0.75rem; font-size: 0.9rem; }
.due { display: block; }
.readings { display: grid; gap: 0.75rem; }
footer .more { margin-left: auto; }
</style>
