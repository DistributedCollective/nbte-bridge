# Forked from https://github.com/ordinals/ord/blob/master/Dockerfile
FROM rust:1.75.0-bookworm as builder

ARG ORD_GIT_CHECKOUT="0.16.0"
ARG ORD_GIT_URL="https://github.com/ordinals/ord"

WORKDIR /usr/src/ord

RUN git clone $ORD_GIT_URL . \
    && git checkout $ORD_GIT_CHECKOUT

RUN cargo build --bin ord --release

FROM debian:bookworm-slim

RUN apt update -y && apt install -y libssl-dev gosu
COPY --from=builder /usr/src/ord/target/release/ord /usr/local/bin

ENV RUST_BACKTRACE=1
ENV RUST_LOG=info

WORKDIR /home/ord

COPY ./docker-entrypoint.sh .

VOLUME "/home/ord/data"

ENTRYPOINT ["/home/ord/docker-entrypoint.sh"]
CMD ["--data-dir /home/ord/data"]
