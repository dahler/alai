# Build stage
FROM node:22-alpine as builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM ghcr.io/nginx/nginx-unprivileged:1.29.2-alpine3.22-otel AS runner
COPY --from=builder --chown=101:101 /app/dist /usr/share/nginx/html
COPY --chown=101:101 ./nginx.conf /etc/nginx/conf.d/default.conf
# Verify mime.types is present (needed for correct JS MIME type)
RUN test -f /etc/nginx/mime.types
EXPOSE 8080
