import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import prefixer from 'postcss-prefix-selector'
import { defineConfig } from 'vite'

// SportLens shell. Sport UIs are imported from their own source trees (single source of truth):
//   @futsal -> ../frontend/src      @padel -> ../padel/web/src
// Each sport's global stylesheet is namespaced under its wrapper class, so the two design systems
// cannot restyle each other or the shell.
const here = (p: string) => fileURLToPath(new URL(p, import.meta.url))

function scope(prefix: string, dir: RegExp) {
  return prefixer({
    prefix,
    includeFiles: [dir],
    transform(pfx: string, selector: string, prefixed: string) {
      if (/^(html|body|#root)$/.test(selector)) return pfx
      if (selector.startsWith(':root')) return `${selector} ${pfx}`
      if (selector.startsWith(pfx)) return selector
      return prefixed
    },
  })
}

const core = process.env.SPORTLENS_CORE_URL ?? 'http://localhost:8001'
const padel = process.env.SPORTLENS_PADEL_URL ?? 'http://localhost:8010'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@futsal': here('../frontend/src'), '@padel': here('../padel/web/src') },
    // one React for every module, even those resolved from the sport folders' node_modules
    dedupe: ['react', 'react-dom', 'react-router-dom'],
  },
  css: {
    postcss: {
      plugins: [scope('.sl-futsal', /[\\/]frontend[\\/]src[\\/]/), scope('.sl-padel', /[\\/]padel[\\/]web[\\/]src[\\/]/)],
    },
  },
  server: {
    port: 5180,
    fs: { allow: [here('..')] },
    // same routes the gateway serves in production
    proxy: {
      '/api/v1': core,
      '/padel/api': { target: padel, rewrite: (p) => p.replace(/^\/padel/, '') },
    },
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) return 'vendor'
        },
      },
    },
  },
})
