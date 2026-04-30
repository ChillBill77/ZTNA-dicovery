FROM node:22-bookworm AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
RUN npm run build

# The api container mounts this as its static asset dir. In dev the Vite server
# replaces this image entirely (see docker-compose.dev.yml override).
FROM busybox:1.37 AS dist
WORKDIR /web
COPY --from=build /app/dist /web
CMD ["sh", "-c", "echo 'static assets baked at /web; mount into api'; sleep infinity"]
