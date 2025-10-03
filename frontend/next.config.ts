import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Skip ESLint during production builds (handled separately in CI)
  eslint: {
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
