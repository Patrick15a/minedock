#!/bin/bash
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then
  echo 'Bitte mit sudo bash deploy/install.sh ausführen.' >&2
  exit 1
fi
. /etc/os-release
if [[ ${ID} != debian || ${VERSION_ID} != 13 ]]; then
  echo 'Dieses Installationsskript ist für Debian 13 vorgesehen.' >&2
  exit 1
fi
SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ -e /opt/minedock || -e /etc/systemd/system/minedock.service ]]; then
  echo 'Installation existiert bereits. Upgrade-Schritte in README.md verwenden.' >&2
  exit 1
fi
apt-get update
apt-get install -y python3 python3-venv openjdk-21-jre-headless ca-certificates
if ! id minedock >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/minedock --create-home --shell /usr/sbin/nologin minedock
fi
install -d -m 755 /opt/minedock
install -d -o minedock -g minedock -m 700 /var/lib/minedock
cp -R -- "$SOURCE_DIR/app" "$SOURCE_DIR/deploy" "$SOURCE_DIR/docs" "$SOURCE_DIR/requirements.txt" "$SOURCE_DIR/requirements.lock" "$SOURCE_DIR/README.md" /opt/minedock/
python3 -m venv /opt/minedock/.venv
/opt/minedock/.venv/bin/pip install -r /opt/minedock/requirements.lock
if [[ ! -e /etc/minedock/minedock.env ]]; then
  python3 /opt/minedock/deploy/configure.py
fi
install -m 644 /opt/minedock/deploy/minedock.service /etc/systemd/system/minedock.service
systemctl daemon-reload
systemctl enable --now minedock
echo 'MineDock lauscht standardmäßig auf 0.0.0.0:8080. Apache-Reverse-Proxy und MINEDOCK_PROXY_IPS gemäß README konfigurieren.'
