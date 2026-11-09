import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// Tauri expects a fixed dev port and relative asset paths in the build.
export default defineConfig({
	plugins: [vue()],
	base: './',
	clearScreen: false,
	// fs.allow: the sample workbook lives in ../samples (shared with the Python tests).
	server: { port: 5173, strictPort: true, fs: { allow: ['..'] } },
	build: { target: 'chrome105', outDir: 'dist' },
});
