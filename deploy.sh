#!/bin/bash
# ============================================
# AutoHelp.uz — Server Deployment Script
# Run on fresh Hetzner Cloud Ubuntu 22.04
# ============================================
set -e

echo "🚀 AutoHelp.uz Deployment Script"
echo "================================="

# ── 1. System Update ──────────────────────────────────────────────
echo "📦 Updating system..."
apt-get update && apt-get upgrade -y

# ── 2. Install Docker ─────────────────────────────────────────────
echo "🐳 Installing Docker..."
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# Install Docker Compose
apt-get install -y docker-compose-plugin

# ── 3. Install Nginx & Certbot ────────────────────────────────────
echo "🌐 Installing Nginx..."
apt-get install -y nginx certbot python3-certbot-nginx

# ── 4. Setup Firewall ────────────────────────────────────────────
echo "🔥 Configuring firewall..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# ── 5. Create project directory ──────────────────────────────────
echo "📁 Setting up project..."
mkdir -p /opt/autohelp
cd /opt/autohelp

# ── 6. Clone/Copy project files ──────────────────────────────────
echo "📋 Copy your project files to /opt/autohelp"
echo "   Then run: docker compose up -d"

# ── 7. SSL Certificate ───────────────────────────────────────────
echo ""
echo "🔐 After copying files and setting up DNS, run:"
echo "   certbot --nginx -d autohelp.uz -d www.autohelp.uz"

# ── 8. Setup systemd service for auto-restart ─────────────────────
cat > /etc/systemd/system/autohelp.service << 'EOF'
[Unit]
Description=AutoHelp.uz Telegram Bot
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/autohelp
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable autohelp.service

echo ""
echo "✅ Server setup complete!"
echo ""
echo "Next steps:"
echo "  1. Copy project files to /opt/autohelp/"
echo "  2. Create .env file from .env.example"
echo "  3. Run: cd /opt/autohelp && docker compose up -d"
echo "  4. Setup SSL: certbot --nginx -d autohelp.uz"
echo "  5. Copy nginx.conf to /etc/nginx/sites-available/"
echo ""
