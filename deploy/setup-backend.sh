#!/usr/bin/env bash
set -euo pipefail
test "$(id -u)" = 0
source_dir="$(cd "$(dirname "$0")" && pwd)"
project_dir="$(dirname "$source_dir")"

if ! id saoke-app >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /var/lib/saoke --shell /usr/sbin/nologin saoke-app
fi
install -d -m 750 -o saoke-app -g saoke-app /var/lib/saoke
install -d -m 750 -o root -g saoke-app /etc/saoke
install -d -m 755 /opt/saoke/runtime /usr/local/lib/saoke
python3 -m pip install --quiet --upgrade --no-cache-dir --target /opt/saoke/runtime -r "$project_dir/requirements.txt"

if [ ! -f /etc/saoke/saoke.env ]; then
  SAOKE_SOURCE="$project_dir" python3 - <<'PY'
import grp
import os
from pathlib import Path
import secrets
import sys
sys.path.insert(0, os.environ['SAOKE_SOURCE'])
from server.app import password_hash
os.umask(0o077)
password=secrets.token_urlsafe(24)
env=Path('/etc/saoke/saoke.env')
env.write_text('SAOKE_DB=/var/lib/saoke/saoke.sqlite3\nSAOKE_USER=admin\n'
               'SAOKE_ORIGIN=https://sk.zenify.cx\nSAOKE_PASSWORD_HASH='+password_hash(password)+'\n')
os.chown(env,0,grp.getgrnam('saoke-app').gr_gid)
env.chmod(0o640)
Path('/etc/saoke/initial-login.txt').write_text('URL: https://sk.zenify.cx\nUsername: admin\nPassword: '+password+'\n')
PY
fi

install -m 755 "$source_dir/receive.py" /usr/local/lib/saoke/receive.py
install -m 755 "$source_dir/backup.py" /usr/local/lib/saoke/backup.py
install -m 644 "$source_dir/saoke.service" /etc/systemd/system/saoke.service
install -m 644 "$source_dir/saoke-backup.service" /etc/systemd/system/saoke-backup.service
install -m 644 "$source_dir/saoke-backup.timer" /etc/systemd/system/saoke-backup.timer
printf '%s\n' 'saoke-deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart saoke.service, /usr/bin/systemctl stop saoke.service' \
  > /etc/sudoers.d/saoke-deploy
chmod 440 /etc/sudoers.d/saoke-deploy
visudo -cf /etc/sudoers.d/saoke-deploy
systemctl daemon-reload
systemctl enable saoke.service
# Start the backend and install the new API vhost only after the first code release is uploaded.
printf '%s\n' 'Backend runtime and persistent storage prepared.'
