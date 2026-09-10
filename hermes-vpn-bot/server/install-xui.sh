#!/usr/bin/env bash
# Installs the 3x-ui panel (Xray core) on a small (1 vCPU / 1GB RAM) Ubuntu/Debian VPS.
# Run as root: bash install-xui.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo bash install-xui.sh)" >&2
  exit 1
fi

echo "==> Updating system packages"
apt-get update -y
apt-get upgrade -y
apt-get install -y curl socat ufw

# --- 1GB RAM safety net -----------------------------------------------------
# The panel + node processes can spike during install/updates; a small swap
# file avoids OOM kills on a 1GB box. Safe to keep even if unused.
if ! swapon --show | grep -q '/swapfile'; then
  echo "==> Creating 1GB swap file"
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  if ! grep -q '/swapfile' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
else
  echo "==> Swap already configured, skipping"
fi

# --- Firewall ----------------------------------------------------------------
echo "==> Configuring firewall (ufw)"
ufw allow OpenSSH
ufw allow 2053/tcp   # default 3x-ui panel port (change later if you customize it)
ufw allow 443/tcp    # Reality/TLS inbound port (adjust to whatever port you pick)
ufw --force enable

# --- Install 3x-ui -------------------------------------------------------
echo "==> Installing 3x-ui panel"
bash <(curl -Ls https://raw.githubusercontent.com/MHSanaei/3x-ui/master/install.sh)

cat <<'EOF'

==============================================================================
Panel installed.

NEXT STEPS (manual, one-time):
  1. Run `x-ui` on the server and use the menu to set a custom panel
     username/password and port (don't leave the defaults).
  2. Note the panel port, username, and password — you'll need them in
     bot/.env as XUI_BASE_URL / XUI_USERNAME / XUI_PASSWORD.
  3. Open that port in ufw if you changed it from 2053:
       ufw allow <your-port>/tcp
  4. Run `python3 setup_inbound.py` (after `pip install requests`) to create
     a VLESS+Reality inbound automatically, or create one from the panel UI.

Keep the panel port and credentials private — anyone with panel access can
create/delete VPN accounts.
==============================================================================
EOF
