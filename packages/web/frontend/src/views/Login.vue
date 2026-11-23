<script setup>
import { ref } from 'vue'

import { login, session } from '../api.js'

const emit = defineEmits(['done'])
const name = ref(localStorage.getItem('fsf-name') ?? '')
const password = ref('')
const error = ref(null)
const busy = ref(false)

async function submit() {
  busy.value = true
  error.value = null
  try {
    await login(password.value, name.value)
    localStorage.setItem('fsf-name', name.value)
    emit('done')
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
    password.value = ''
  }
}
</script>

<template>
  <form class="card login" @submit.prevent="submit">
    <h1>Log in</h1>
    <p v-if="session && !session.password_configured" class="error">
      No password is configured on this dashboard, so nobody can log in. Set <code>FSF_WEB_PASSWORD_HASH</code>
      (make one with <code>python -m fsf_web hash-password</code>) and restart it.
    </p>
    <label>Your name <span class="muted">(shown in the log next to what you do)</span>
      <input v-model="name" type="text" autocomplete="nickname" maxlength="40" />
    </label>
    <label>Password
      <input v-model="password" type="password" autocomplete="current-password" required />
    </label>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <button type="submit" class="primary" :disabled="busy">Log in</button>
    <p class="small muted">One password is shared by everyone who looks after this site.</p>
  </form>
</template>

<style scoped>
.login { display: grid; gap: 1rem; max-width: 24rem; margin: 2rem auto; }
label { display: grid; gap: 0.25rem; }
</style>
