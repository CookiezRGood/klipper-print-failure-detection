#!/bin/bash

# This script is for setting up the 3D print failure detection plugin

# Step 1: Check if the script is being run as root
if [ "$(id -u)" != "0" ]; then
    echo "This script must be run as root. Please use sudo."
    exit 1
fi

# Step 2: Activate the Klipper virtual environment
# Assuming you have your virtual environment set up at /home/pi/klipper-env
KLIPPER_ENV_PATH="/home/pi/klipper-env"
if [ ! -d "$KLIPPER_ENV_PATH" ]; then
    echo "Klipper virtual environment not found. Please check your installation."
    exit 1
fi

source $KLIPPER_ENV_PATH/bin/activate

# Step 3: Install necessary Python dependencies
echo "Installing dependencies..."

# Install dependencies for the plugin
pip install --upgrade pip  # Ensure pip is up to date
pip install -r requirements.txt  # Install dependencies listed in requirements.txt

# Step 4: Install system dependencies if required (e.g., OpenCV)
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y libopencv-dev  # OpenCV library for image processing

# Step 5: Ensure proper permissions on the plugin files
echo "Setting up file permissions..."
chmod +x /home/pi/klipper-plugins/klipper-print-failure-detection/*.py  # Make Python files executable

# Step 6: Finish the installation
echo "Installation complete! You can now run the plugin."

# Deactivate the virtual environment
deactivate
