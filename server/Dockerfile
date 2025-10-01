# syntax=docker/dockerfile:1

# --- Builder ---
FROM node:20-alpine AS builder
WORKDIR /app

# Install deps
COPY package.json package-lock.json* ./
RUN npm ci

# Copy source
COPY tsconfig.json ./
COPY prisma ./prisma
COPY src ./src

# Generate Prisma client
RUN npx prisma generate

# Build TypeScript
RUN npm run build

# Prune dev dependencies; keep only production deps and generated client
RUN npm prune --omit=dev

# --- Runtime ---
FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production

# Copy production node_modules and app files from builder
COPY --from=builder /app/node_modules ./node_modules
COPY package.json package-lock.json* ./

# Install Prisma CLI for runtime migrations
RUN npm i prisma@^6.16.3 --no-save

# Copy build outputs and prisma client
COPY --from=builder /app/dist ./dist
# Prisma client is in node_modules when using default output
COPY prisma ./prisma

EXPOSE 3001

# Default env (override at runtime)
ENV PORT=3001

CMD ["node", "dist/index.js"]
