#!/bin/bash

# --- 1. SETUP ---
# Identify the non-root user who ran the script via sudo
if [ -z "$SUDO_USER" ]; then
    echo "Error: This script must be run using sudo, and the user must be defined."
    exit 1
fi
KLIPPER_USER="$SUDO_USER"
PLUGIN_DIR=$(pwd)
SERVICE_NAME="failure_detection"

# --- 2. Install Python Dependencies ---
echo "Installing required Python dependencies..."
# Run pip as the non-root user to install into their environment/venv
sudo -u "$KLIPPER_USER" "$PLUGIN_DIR/venv/bin/pip" install -r "$PLUGIN_DIR/requirements.txt"

# --- 3. Permissions Guarantee (THE FIX) ---
echo "Guarding against file permission errors..."
# This is the critical step: ensures the entire plugin directory and all contents 
# are owned by the Klipper user. This allows the plugin to create 'user_settings.json'.
chown -R "$KLIPPER_USER":"$KLIPPER_USER" "$PLUGIN_DIR"

# --- 4. Service File Creation (Ensures correct User setting) ---
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "Creating Systemd service file..."
sudo bash -c "cat > $SERVICE_FILE <<EOF
[Unit]
Description=Klipper Print Failure Detection Plugin
After=network.target

[Service]
Type=simple
User=$KLIPPER_USER
# Assumes venv is created in the standard location
ExecStart=$PLUGIN_DIR/venv/bin/python $PLUGIN_DIR/plugin.py
WorkingDirectory=$PLUGIN_DIR
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF"

# --- 5. Enable and Start Service ---
echo "Enabling and starting service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME".service
systemctl start "$SERVICE_NAME".service

echo "Installation complete! The plugin should now be running."
