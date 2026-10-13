import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static shell + streamed, per-user data (all research data is behind auth).
  cacheComponents: true,
  partialPrefetching: true,
  // Self-hosted on a VPS via Docker.
  output: "standalone",
  poweredByHeader: false,
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
