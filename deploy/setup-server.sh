#!/usr/bin/env bash
# Run as root on Ubuntu, with the full project and a deployment public key.
set -euo pipefail
test "$(id -u)" = 0 || { printf '%s\n' 'Run as root.' >&2; exit 1; }
source_dir="$(cd "$(dirname "$0")" && pwd)"
public_key="${1:?Pass the path to the deployment public key}"
grep -q '^ssh-ed25519 ' "$public_key"

if ! id saoke-deploy >/dev/null 2>&1; then
  useradd --system --user-group --create-home --home-dir /var/lib/saoke-deploy \
    --shell /bin/sh --password '*' saoke-deploy
fi
install -d -m 755 /usr/local/lib/saoke
install -m 755 "$source_dir/receive.py" /usr/local/lib/saoke/receive.py
install -d -m 755 -o saoke-deploy -g saoke-deploy /var/www/saoke /var/www/saoke/releases
install -d -m 755 /var/www/letsencrypt/.well-known/acme-challenge
# Root owns authorized_keys so the deploy account cannot remove command restrictions.
install -d -m 755 -o root -g root /var/lib/saoke-deploy/.ssh
printf 'restrict,command="/usr/local/lib/saoke/receive.py" %s\n' "$(cat "$public_key")" \
  > /var/lib/saoke-deploy/.ssh/authorized_keys
chown root:root /var/lib/saoke-deploy/.ssh/authorized_keys
chmod 644 /var/lib/saoke-deploy/.ssh/authorized_keys

site=/etc/nginx/sites-available/sk.zenify.cx
if [ ! -e "$site" ]; then
  install -m 644 "$source_dir/nginx-http.conf" "$site"
fi
ln -sfn "$site" /etc/nginx/sites-enabled/sk.zenify.cx
nginx -t
systemctl reload nginx

certbot certonly --webroot -w /var/www/letsencrypt \
  --cert-name sk.zenify.cx -d sk.zenify.cx --non-interactive --keep-until-expiring

backup="$(mktemp)"
cp "$site" "$backup"
install -m 644 "$source_dir/nginx.conf" "$site"
if ! nginx -t; then
  cp "$backup" "$site"
  rm -f "$backup"
  exit 1
fi
rm -f "$backup"
systemctl reload nginx

install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/saoke-reload-nginx <<'HOOK'
#!/bin/sh
set -eu
if [ "${RENEWED_LINEAGE:-}" = /etc/letsencrypt/live/sk.zenify.cx ]; then
  /usr/sbin/nginx -t
  /bin/systemctl reload nginx
fi
HOOK
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/saoke-reload-nginx
bash "$source_dir/setup-backend.sh"
printf '%s\n' 'SaoKe server configured; ready for GitHub Actions deployment.'
