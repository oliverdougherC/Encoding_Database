#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CERT_DIR="${CERT_DIR:-$ROOT_DIR/nginx/dev-certs}"
CERT_FILE="${CERT_FILE:-$CERT_DIR/selfsigned.crt}"
KEY_FILE="${KEY_FILE:-$CERT_DIR/selfsigned.key}"
DAYS="${DAYS:-30}"
SUBJECT="${SUBJECT:-/CN=localhost}"

log() {
  echo "[generate-dev-cert] $*"
}

die() {
  echo "[generate-dev-cert] ERROR: $*" >&2
  exit 1
}

command -v openssl >/dev/null 2>&1 || die "openssl is required"

mkdir -p "$CERT_DIR"
umask 077

tmp_config="$(mktemp)"
trap 'rm -f "$tmp_config"' EXIT

cat >"$tmp_config" <<EOF
[req]
distinguished_name = dn
x509_extensions = v3_req
prompt = no

[dn]
CN = localhost

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
EOF

openssl req \
  -x509 \
  -nodes \
  -newkey rsa:2048 \
  -days "$DAYS" \
  -keyout "$KEY_FILE" \
  -out "$CERT_FILE" \
  -subj "$SUBJECT" \
  -config "$tmp_config" \
  -extensions v3_req >/dev/null 2>&1

chmod 600 "$KEY_FILE"
chmod 644 "$CERT_FILE"

log "Generated $CERT_FILE and $KEY_FILE"
