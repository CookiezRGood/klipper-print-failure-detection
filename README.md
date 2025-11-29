# Print Failure Detection Plugin for Klipper/Mainsail

## Local AI-Powered Failure Detection

This plugin uses an optimized TensorFlow Lite model to detect print failures in real time. It runs fully locally on your Klipper host, requires no cloud services, and directly integrates with Moonraker to pause or cancel prints automatically.

The plugin includes a complete monitoring dashboard with live camera feeds, visual failure overlays, multi-zone masking, and support for one or two cameras at once.

[AI Training Documentation](documents/AI_Training.md)

## Prerequisites

- Crowsnest (adding camera functionality)
   - https://github.com/mainsail-crew/crowsnest

## Features

- **AI Failure Detection**: Uses a .tflite YOLO-based model to identify failures such as spaghetti, stringing, and zits.

<img width="627" height="562" alt="image" src="https://github.com/user-attachments/assets/05b6f73e-8a87-4586-993d-4e8ce503b709" />

<br><br>

- **Real-time Dashboard**: View live camera feeds with bounding box overlays showing what the AI detects.

<img width="1854" height="963" alt="image" src="https://github.com/user-attachments/assets/404b504d-29d1-44db-acf3-ca46a4d4a87a" />

<br><br>

- **Comprehensive Settings Menu**: Many configurable aspects to tailor the plugin to your printer and environment.

<img width="714" height="571" alt="image" src="https://github.com/user-attachments/assets/23e8e2e7-a8d5-4e4b-a084-b53f2a2b2501" />

<br><br>

- **Multi-Camera Support**: Monitor and analyze up to **two cameras simultaneously**, each with its own prediction score and mask zones.
  
- **Dual Thresholds**:
   - **Detection Threshold** (yellow): highlights possible issues.
   - **Trigger Threshold** (red): automatically pauses or cancels the print after a configurable number of retries.

- **Configurable Actions**: Choose to warn only, pause, or cancel the print when a failure is detected.
  
- **Multi-Zone Masking System**:
   - Click-and-drag to define any number of mask rectangles directly on the camera feed.
   - Per-camera mask storage for dual-camera setups.
   - Masks hide irrelevant regions from AI analysis.
   - Right-click to delete individual zones.
   - “Clear Masks” button for quick resets.

![masking](https://github.com/user-attachments/assets/0042758a-11e9-45f8-bcfb-1e4ac639a1be)

<br><br>

- **Smart Idle Mode**: Automatically suspends AI processing when the printer is idle to reduce CPU usage.

- **Manual Start Button**: Starts AI monitoring process (useful for testing and finding ideal detection percentages).

- **Auto-Start Toggle**: Toggle switch to enable the plugin automatically starting when you start a print.

- **Live Plugin Logs**: View the logs for the plugin on the main dashboard to check for functionality and see errors.

## Installation

Clone this repository to your printer and install:
   ```bash
   cd ~/klipper/klippy/extras/
   git clone https://github.com/CookiezRGood/klipper-print-failure-detection.git
   cd ~/klipper/klippy/extras/klipper-print-failure-detection
   sudo bash install.sh
   ```

## Post Installation Steps

- Open your browser and go to http://YOUR-IP:7126 to see the dashboard.
- Open the settings and input your printer camera ip (used in crowsnest).
- Adjust any other settings to your preference with testing to make sure it works well for your setup.
   - The main testing you need to find is your ideal trigger threshold value. The detection threshold value can be anything as long as its lower than the detection threshold value.


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
