<template>
  <div class="app-container">
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
      <div class="container">
        <a class="navbar-brand" href="#">IoT Plant Manager</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
          <ul class="navbar-nav ms-auto">
            <li class="nav-item">
              <router-link class="nav-link" to="/">Sensor Data</router-link>
            </li>
            <li class="nav-item">
              <router-link class="nav-link" to="/books">Books</router-link>
            </li>
            <li class="nav-item">
              <router-link class="nav-link" to="/ping">API Status</router-link>
            </li>
          </ul>
        </div>
      </div>
    </nav>

    <main class="container mt-4">
      <RouterView />
    </main>

    <footer class="footer mt-5 py-3 bg-light">
      <div class="container text-center">
        <span class="text-muted">IoT Plant Manager Dashboard © 2025</span>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { RouterView } from 'vue-router'
</script>

<style>
body {
  background-color: #f8f9fa;
  min-height: 100vh;
}

.app-container {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

main {
  flex: 1;
}

.footer {
  margin-top: auto;
}
</style>