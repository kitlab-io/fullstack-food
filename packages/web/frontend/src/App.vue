<script setup>
import { onMounted, ref, watch } from 'vue'

import { connection, loadSession, loadSite, logout, session, site } from './api.js'
import Login from './views/Login.vue'

const error = ref(null)
const wantsLogin = ref(false)

async function start() {
  error.value = null
  try {
    const who = await loadSession()
    if (who.can_read) await loadSite()
  } catch (err) {
    error.value = err.message
  }
}
onMounted(start)
watch(() => session.value?.can_read, (can) => { if (can && !site.value) start() })

async function leave() {
  await logout()
  wantsLogin.value = false
}
</script>

<template>
  <header class="top">
    <div class="inner">
      <RouterLink to="/" class="brand">
        <strong>{{ site?.name ?? 'Fullstack Food' }}</strong>
      </RouterLink>
      <nav v-if="session?.can_read" aria-label="Main">
        <RouterLink to="/">Zones</RouterLink>
        <RouterLink to="/devices">Devices</RouterLink>
        <RouterLink to="/log">Log</RouterLink>
        <RouterLink to="/raw">Raw data</RouterLink>
      </nav>
      <span v-if="session?.can_read" class="link" :class="{ down: !connection.live }" role="status">
        <span class="dot" aria-hidden="true"></span>{{ connection.live ? 'Live' : 'Reconnecting' }}
      </span>
      <span v-if="session?.authenticated" class="who">
        {{ session.name }} <button type="button" class="plain small" @click="leave">Log out</button>
      </span>
      <button v-else-if="session?.login_required && session.can_read" type="button" class="plain small" @click="wantsLogin = true">
        Log in to act
      </button>
    </div>
  </header>
  <main class="page">
    <p v-if="error" class="error">Could not reach the dashboard service: {{ error }}</p>
    <Login v-else-if="session && (!session.can_read || (wantsLogin && !session.authenticated))" @done="wantsLogin = false" />
    <RouterView v-else-if="site" @login="wantsLogin = true" />
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
nav a.router-link-exact-active { background: var(--track); color: var(--text); }
.link { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.85rem; color: var(--muted-text); }
.dot { width: 0.55rem; height: 0.55rem; border-radius: 50%; background: #2e9d62; }
.down .dot { background: var(--warn); }
.down { color: var(--warn-text); }
.who { font-size: 0.9rem; display: inline-flex; gap: 0.5rem; align-items: center; }
</style>
