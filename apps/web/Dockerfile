# Keep the readable tag; update its digest deliberately with each version bump.
FROM node:22.22.2-bookworm-slim@sha256:9f6d5975c7dca860947d3915877f85607946403fc55349f39b4bc3688448bb6e AS build

# npm registry defaults to npmmirror; override with
# --build-arg NPM_CONFIG_REGISTRY=... if a mirror rate-limits or 403s.
ARG NPM_CONFIG_REGISTRY=https://registry.npmmirror.com

ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY} \
    COREPACK_NPM_REGISTRY=${NPM_CONFIG_REGISTRY}

RUN corepack enable \
    && corepack prepare pnpm@11.19.0 --activate

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json

RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile

COPY apps/web ./apps/web

RUN pnpm --dir apps/web build

FROM node:22.22.2-bookworm-slim@sha256:9f6d5975c7dca860947d3915877f85607946403fc55349f39b4bc3688448bb6e AS runtime

ARG NPM_CONFIG_REGISTRY=https://registry.npmmirror.com

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY} \
    COREPACK_NPM_REGISTRY=${NPM_CONFIG_REGISTRY}

RUN corepack enable \
    && corepack prepare pnpm@11.19.0 --activate

WORKDIR /app

COPY --from=build --chown=node:node /app/package.json ./package.json
COPY --from=build --chown=node:node /app/pnpm-lock.yaml ./pnpm-lock.yaml
COPY --from=build --chown=node:node /app/pnpm-workspace.yaml ./pnpm-workspace.yaml
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/apps/web ./apps/web

USER node
WORKDIR /app/apps/web

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=10 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000').then(r => { if (!r.ok) process.exit(1) }).catch(() => process.exit(1))"]

CMD ["pnpm", "start"]
