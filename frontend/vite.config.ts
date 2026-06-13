import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Keep the chart stack in its own cacheable chunk, shared across the
        // lazy chart routes that import "@/echarts". It no longer lands in the
        // main entry chunk, so chartless routes never download it.
        manualChunks: {
          echarts: ["echarts/core", "echarts/renderers", "echarts/charts", "echarts/components", "vue-echarts"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
