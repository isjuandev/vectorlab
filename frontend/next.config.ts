import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Salida mínima autocontenida para la imagen Docker (ver frontend/Dockerfile).
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
