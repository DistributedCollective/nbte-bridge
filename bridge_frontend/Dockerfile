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

ARG REACT_APP_API_BASE_URL
ARG REACT_APP_RUNE_BRIDGE_CONTRACT_ADDRESS

ENV REACT_APP_API_BASE_URL=$REACT_APP_API_BASE_URL
ENV REACT_APP_RUNE_BRIDGE_CONTRACT_ADDRESS=$REACT_APP_RUNE_BRIDGE_CONTRACT_ADDRESS

# Build the app
RUN npm run build

FROM base as final
COPY --from=builder /srv/bridge_frontend/build ./build

CMD serve -s build
