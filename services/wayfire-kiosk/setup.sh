#!/bin/bash
set -e

PI_USER="${PI_USER:-pi}"
PI_HOME="${PI_HOME:-/home/$PI_USER}"
SYSTEMD_DIR=/etc/systemd/system
UDEV_RULES_DIR=/etc/udev/rules.d

# 1. Install wayfire and wlr-randr
sudo apt-get install -y wayfire wlr-randr

# 2. Remove stale HyperPixel package udev rule (interferes with ours)
sudo rm -f "$UDEV_RULES_DIR/99-hyperpixel-touch.rules"

# 3. Install udev rule (Goodix touch calibration)
sudo cp 99-goodix-hyperpixel-touch.rules "$UDEV_RULES_DIR/"
sudo udevadm control --reload-rules

# 4. Install wayfire config
mkdir -p "$PI_HOME/.config"
cp wayfire.ini "$PI_HOME/.config/wayfire.ini"

# 5. Install systemd service
sudo cp cinemate-kiosk.service "$SYSTEMD_DIR/cinemate-kiosk.service"
sudo systemctl daemon-reload

# 6. Enable and start
sudo systemctl enable cinemate-kiosk.service
sudo systemctl restart cinemate-kiosk.service

echo "Done. Check status: sudo systemctl status cinemate-kiosk.service"
