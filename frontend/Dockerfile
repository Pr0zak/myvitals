FROM node:22-alpine AS build
WORKDIR /app
# Pin pnpm 9 — pnpm 10 fails the build on ignored build scripts
# (esbuild, vue-demi). Sticking with 9 keeps `pnpm install` non-interactive.
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate
# SA-S4: install from the committed lockfile, not a fresh resolve of the
# floating package.json ranges — --frozen-lockfile refuses to touch
# pnpm-lock.yaml and fails loudly on drift instead of silently pulling
# whatever is newest on the registry today.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM caddy:2.8-alpine
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 80
