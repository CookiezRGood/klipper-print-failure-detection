#!/bin/bash

if [ -z "$SUDO_USER" ]; then
    echo "Error: This script must be run using sudo."
    exit 1
fi
KLIPPER_USER="$SUDO_USER"
PLUGIN_DIR=$(pwd)
SERVICE_NAME="klipper-print-failure-detection"

echo "Detected User: $KLIPPER_USER"
echo "Installation Directory: $PLUGIN_DIR"

# 1. System Dependencies (libatlas for numpy/tflite)
echo "Installing system libraries..."
apt-get update && apt-get install -y python3-opencv python3-venv libopenjp2-7 libatlas-base-dev

# 2. Virtual Environment
if [ ! -d "$PLUGIN_DIR/venv" ]; then
    echo "Creating Python virtual environment..."
    sudo -u "$KLIPPER_USER" python3 -m venv "$PLUGIN_DIR/venv"
fi

# 3. Install Lightweight Requirements
echo "------------------------------------------------"
echo "INSTALLING TFLITE RUNTIME (Lightweight AI)"
echo "------------------------------------------------"
sudo -u "$KLIPPER_USER" "$PLUGIN_DIR/venv/bin/pip" install -r "$PLUGIN_DIR/requirements.txt"

# 4. Permissions
echo "Fixing permissions..."
chown -R "$KLIPPER_USER":"$KLIPPER_USER" "$PLUGIN_DIR"

# 5. Service Creation
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
echo "Creating Systemd service..."

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Klipper Print Failure Detection (TFLite)
After=network.target

[Service]
Type=simple
User=$KLIPPER_USER
ExecStart=$PLUGIN_DIR/venv/bin/python $PLUGIN_DIR/plugin.py
WorkingDirectory=$PLUGIN_DIR
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 6. Enable Service
echo "Enabling service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME".service
systemctl restart "$SERVICE_NAME".service

echo "------------------------------------------------"
echo "Installation Complete!"
echo "Please upload your exported 'model.tflite' file."
echo "------------------------------------------------"
