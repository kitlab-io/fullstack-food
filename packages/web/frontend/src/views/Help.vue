<script setup>
// Troubleshooting: what a status means, what the hub is doing, what to check.
import { ref, watch } from 'vue'

import { get } from '../api.js'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps({ status: { type: String, default: null } })
const index = ref(null)
const entry = ref(null)
const error = ref(null)

async function load() {
  error.value = null
  entry.value = null
  try {
    if (props.status) entry.value = await get(`/help/${props.status}`)
    else index.value ??= await get('/help')
  } catch (err) {
    error.value = err.message
  }
}
watch(() => props.status, load, { immediate: true })
</script>

<template>
  <p v-if="error" class="error">Could not load this guide: {{ error }}</p>

  <template v-if="status && entry">
    <p><RouterLink to="/help">← All troubleshooting</RouterLink></p>
    <section class="card guide">
      <StatusBadge :status="entry.status" large />
      <p>{{ entry.meaning }}</p>
      <h2>What the hub is doing</h2>
      <p>{{ entry.doing }}</p>
      <h2>Likely causes, most likely first</h2>
      <ol><li v-for="cause in entry.causes" :key="cause">{{ cause }}</li></ol>
      <h2>What to check, in this order</h2>
      <ol><li v-for="check in entry.checks" :key="check">{{ check }}</li></ol>
      <h2>When it clears</h2>
      <p>{{ entry.clears }}</p>
    </section>
    <section v-for="symptom in entry.symptoms" :key="symptom.symptom" class="card guide">
      <h2>Does it look like this? {{ symptom.symptom }}</h2>
      <ol><li v-for="check in symptom.checks" :key="check">{{ check }}</li></ol>
    </section>
    <p class="small muted">Hardware advice here is from general experience and has not been confirmed on a bench.</p>
  </template>

  <template v-else-if="index">
    <h1>Troubleshooting</h1>
    <p class="muted">Start from what you see: the colour on the strip, the status on the dashboard, or what is going wrong.</p>
    <section class="card guide">
      <h2>By status</h2>
      <ul class="statuses">
        <li v-for="item in index.statuses" :key="item.status">
          <RouterLink :to="`/help/${item.status}`"><StatusBadge :status="item.status" /></RouterLink>
          <span class="muted">{{ item.meaning }}</span>
        </li>
      </ul>
    </section>
    <section class="card guide">
      <h2>By symptom</h2>
      <details v-for="symptom in index.symptoms" :key="symptom.symptom">
        <summary>{{ symptom.symptom }}</summary>
        <p class="muted">Likely causes</p>
        <ul><li v-for="cause in symptom.causes" :key="cause">{{ cause }}</li></ul>
        <p class="muted">What to check</p>
        <ol><li v-for="check in symptom.checks" :key="check">{{ check }}</li></ol>
        <p v-if="symptom.statuses.length" class="small">
          See also: <template v-for="s in symptom.statuses" :key="s"><RouterLink :to="`/help/${s}`">{{ s.replaceAll('_', ' ') }}</RouterLink>&nbsp; </template>
        </p>
      </details>
    </section>
  </template>
</template>

<style scoped>
.guide { display: grid; gap: 0.6rem; }
.guide h2 { margin-top: 0.5rem; }
ol, ul { margin: 0; padding-left: 1.4rem; display: grid; gap: 0.3rem; }
.statuses { list-style: none; padding: 0; gap: 0.75rem; }
.statuses li { display: grid; grid-template-columns: minmax(12rem, 16rem) 1fr; gap: 0.75rem; align-items: center; }
.statuses a { text-decoration: none; }
details { border-top: 1px solid var(--line); padding: 0.5rem 0; }
summary { cursor: pointer; font-weight: 600; }
@media (max-width: 40rem) { .statuses li { grid-template-columns: 1fr; gap: 0.2rem; } }
</style>
