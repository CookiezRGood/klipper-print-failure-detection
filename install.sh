#!/bin/bash

# --- 1. SETUP ---
# Identify the non-root user who ran the script via sudo
if [ -z "$SUDO_USER" ]; then
    echo "Error: This script must be run using sudo."
    exit 1
fi
KLIPPER_USER="$SUDO_USER"
PLUGIN_DIR=$(pwd)
SERVICE_NAME="failure_detection"

echo "Detected User: $KLIPPER_USER"
echo "Installation Directory: $PLUGIN_DIR"

# --- 2. Install System Dependencies (Universal Safety) ---
# Ensures the Pi has the libraries needed for OpenCV
echo "Installing system libraries..."
apt-get update && apt-get install -y python3-opencv python3-venv libopenjp2-7

# --- 3. Create Virtual Environment (THE MISSING STEP) ---
if [ ! -d "$PLUGIN_DIR/venv" ]; then
    echo "Creating Python virtual environment..."
    # We run this AS the user so the folder is owned by them, not root
    sudo -u "$KLIPPER_USER" python3 -m venv "$PLUGIN_DIR/venv"
fi

# --- 4. Install Python Dependencies ---
echo "Installing Python requirements..."
sudo -u "$KLIPPER_USER" "$PLUGIN_DIR/venv/bin/pip" install -r "$PLUGIN_DIR/requirements.txt"

# --- 5. Permissions Guarantee ---
echo "Guarding against file permission errors..."
# Forces the folder to be owned by the user, fixing the save_settings issue
chown -R "$KLIPPER_USER":"$KLIPPER_USER" "$PLUGIN_DIR"

# --- 6. Service File Creation ---
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
echo "Creating Systemd service file..."

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Klipper Print Failure Detection Plugin
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

# --- 7. Enable and Start Service ---
echo "Enabling and starting service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME".service
systemctl restart "$SERVICE_NAME".service

echo "------------------------------------------------"
echo "Installation complete!"
echo "Access the dashboard at: http://<your-ip>:7126"
echo "------------------------------------------------"
