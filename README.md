# Print Failure Detection Plugin for Klipper/Mainsail

## Local AI-Powered Failure Detection

This plugin uses advanced AI (TensorFlow Lite) to detect print failures in real-time. This plugin utilizes a computer vision model trained to recognize specific failure states like spaghetti, stringing, and zits.

It runs locally on your Raspberry Pi (or other Klipper host), integrates directly with Moonraker to pause or cancel failed prints, and provides a dedicated dashboard for monitoring up to two cameras simultaneously.

## Features

- **AI Failure Detection**: Uses a .tflite model (YOLOv8 Nano architecture) to identify failures with high accuracy.
- **Multi-Camera Support**: Monitor and detect failures on up to 2 cameras at once.
- **Dual Thresholds**:
   - **Detection Threshold**: Visually highlights potential issues (Yellow box) without stopping the print.
   - **Trigger Threshold**: Automatically pauses or cancels the print when confidence is high (Red box) after a set number of retrys.
- **Smart Idle Mode**: Automatically stops processing when the printer is idle to save CPU resources.
- **Real-time Dashboard**: View live feeds with bounding box overlays showing exactly what the AI detected.
- **Configurable Actions**: Choose to Warn, Pause, or Cancel print upon failure.

## Installation

Clone this repository to your printer and install:
   ```bash
   cd ~/klipper/klippy/extras/
   git clone https://github.com/CookiezRGood/klipper-print-failure-detection.git
   cd ~/klipper/klippy/extras/klipper-print-failure-detection
   sudo bash install.sh
   ```

## Post Installation Steps

- Open your browser and go to http://YOUR-IP:7126 to see the dashboard
- Open the settings and input your printer camera ip (Default uses MJPEG style (.../webcam/?action=snapshot)
- Adjust any other settings to your preference with testing to make sure it works well for your setup (mainly detection/failure threshold values)


## Automatic Updates

Add the following to your moonraker.conf to receive automatic updates:

```bash
[update_manager klipper-print-failure-detection]
type: git_repo
path: ~/klipper/klippy/extras/klipper-print-failure-detection
origin: https://github.com/CookiezRGood/klipper-print-failure-detection.git
install_script: install.sh
primary_branch: main
managed_services: klipper-print-failure-detection
```
