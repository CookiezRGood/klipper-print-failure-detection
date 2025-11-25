# Print Failure Detection Plugin for Klipper
# IN PROGRESS, DO NOT DOWNLOAD

This plugin uses image comparison (SSIM) to detect print failures. It is integrated with Mainsail for real-time monitoring of print status. This plugin works with a camera pointed at the print bed and uses dynamic motion-based masking to detect toolhead movement during printing.

## Features
- Detects print failures based on image comparison (SSIM).
- Real-time camera preview in Mainsail.
- Adjustable thresholds for SSIM, stillness, and layer height.
- Web-based interface for adjusting settings.
- Debug overlays for toolhead masking.

## Installation

1. Clone this repository to your Raspberry Pi:
   ```bash
   cd ~/klipper/klippy/extras/
   git clone https://github.com/CookiezRGood/klipper-print-failure-detection.git
   ```

2. Run the installation script:
   ```bash
   cd ~/klipper/klippy/extras/klipper-print-failure-detection
   sudo install.sh
   ```
