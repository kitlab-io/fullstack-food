<script setup>
import { onMounted, ref } from 'vue'

import { connection, loadSite, site } from './api.js'

const error = ref(null)
onMounted(() => loadSite().catch((err) => (error.value = err.message)))
</script>

<template>
  <header class="top">
    <div class="inner">
      <RouterLink to="/" class="brand">
        <strong>{{ site?.name ?? 'Fullstack Food' }}</strong>
      </RouterLink>
      <nav aria-label="Main">
        <RouterLink to="/">Zones</RouterLink>
        <RouterLink to="/devices">Devices</RouterLink>
      </nav>
      <span class="link" :class="{ down: !connection.live }" role="status">
        <span class="dot" aria-hidden="true"></span>{{ connection.live ? 'Live' : 'Reconnecting' }}
      </span>
    </div>
  </header>
  <main class="page">
    <p v-if="error" class="error">Could not load the site: {{ error }}</p>
    <RouterView v-else-if="site" />
    <p v-else class="muted">Loading…</p>
  </main>
</template>

<style scoped>
.top { background: var(--surface); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 10; }
.inner { max-width: 72rem; margin: 0 auto; padding: 0.6rem 1rem; display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem 1.25rem; }
.brand { text-decoration: none; margin-right: auto; min-width: 0; }
.brand strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60vw; }
nav { display: flex; gap: 0.25rem; }
nav a { text-decoration: none; padding: 0.3rem 0.7rem; border-radius: 0.5rem; color: var(--muted-text); }
nav a.router-link-exact-active, nav a.router-link-active[href='#/devices'] { background: var(--track); color: var(--text); }
.link { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.85rem; color: var(--muted-text); }
.dot { width: 0.55rem; height: 0.55rem; border-radius: 50%; background: #2e9d62; }
.down .dot { background: var(--warn); }
.down { color: var(--warn-text); }
</style>
