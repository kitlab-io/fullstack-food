<script setup>
// Shown only when the dashboard is over a finished scenario run: what was done to the
// simulated site and whether what the scenario expected held.
import { computed } from 'vue'

import { scenario, site } from '../api.js'
import { clock } from '../format.js'

const failed = computed(() => (scenario.value?.expectations ?? []).filter((e) => !e.ok).length)
const tz = computed(() => site.value?.timezone)
</script>

<template>
  <h1>Scenario</h1>
  <p v-if="!scenario" class="card pad">This is a live site, not a scenario run.</p>
  <template v-else>
    <section class="card pad">
      <div class="row spread">
        <h2>{{ scenario.title }}</h2>
        <span class="pill" :class="{ bad: !scenario.passed }">{{ scenario.passed ? 'Passed' : 'Failed' }}</span>
      </div>
      <p class="muted">
        Simulated from <span class="tnum">{{ clock(scenario.start, tz, true) }}</span> to
        <span class="tnum">{{ clock(scenario.end, tz, true) }}</span>. The run is finished: every other page shows
        its last moment and its history, and nothing can be switched.
      </p>
      <p class="note">{{ scenario.note }}</p>
    </section>

    <section class="card">
      <h2 class="pad">What happened</h2>
      <p v-if="!scenario.timeline.length" class="muted pad">Nothing was done to the site; it ran undisturbed.</p>
      <ol class="rows">
        <li v-for="(entry, n) in scenario.timeline" :key="n" :class="{ bad: !entry.ok }">
          <span class="when tnum">{{ entry.at }}</span>
          <span class="mark" aria-hidden="true">{{ entry.ok ? '•' : '✕' }}</span>
          <span>
            <span class="text">{{ entry.text }}</span>
            <span v-if="entry.note" class="muted"> · {{ entry.note }}</span>
            <span v-if="entry.detail" class="detail">{{ entry.ok ? 'Answer' : 'Failed' }}: {{ entry.detail }}</span>
          </span>
          <time class="muted small tnum">{{ clock(entry.t, tz, true) }}</time>
        </li>
      </ol>
    </section>

    <section class="card">
      <h2 class="pad">What was expected
        <span class="muted small">{{ scenario.expectations.length - failed }} of {{ scenario.expectations.length }} held</span>
      </h2>
      <ol class="rows">
        <li v-for="(check, n) in scenario.expectations" :key="n" :class="{ bad: !check.ok }">
          <span class="when">{{ check.ok ? 'Held' : 'Failed' }}</span>
          <span class="mark" aria-hidden="true">{{ check.ok ? '✓' : '✕' }}</span>
          <span>
            <span class="text">{{ check.text }}</span>
            <span v-if="check.detail" class="detail">{{ check.ok ? 'Seen' : 'Instead' }}: {{ check.detail }}</span>
          </span>
        </li>
      </ol>
    </section>
  </template>
</template>

<style scoped>
.pad { padding: 1rem; }
h2.pad { padding-bottom: 0.25rem; display: flex; gap: 0.75rem; align-items: baseline; flex-wrap: wrap; }
.note { margin-top: 0.75rem; padding: 0.6rem 0.8rem; border-radius: 0.5rem; background: var(--track); font-size: 0.9rem; }
.rows { list-style: none; margin: 0; padding: 0.25rem 0; }
.rows li { display: grid; grid-template-columns: 5.5rem 1rem 1fr auto; gap: 0.75rem; align-items: baseline; padding: 0.45rem 1rem; }
.rows li + li { border-top: 1px solid var(--line); }
.when { color: var(--muted-text); font-size: 0.85rem; }
.text { overflow-wrap: anywhere; }
.detail { display: block; color: var(--muted-text); font-size: 0.85rem; }
.bad .text, .bad .when, .bad .mark, .bad .detail { color: var(--warn-text); }
@media (max-width: 46rem) {
  .rows li { grid-template-columns: auto 1rem 1fr; }
  .rows time { grid-column: 1 / -1; }
}
</style>
