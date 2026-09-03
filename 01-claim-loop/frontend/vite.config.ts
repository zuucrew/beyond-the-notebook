import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // Polling because the source is a bind mount from the host into the
    // container; inotify does not cross that boundary reliably on macOS.
    watch: { usePolling: true },
  },
});
