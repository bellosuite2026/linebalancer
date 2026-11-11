import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// three.js dans un chunk à part (chargé seulement avec les vues 3D)
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: { rollupOptions: { output: { manualChunks: (id) => (id.includes("node_modules/three/") ? "three" : id.includes("node_modules/@xyflow/") || id.includes("node_modules/d3-") ? "xyflow" : undefined) } } },
});
