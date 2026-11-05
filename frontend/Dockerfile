FROM node:24-slim AS build
RUN npm install -g pnpm@12.15.0 # keep in sync with package.json "packageManager"

WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build && pnpm prune --prod

FROM node:24-slim

WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/next.config.ts ./

EXPOSE 3000
CMD ["node_modules/.bin/next", "start"]
