import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/static/tradingcodex_web/",
  plugins: [react()],
  build: {
    outDir: "../tradingcodex_service/static/tradingcodex_web",
    emptyOutDir: true,
    assetsDir: "",
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "[name].js",
        assetFileNames: "app[extname]",
      },
    },
  },
});
