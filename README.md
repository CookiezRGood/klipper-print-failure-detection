<h1 align="center">AI Print Failure Detection Plugin for Klipper/Mainsail</h1>

<p align="center">
<img width="300" height="300" alt="Print Failure Detection Logo 3" src="https://github.com/user-attachments/assets/1e019f25-1e45-4589-92cd-c2b0f8e45231" />
</p/
## Local AI-Powered Failure Detection

This plugin uses an optimized TensorFlow Lite model to detect print failures in real time. It runs fully locally on your Klipper host, requires no cloud services, and directly integrates with Moonraker to pause or cancel prints automatically.

The plugin includes a complete monitoring dashboard with live camera feeds, visual failure overlays, multi-zone masking, and support for one or two cameras at once.

[AI Training Documentation](documents/AI_Training.md)

## Prerequisites

- Crowsnest (camera functionality)
   - https://github.com/mainsail-crew/crowsnest
- Gcode Shell Commands (via kiauh; only needed for auto-start macro)
   - https://github.com/dw-0/kiauh/tree/master

## Features

- **AI Failure Detection**: Uses a .tflite YOLO-based model to identify failures such as spaghetti, stringing, and zits.

<img width="627" height="562" alt="image" src="https://github.com/user-attachments/assets/05b6f73e-8a87-4586-993d-4e8ce503b709" />

<br><br>

- **Real-Time Web Dashboard**: View live camera feeds with bounding box overlays showing what the AI detects.

<img width="1852" height="962" alt="image" src="https://github.com/user-attachments/assets/52b18d96-7d69-4b79-b3e8-78f4c3f75725" />

<br><br>

- **Comprehensive Settings Menu**: Many configurable aspects to tailor the plugin to your printer and environment.

<img width="710" height="919" alt="image" src="https://github.com/user-attachments/assets/a274d5f0-8cca-461b-8ce2-6c215ab8642f" />

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

![masking](https://github.com/user-attachments/assets/c0bfe96e-2dd3-4e3f-9f32-8f80bde18cd5)

<br><br>

- **Smart Idle Mode**: Automatically suspends AI processing when the printer is idle to reduce CPU usage.

- **Manual Start Button**: Starts AI monitoring process (useful for testing and finding ideal detection percentages).

- **Auto-Start Macro**: Provided macro can be inserted at the end of your `PRINT_START` to automatically enable the detection system (prevents high CPU usage during things like leveling and meshing).

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
- Add the following macros to your printer to allow auto-starting of the plugin while printing:
   - Place the `ENABLE_AI_MONITOR` and `DISABLE_AI_MONITOR` macros at the end of your `PRINT_START` and wherever you want in your `PRINT_END` macro.

```bash
[gcode_macro ENABLE_AI_MONITOR]
gcode:
    RUN_SHELL_COMMAND CMD=ai_monitor_enable
    M118 AI Failure Detection Started

[gcode_macro DISABLE_AI_MONITOR]
gcode:
    RUN_SHELL_COMMAND CMD=ai_monitor_disable
    M118 AI Failure Detection Stopped

[gcode_shell_command ai_monitor_enable]
command: curl -X POST http://127.0.0.1:7126/api/action/start_from_macro
timeout: 5

[gcode_shell_command ai_monitor_disable]
command: curl -X POST http://127.0.0.1:7126/api/action/stop
timeout: 5
```


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
