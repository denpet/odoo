# Caddy with the GoDaddy DNS plugin for Let's Encrypt DNS-01 challenges
FROM caddy:2.10-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/godaddy@v1.2.0

FROM caddy:2.10
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
