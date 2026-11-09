import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// Tauri expects a fixed dev port and relative asset paths in the build.
export default defineConfig({
	plugins: [vue()],
	base: './',
	clearScreen: false,
	server: { port: 5173, strictPort: true },
	build: { target: 'chrome105', outDir: 'dist' },
});
