#!/bin/bash

# Installation Script for Print Failure Detection (Standalone Service)

USER="pi"
PLUGIN_DIR="/home/$USER/klipper-print-failure-detection"
VENV_DIR="$PLUGIN_DIR/venv"

# 1. Install System Dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-opencv python3-venv libopenjp2-7

# 2. Create Python Virtual Environment (Best practice to avoid breaking system python)
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv $VENV_DIR
fi

# 3. Install Python Requirements
echo "Installing Python requirements..."
$VENV_DIR/bin/pip install -r requirements.txt

# 4. Create Systemd Service
echo "Creating system service..."
SERVICE_FILE="/etc/systemd/system/failure_detection.service"

# This writes the service file so the Pi knows how to run your code
sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=Klipper Print Failure Detection Plugin
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PLUGIN_DIR
ExecStart=$VENV_DIR/bin/python plugin.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOL

# 5. Enable and Start the Service
echo "Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable failure_detection.service
sudo systemctl restart failure_detection.service

echo "Done! Your plugin is running on http://<your-printer-ip>:7126"
