import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// Mobile-first PWA (decision 0008). In development `/api` is proxied to the backend.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "Smart Basket",
        short_name: "Smart Basket",
        description: "Tu cesta de la compra más barata en León",
        lang: "es",
        start_url: "/",
        scope: "/",
        display: "standalone",
        orientation: "portrait",
        background_color: "#f6f7f2",
        theme_color: "#2f6f4e",
        icons: [
          { src: "pwa-192.png", sizes: "192x192", type: "image/png" },
          { src: "pwa-512.png", sizes: "512x512", type: "image/png" },
          { src: "pwa-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith("/api/"),
            handler: "NetworkOnly",
          },
        ],
      },
    }),
  ],
  server: {
    proxy: { "/api": process.env.VITE_API_PROXY ?? "http://localhost:8000" },
  },
});
