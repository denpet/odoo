# Caddy with the GoDaddy DNS provider, for Let's Encrypt DNS-01 challenges.
# The server is internal-only, so HTTP-01/TLS-ALPN-01 can't reach it; DNS-01 proves control of
# eden.ph by creating a TXT record through the GoDaddy API instead.
FROM caddy:2.10-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/godaddy@v1.2.0

FROM caddy:2.10
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
