FROM node:18-alpine as base
WORKDIR /srv/bridge_frontend

RUN npm install -g serve

RUN apk add curl && \
    rm -rf /var/cache/apk/*

FROM base as builder
COPY package.json package-lock.json ./
# Install dependencies
RUN npm ci

# Copy the rest of the files
COPY tsconfig.json ./
COPY public ./public
COPY src ./src

# Build the app
RUN npm run build

FROM base as final
COPY --from=builder /srv/bridge_frontend/build ./build

CMD serve -s build
