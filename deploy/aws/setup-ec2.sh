#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 24.04 EC2 instance.
# Usage (on the server):  bash setup-ec2.sh https://github.com/<you>/smartfactory-ai.git
set -euo pipefail
REPO="${1:?Usage: bash setup-ec2.sh <git-repo-url>}"

echo "==> Installing Docker, Compose, Buildx and Git"
sudo apt-get update -y
sudo apt-get install -y docker.io docker-compose-v2 docker-buildx git curl
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER" || true

echo "==> Adding 2 GB swap (the Angular build needs more than 1 GB RAM)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> Getting the code"
if [ ! -d "$HOME/smartfactory-ai" ]; then git clone "$REPO" "$HOME/smartfactory-ai"; fi
cd "$HOME/smartfactory-ai/deploy/aws"

echo "==> Configuring"
PUBLIC_IP=$(curl -s https://checkip.amazonaws.com)
DOMAIN="${DOMAIN:-$(echo "$PUBLIC_IP" | tr . -).sslip.io}"
echo "DOMAIN=$DOMAIN" > .env
[ -f app.env ] || cp app.env.example app.env

echo
echo "Next steps:"
echo "  1. nano ~/smartfactory-ai/deploy/aws/app.env      # add GEMINI_API_KEY (and DATABASE_URL for RDS)"
echo "  2. cd ~/smartfactory-ai/deploy/aws && sudo docker compose up -d --build"
echo "  3. Open https://$DOMAIN  (first start: build ~10 min, certificate ~1 min)"
