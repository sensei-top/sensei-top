import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // The build lands inside the Python package so the wheel carries it;
  // emptyOutDir is explicit because the folder is outside Vite's root.
  build: {
    outDir: '../src/sensei_top/web_dist',
    emptyOutDir: true,
  },
  server: {
    // Fixed addresses, both sides: the API is always :8000 and the dev server
    // always :5173. strictPort makes Vite fail loudly instead of hopping to
    // 5174 and silently changing the URL.
    port: 5173,
    strictPort: true,
    // Proxy rather than CORS: the dashboard and the API stay same-origin in
    // development, exactly as they are in production where FastAPI serves
    // web_dist/ itself. Nothing here is reachable off the loopback interface.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
