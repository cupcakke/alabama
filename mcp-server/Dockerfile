FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src

RUN npm run build

FROM node:22-alpine AS runtime

RUN addgroup -S appgroup && adduser -S appuser -G appgroup

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY --from=builder /app/dist ./dist

USER appuser

EXPOSE 8080

ENV PORT=8080
ENV TOOL_NAME=search_alabama_md

CMD ["node", "dist/index.js"]
