import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import { resolve } from 'path';

export default defineConfig(() => ({
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, '../static/reactbits'),
    emptyOutDir: true,
    manifest: false,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/main.js',
        chunkFileNames: 'assets/chunk-[name].js',
        assetFileNames: 'assets/[name][extname]',
      },
    },
  },
  server: {
    port: 5173,
    origin: 'http://localhost:5173',
  },
}));
