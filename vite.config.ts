import { defineConfig } from 'vite';
export default defineConfig({server:{port:5173,proxy:{'/api':'http://127.0.0.1:18080'}},build:{rollupOptions:{onwarn(warning, warn){if(warning.code === 'MODULE_LEVEL_DIRECTIVE' && warning.message.includes('use client')) return; warn(warning);}}}});
