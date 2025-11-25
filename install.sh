#!/bin/bash

# --- 1. SETUP ---
if [ -z "$SUDO_USER" ]; then
    echo "Error: This script must be run using sudo."
    exit 1
fi
KLIPPER_USER="$SUDO_USER"
PLUGIN_DIR=$(pwd)
SERVICE_NAME="klipper-print-failure-detection"

echo "Detected User: $KLIPPER_USER"
echo "Installation Directory: $PLUGIN_DIR"

# --- 2. Install System Dependencies ---
echo "Installing system libraries..."
# libatlas-base-dev is required for NumPy/TensorFlow on Pi
apt-get update && apt-get install -y python3-opencv python3-venv libopenjp2-7 libatlas-base-dev

# --- 3. Create Virtual Environment ---
if [ ! -d "$PLUGIN_DIR/venv" ]; then
    echo "Creating Python virtual environment..."
    sudo -u "$KLIPPER_USER" python3 -m venv "$PLUGIN_DIR/venv"
fi

# --- 4. Install Python Requirements ---
echo "Installing Python requirements (This may take a while)..."
sudo -u "$KLIPPER_USER" "$PLUGIN_DIR/venv/bin/pip" install -r "$PLUGIN_DIR/requirements.txt"

# --- 5. Download Pre-Trained AI Model ---
MODEL_URL="https://github.com/frenck/python-spaghetti-detect/raw/main/spaghetti_detect/model.tflite"
LABELS_URL="https://github.com/frenck/python-spaghetti-detect/raw/main/spaghetti_detect/labels.txt"

echo "Downloading AI Model..."
if [ ! -f "$PLUGIN_DIR/model.tflite" ]; then
    sudo -u "$KLIPPER_USER" curl -L -o "$PLUGIN_DIR/model.tflite" "$MODEL_URL"
fi
if [ ! -f "$PLUGIN_DIR/labels.txt" ]; then
    sudo -u "$KLIPPER_USER" curl -L -o "$PLUGIN_DIR/labels.txt" "$LABELS_URL"
fi

# --- 6. Permissions Guarantee ---
echo "Guarding against file permission errors..."
chown -R "$KLIPPER_USER":"$KLIPPER_USER" "$PLUGIN_DIR"

# --- 7. Service File Creation ---
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
echo "Creating Systemd service file..."

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Klipper Print Failure Detection (AI Powered)
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

# --- 8. Enable and Start Service ---
echo "Enabling and starting service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME".service
systemctl restart "$SERVICE_NAME".service

echo "------------------------------------------------"
echo "AI Installation complete!"
echo "Access the dashboard at: http://<your-ip>:7126"
echo "------------------------------------------------"
