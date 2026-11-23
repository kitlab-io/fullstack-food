import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// `npm run dev` serves the frontend on :5173 and forwards API calls to a running
// `python -m fsf_web` on :8080. `npm run build` writes dist/, which that service serves.
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8080' },
  },
})
