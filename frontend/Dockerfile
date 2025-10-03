# syntax=docker/dockerfile:1

# --- Builder ---
FROM node:20-alpine AS builder
WORKDIR /app

# Install dependencies
COPY package.json package-lock.json* ./
RUN npm ci

# Copy source
COPY . .

# Build Next.js app (production)
ENV NODE_ENV=production
RUN npm run build

# Prune dev dependencies
RUN npm prune --omit=dev

# --- Runner ---
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOST=0.0.0.0
EXPOSE 3000

# Copy production deps and build output
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
# Use JS config at runtime to avoid installing TypeScript in the runner image
COPY --from=builder /app/next.config.mjs ./next.config.mjs

# Explicitly bind to 0.0.0.0 so Nginx in the same Docker network can reach it
CMD ["node", "node_modules/next/dist/bin/next", "start", "-H", "0.0.0.0", "-p", "3000"]


