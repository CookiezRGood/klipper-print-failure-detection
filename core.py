import aiohttp
import asyncio
import cv2
import numpy as np
import yaml
import time
import logging
from pathlib import Path

# ------------------------------------------------------------
# Load configuration
# ------------------------------------------------------------

def load_config():
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

config = load_config()

# Configure logging
logging.basicConfig(
    filename=config.get("log_path", "/tmp/klipper-pfd.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ------------------------------------------------------------
# Camera Snapshot Handler
# ------------------------------------------------------------

class Camera:
    def __init__(self, url):
        self.url = url

    async def snap(self):
        """Grab a snapshot image from the camera."""
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(self.url) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logging.warning(f"Camera returned status {response.status}")
                        return None
            except Exception as e:
                logging.error(f"Camera snapshot error: {e}")
                return None

# ------------------------------------------------------------
# Moonraker Toolhead Motion Detection
# ------------------------------------------------------------

async def is_toolhead_still(session, moonraker_url):
    """Returns True if toolhead velocity is 0."""
    try:
        url = f"{moonraker_url}/printer/objects/query?toolhead"
        async with session.get(url) as r:
            data = await r.json()
            vel = data["result"]["status"]["toolhead"]["velocity"]
            return vel == 0
    except Exception as e:
        logging.error(f"Moonraker query failed: {e}")
        return False

# ------------------------------------------------------------
# Failure Detection Logic
# ------------------------------------------------------------

def detect_difference(img1, img2, threshold):
    """Detects pixel differences between two images."""
    bg = cv2.createBackgroundSubtractorMOG2()

    # Warm-up with first image
    bg.apply(img1)

    # Apply to second
    mask = bg.apply(img2)

    # Count changed pixels
    diff_pixels = cv2.countNonZero(mask)

    logging.info(f"Pixel diff: {diff_pixels}")

    return diff_pixels > threshold


# ------------------------------------------------------------
# Moonraker Print Action
# ------------------------------------------------------------

async def perform_failure_action(action, session, moonraker_url):
    """Pause or cancel print through Moonraker."""
    try:
        if action == "pause":
            await session.post(f"{moonraker_url}/printer/print/pause")
            logging.warning(">>> Print paused due to detected failure!")
        elif action == "cancel":
            await session.post(f"{moonraker_url}/printer/print/cancel")
            logging.warning(">>> Print canceled due to detected failure!")
    except Exception as e:
        logging.error(f"Failed to send action to Moonraker: {e}")

# ------------------------------------------------------------
# Main Loop
# ------------------------------------------------------------

async def main():
    logging.info("Starting Klipper Print Failure Detection service...")

    camera = Camera(config["camera_url"])
    moonraker_url = config["moonraker_url"]
    check_interval = config["check_interval"]
    threshold = config["failure_threshold"]
    needed = config["consecutive_failures"]
    action = config["on_failure"]

    failure_count = 0
    last_frame = None

    async with aiohttp.ClientSession() as session:
        while True:
            # Check motion
            still = await is_toolhead_still(session, moonraker_url)

            if not still:
                logging.info("Toolhead moving — skipping check.")
                await asyncio.sleep(check_interval)
                continue

            # Capture image
            frame_data = await camera.snap()
            if not frame_data:
                logging.warning("No frame captured.")
                await asyncio.sleep(check_interval)
                continue

            np_frame = np.frombuffer(frame_data, np.uint8)
            frame = cv2.imdecode(np_frame, cv2.IMREAD_COLOR)

            if last_frame is None:
                last_frame = frame
                await asyncio.sleep(check_interval)
                continue

            # Compare frames
            if detect_difference(last_frame, frame, threshold):
                failure_count += 1
                logging.warning(f"Failure suspicion {failure_count}/{needed}")
            else:
                failure_count = 0

            # Trigger action if needed
            if failure_count >= needed:
                await perform_failure_action(action, session, moonraker_url)
                failure_count = 0

            last_frame = frame
            await asyncio.sleep(check_interval)

# ------------------------------------------------------------
# Run
# ------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())
