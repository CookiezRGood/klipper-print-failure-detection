#!/bin/bash

# This script installs the 3D print failure detection plugin

# Step 1: Check if the script is being run as root
if [ "$(id -u)" != "0" ]; then
    echo "This script must be run as root. Please use sudo."
    exit 1
fi

# Step 2: Ensure the correct dependencies are installed
echo "Installing required dependencies..."
pip install -r requirements.txt

# Step 3: Ensure Mainsail's web folder is accessible
MAINSAIL_WEB_DIR="/usr/share/mainsail/web"

if [ ! -d "$MAINSAIL_WEB_DIR" ]; then
    echo "Mainsail web directory not found. Please install Mainsail before proceeding."
    exit 1
fi

# Step 4: Copy the plugin's frontend files to Mainsail's web directory
echo "Copying plugin UI files to Mainsail web directory..."
cp -r web_interface/* $MAINSAIL_WEB_DIR/

# Step 5: Create the plugin folder in the Mainsail web interface directory if it doesn't exist
PLUGIN_DIR="$MAINSAIL_WEB_DIR/plugins"
if [ ! -d "$PLUGIN_DIR" ]; then
    mkdir $PLUGIN_DIR
fi

# Copy the plugin's HTML page into the plugin directory
cp $MAINSAIL_WEB_DIR/print_failure_detection.html $PLUGIN_DIR/

# Step 6: Restart Mainsail to apply changes
echo "Restarting Mainsail..."
sudo systemctl restart mainsail

# Step 7: Finish the installation
echo "Installation complete! You can now access the plugin through Mainsail's interface."
