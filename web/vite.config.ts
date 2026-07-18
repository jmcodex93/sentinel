import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
//
// The build output is the committed artifact plugin/web/ — Sentinel
// artists don't have Node, so `npm run build` here must be run (and its
// output synced) before the plugin ships. See web/README.md.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../plugin/web',
    emptyOutDir: true,
  },
})
