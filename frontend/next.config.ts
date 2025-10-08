import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Skip ESLint during production builds (handled separately in CI)
  eslint: {
    ignoreDuringBuilds: true,
  },
  headers: async () => [
    {
      source: '/(.*)',
      headers: [
        { key: 'Referrer-Policy', value: 'no-referrer' },
        { key: 'X-Frame-Options', value: 'DENY' },
        { key: 'X-Content-Type-Options', value: 'nosniff' },
        { key: 'Permissions-Policy', value: "geolocation=(), microphone=(), camera=()" },
        // Basic CSP; adjust as needed if adding external resources
        { key: 'Content-Security-Policy', value: "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'" },
      ],
    },
  ],
};

export default nextConfig;
