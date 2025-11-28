# Print Failure Detection Plugin for Klipper/Mainsail

## Local AI-Powered Failure Detection

This plugin uses an optimized TensorFlow Lite model to detect print failures in real time. It runs fully locally on your Klipper host, requires no cloud services, and directly integrates with Moonraker to pause or cancel prints automatically.

The plugin includes a complete monitoring dashboard with live camera feeds, visual failure overlays, multi-zone masking, and support for one or two cameras at once.

[AI Training Documentation](documents/AI_Training.md)

## Features

- **AI Failure Detection**: Uses a .tflite YOLO-based model to identify failures such as spaghetti, stringing, and zits.

<img width="816" height="576" alt="image" src="https://github.com/user-attachments/assets/fb41211b-88c3-49b5-b405-ff75d69d8de5" />

- **Real-time Dashboard**: View live camera feeds with bounding box overlays showing what the AI detects.

<img width="1225" height="857" alt="image" src="https://github.com/user-attachments/assets/56ebd5e4-89cc-492f-8671-b118ef7f1b07" />

- **Comprehensive Settings Menu**: Many configurable aspects to tailor the plugin to your printer and environment.

- **Multi-Camera Support**: Monitor and analyze up to **two cameras simultaneously**, each with its own prediction score and mask zones.

<img width="432" height="428" alt="image" src="https://github.com/user-attachments/assets/47c7af32-ce09-4da5-8266-52215345a113" />

- **Multi-Zone Masking System**:
   - Click-and-drag to define **any number of mask rectangles** directly on the camera feed.
   - Per-camera mask storage for dual-camera setups.
   - Masks hide irrelevant regions from AI analysis.
   - Right-click to delete individual zones.
   - “Clear Masks” button for quick resets.

![masking](https://github.com/user-attachments/assets/018157ec-98e1-4d96-aeb0-8be1189f718a)

- **Dual Thresholds**:
   - **Detection Threshold** (yellow): highlights possible issues.
   - **Trigger Threshold** (red): automatically pauses or cancels the print after a configurable number of retries.

<img width="433" height="389" alt="image" src="https://github.com/user-attachments/assets/c3bfc437-82ba-4c7c-8fb3-29a8c085e711" />

- **Configurable Actions**: Choose to warn only, pause, or cancel the print when a failure is detected.

<img width="423" height="224" alt="image" src="https://github.com/user-attachments/assets/3fbc8ce3-c76a-4ae0-92e5-fe995f573ea7" />

- **Smart Idle Mode**: Automatically suspends AI processing when the printer is idle to reduce CPU usage.
