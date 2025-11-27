# Print Failure Detection Plugin for Klipper/Mainsail

## Local AI-Powered Failure Detection

This plugin uses advanced AI (TensorFlow Lite) to detect print failures in real-time. This plugin utilizes a computer vision model trained to recognize specific failure states like spaghetti, stringing, and zits.

It runs locally on your Raspberry Pi (or other Klipper host), integrates directly with Moonraker to pause or cancel failed prints, and provides a dedicated dashboard for monitoring up to two cameras simultaneously.

[AI Training Documentation](documents/AI_Training.md)

## Features

- **AI Failure Detection**: Uses a .tflite model (YOLOv8 Nano architecture) to identify failures with high accuracy.
- **Real-time Dashboard**: View live feeds with bounding box overlays showing exactly what the AI detected.

<img width="1271" height="795" alt="image" src="https://github.com/user-attachments/assets/98d8650e-d1eb-494f-8e06-f3e69f2f7ccf" />

- **Comprehensive Settings Menu**: Many configurable aspcets to the plugin to make it work the way you want/need.
- **Multi-Camera Support**: Monitor and detect failures on up to 2 cameras at once.

<img width="432" height="428" alt="image" src="https://github.com/user-attachments/assets/47c7af32-ce09-4da5-8266-52215345a113" />

- **Dual Thresholds**:
   - **Detection Threshold**: Visually highlights potential issues (Yellow box) without stopping the print.
   - **Trigger Threshold**: Automatically pauses or cancels the print when confidence is high (Red box) after a set number of retrys.
 
<img width="433" height="389" alt="image" src="https://github.com/user-attachments/assets/c3bfc437-82ba-4c7c-8fb3-29a8c085e711" />

- **Configurable Actions**: Choose to Warn, Pause, or Cancel print upon failure.

<img width="423" height="224" alt="image" src="https://github.com/user-attachments/assets/3fbc8ce3-c76a-4ae0-92e5-fe995f573ea7" />

- **Smart Idle Mode**: Automatically stops processing when the printer is idle to save CPU resources.

## Installation

Clone this repository to your printer and install:
   ```bash
   cd ~/klipper/klippy/extras/
   git clone https://github.com/CookiezRGood/klipper-print-failure-detection.git
   cd ~/klipper/klippy/extras/klipper-print-failure-detection
   sudo bash install.sh
   ```

**Note**: since this is an AI model running image processing locally on your 3D printer, it may be resource intensive. I optimized it as best I could for my setup so it may or may not work for you depending on how good of an MCU you have. I have a Raspberry Pi CM4 with 8GB memory and 32GB eMMC storage. While running, this plugin puts my CPU usage to around 40-50% so it should be small enough to not overload most machines.

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
