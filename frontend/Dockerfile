# ── Stage 1: build ───────────────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# Install deps first (cached layer; only re-runs when lock file changes)
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Bake VITE_API_URL at build time if passed (e.g. for production builds)
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# ── Stage 2: serve ────────────────────────────────────────────────────────────
FROM node:20-alpine AS serve

RUN npm install -g serve

COPY --from=build /app/dist /app/dist

WORKDIR /app

EXPOSE 3000

CMD ["serve", "-s", "dist", "-l", "3000"]
