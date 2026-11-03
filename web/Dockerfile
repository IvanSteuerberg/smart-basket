# Web image: build the React PWA, then serve it with Caddy, which also proxies /api (0008).
# Build context is the repository root (see compose.yaml), to reach infra/caddy.
FROM node:26.13.0-alpine AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run typecheck && npm run build

FROM caddy:2.11.7-alpine
COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
