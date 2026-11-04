# SportLens edge image: builds the unified web app (shell + futsal + padel UIs) and serves it with the API routes.
# Build context = repo root (see /.dockerignore, which whitelists only the web sources).
FROM node:20-slim AS web
WORKDIR /src
COPY web/package.json web/package-lock.json web/
RUN cd web && npm ci --no-audit --no-fund --legacy-peer-deps
COPY frontend/src frontend/src
COPY frontend/public frontend/public
COPY padel/web/src padel/web/src
COPY padel/web/public padel/web/public
COPY web/ web/
# sport sources resolve packages (and their types) from the shell's node_modules: one React, one router
RUN ln -s ../web/node_modules frontend/node_modules && ln -s ../../web/node_modules padel/web/node_modules \
    && cd web && npm run build

FROM nginx:1.27-alpine
ENV CORE_UPSTREAM=core-api:8000 \
    PADEL_UPSTREAM=padel:8010 \
    MAX_UPLOAD_SIZE=20g \
    CSP_MEDIA_EXTRA="" \
    NGINX_ENVSUBST_FILTER="^(CORE_UPSTREAM|PADEL_UPSTREAM|MAX_UPLOAD_SIZE|CSP_MEDIA_EXTRA)$"
COPY gateway/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=web /src/web/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
