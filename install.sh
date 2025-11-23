#!/bin/bash

# This script is for setting up the 3D print failure detection plugin

# Step 1: Check if the script is being run as root
if [ "$(id -u)" != "0" ]; then
    echo "This script must be run as root. Please use sudo."
    exit 1
fi

# Step 2: Make sure this script is executable, if not, set the correct permissions
if [ ! -x "$0" ]; then
    echo "Making the install script executable..."
    chmod +x "$0"
fi

# Step 3: Check if the Klipper virtual environment exists, if not, create it
KLIPPER_ENV_PATH="/home/pi/klipper-env"
if [ ! -d "$KLIPPER_ENV_PATH" ]; then
    echo "Klipper virtual environment not found. Creating the virtual environment..."
    
    # Install Python 3 and virtualenv if not installed
    sudo apt-get update
    sudo apt-get install -y python3-venv python3-pip

    # Create the virtual environment
    python3 -m venv $KLIPPER_ENV_PATH
    echo "Virtual environment created at $KLIPPER_ENV_PATH"
fi

# Step 4: Activate the Klipper virtual environment
source $KLIPPER_ENV_PATH/bin/activate

# Step 5: Install necessary Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip  # Ensure pip is up to date
pip install -r requirements.txt  # Install dependencies listed in requirements.txt

# Step 6: Install system dependencies (OpenCV for image processing)
echo "Installing system dependencies..."
sudo apt-get install -y libopencv-dev  # OpenCV library for image processing

# Step 7: Ensure proper permissions on the plugin files
echo "Setting up file permissions..."
chmod +x /home/pi/klipper-plugins/klipper-print-failure-detection/*.py  # Make Python files executable

# Step 8: Finish the installation
echo "Installation complete! You can now run the plugin."

# Deactivate the virtual environment
deactivate
