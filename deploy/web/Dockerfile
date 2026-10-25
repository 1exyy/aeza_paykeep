# Frontend: build the SPA and serve it with nginx, which also proxies /api/ to the backend.
# Build context: repository root (see docker-compose.yml).
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html vite.config.ts vite-env.d.ts tsconfig.json tsconfig.app.json tsconfig.node.json \
     vitest.config.ts playwright.config.ts ./
COPY public ./public
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine
COPY deploy/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
