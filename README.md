# Print Failure Detection Plugin for Klipper
# IN PROGRESS, DO NOT DOWNLOAD

This plugin uses image comparison (SSIM) to detect print failures. It is integrated with Mainsail for real-time monitoring of print status. This plugin works with a camera pointed at the print bed and uses dynamic motion-based masking to detect toolhead movement during printing.

## Features
- Detects print failures based on image comparison (SSIM)
- Real-time camera preview in Mainsail
- Adjustable thresholds for SSIM, stillness, and layer height
- Web-based interface for adjusting settings
- Debug overlays for toolhead masking

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
- Open the settings and input your printer camera ip (Default uses MJPEG style: /webcam/?action=snapshot)
- Adjust any other settings to your preference with testing to make sure it works well for your setup (works best with a static camera with no moving background)


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
