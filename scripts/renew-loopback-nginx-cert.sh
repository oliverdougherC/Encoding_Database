#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 CONTAINER DEV_CERT_DIR" >&2
  exit 2
fi

container="$1"
cert_dir="$(cd "$2" && pwd -P)"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cert="$cert_dir/selfsigned.crt"
key="$cert_dir/selfsigned.key"
umask 077

# This job manages the repository's localhost certificates. Public ingress
# certificates have their own renewal and trust chain.
mounted_dir="$(docker inspect --type container -f '{{range .Mounts}}{{if eq .Destination "/etc/nginx/certs"}}{{.Source}}{{end}}{{end}}' "$container")"
[[ "$mounted_dir" == "$cert_dir" ]]
[[ "$(openssl x509 -in "$cert" -noout -subject -nameopt RFC2253)" == 'subject=CN=localhost' ]]
if openssl x509 -in "$cert" -noout -checkend 604800 >/dev/null; then
  exit 0
fi

staging="$(mktemp -d "$cert_dir/.renew.XXXXXXXX")"
restore=0
cleanup() {
  local status="$?"
  if (( restore )); then
    mv -f "$staging/old.crt" "$cert"
    mv -f "$staging/old.key" "$key"
    docker exec "$container" nginx -s reload || true
  fi
  rm -rf "$staging"
  exit "$status"
}
trap cleanup EXIT
cp -p "$cert" "$staging/old.crt"
cp -p "$key" "$staging/old.key"
CERT_DIR="$staging" CERT_FILE="$staging/selfsigned.crt" KEY_FILE="$staging/selfsigned.key" \
  DAYS=30 SUBJECT=/CN=localhost bash "$script_dir/generate-dev-cert.sh"
restore=1
mv -f "$staging/selfsigned.crt" "$cert"
mv -f "$staging/selfsigned.key" "$key"
docker exec "$container" nginx -t
docker exec "$container" nginx -s reload
docker exec "$container" sh -ec '
  for attempt in 1 2 3 4 5; do
    if SSL_CERT_FILE=/etc/nginx/certs/selfsigned.crt wget -qO- https://127.0.0.1/health >/dev/null; then
      exit 0
    fi
    sleep 1
  done
  exit 1
'
restore=0
echo "Renewed the localhost TLS certificate for $container"
