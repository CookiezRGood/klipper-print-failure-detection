import aiohttp
import asyncio
import cv2
import numpy as np
import yaml
import logging
import os
from datetime import datetime

# ------------------------------------------------------------
# Load configuration
# ------------------------------------------------------------

def load_config():
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

config = load_config()

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
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(self.url) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logging.warning(f"Camera returned HTTP {response.status}")
                        return None
            except Exception as e:
                logging.error(f"Camera error: {e}")
                return None

# ------------------------------------------------------------
# Moonraker Toolhead Motion Detection
# ------------------------------------------------------------

last_position = None

async def is_toolhead_still(session, moonraker_url):
    """Toolhead is still if 3-axis movement <0.01 mm."""
    global last_position
    try:
        url = f"{moonraker_url}/printer/objects/query?toolhead"
        async with session.get(url) as r:
            data = await r.json()
            pos = data["result"]["status"]["toolhead"]["position"]

            if last_position is None:
                last_position = pos
                return False

            movement = sum(abs(pos[i] - last_position[i]) for i in range(3))
            last_position = pos

            return movement < 0.01

    except Exception as e:
        logging.error(f"Moonraker error: {e}")
        return False

# ------------------------------------------------------------
# UNIVERSAL TOOLHEAD DETECTOR (FRAME DIFFERENCING)
# ------------------------------------------------------------

def detect_toolhead_motion_mask(prev_frame, frame, min_area=100, margin_px=10):
    """
    Universal toolhead detector using frame differencing.
    Detects the largest moving region between prev_frame and frame.
    """
    g1 = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Blur to remove noise
    g1 = cv2.GaussianBlur(g1, (9, 9), 0)
    g2 = cv2.GaussianBlur(g2, (9, 9), 0)

    diff = cv2.absdiff(g1, g2)

    # Threshold motion regions
    _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)

    # Clean up
    kernel = np.ones((5,5), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Largest moving contour = toolhead
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < min_area:
        return None

    x, y, w, h = cv2.boundingRect(largest)

    # Expand by margin
    x1 = max(x - margin_px, 0)
    y1 = max(y - margin_px, 0)
    x2 = min(x + w + margin_px, frame.shape[1])
    y2 = min(y + h + margin_px, frame.shape[0])

    mask = np.zeros((frame.shape[0], frame.shape[1]), dtype=np.uint8)
    mask[y1:y2, x1:x2] = 255
    return mask

# Apply toolhead mask to grayscale frame
def apply_dynamic_mask(gray, dyn_mask):
    if dyn_mask is None:
        return gray
    inv = cv2.bitwise_not(dyn_mask)
    return cv2.bitwise_and(gray, gray, mask=inv)

# ------------------------------------------------------------
# SSIM Implementation
# ------------------------------------------------------------

def ssim(img1, img2):
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    img1 = img1.astype(np.float64)
    img2 = img2.astype(np.float64)

    mu1 = cv2.GaussianBlur(img1, (11, 11), 1.5)
    mu2 = cv2.GaussianBlur(img2, (11, 11), 1.5)

    mu1_sq = mu1 * mu1
    mu2_sq = mu2 * mu2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = cv2.GGaussianBlur(img1 * img1, (11,11), 1.5) - mu1_sq
    sigma2_sq = cv2.GGaussianBlur(img2 * img2, (11,11), 1.5) - mu2_sq
    sigma12   = cv2.GGaussianBlur(img1 * img2, (11,11), 1.5) - mu1_mu2

    numerator   = (2 * mu1_mu2 + C1) * (2 * sigma12 + C2)
    denominator = (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)

    ssim_map = numerator / (denominator + 1e-9)
    return float(ssim_map.mean())

def preprocess(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5,5), 0)
    return gray

def detect_failure_ssim(frame1, frame2, threshold, dyn_mask, debug=False, debug_dir="/tmp/pfd_debug"):

    g1 = preprocess(frame1)
    g2 = preprocess(frame2)

    # Apply dynamic toolhead mask
    g1 = apply_dynamic_mask(g1, dyn_mask)
    g2 = apply_dynamic_mask(g2, dyn_mask)

    score = ssim(g1, g2)
    logging.info(f"SSIM score: {score:.4f}")

    # Debug overlay
    if debug:
        os.makedirs(debug_dir, exist_ok=True)
        overlay = frame2.copy()
        if dyn_mask is not None:
            red = np.zeros_like(overlay)
            red[:, :, 2] = 255
            mask3 = cv2.cvtColor(dyn_mask, cv2.COLOR_GRAY2BGR)
            overlay = np.where(mask3 > 0, (0.6 * overlay + 0.4 * red).astype(np.uint8), overlay)

        ts = datetime.now().strftime("%H%M%S_%f")
        cv2.imwrite(f"{debug_dir}/overlay_{ts}.jpg", overlay)

    return score < threshold

# ------------------------------------------------------------
# Moonraker Failure Action
# ------------------------------------------------------------

async def perform_failure_action(action, session, moonraker_url):
    try:
        if action == "pause":
            await session.post(f"{moonraker_url}/printer/print/pause")
            logging.warning(">>> Print paused due to detected failure")
        elif action == "cancel":
            await session.post(f"{moonraker_url}/printer/print/cancel")
            logging.warning(">>> Print canceled due to detected failure")
    except Exception as e:
        logging.error(f"Failed to send action: {e}")

# ------------------------------------------------------------
# Main Loop
# ------------------------------------------------------------

async def main():
    logging.info("Starting Print Failure Detection...")

    camera = Camera(config["camera_url"])
    moonraker_url = config["moonraker_url"]

    check_interval = config.get("check_interval", 5)
    threshold = config.get("ssim_threshold", 0.97)
    needed = config.get("consecutive_failures", 3)
    action = config.get("on_failure", "pause")

    dyn_cfg = config.get("dynamic_mask", {})
    dyn_enabled = dyn_cfg.get("enabled", True)
    min_area = dyn_cfg.get("min_area", 100)
    margin_px = dyn_cfg.get("margin_px", 10)
    debug_mask = dyn_cfg.get("debug_save_overlays", False)
    debug_dir = dyn_cfg.get("debug_dir", "/tmp/pfd_debug")

    failure_count = 0
    last_frame = None
    last_motion_mask = None

    async with aiohttp.ClientSession() as session:
        while True:

            frame_data = await camera.snap()
            if not frame_data:
                logging.warning("Camera returned no frame.")
                await asyncio.sleep(check_interval)
                continue

            frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)

            if last_frame is None:
                last_frame = frame
                await asyncio.sleep(check_interval)
                continue

            # If toolhead is moving → update motion mask
            moving = not await is_toolhead_still(session, moonraker_url)
            if moving and dyn_enabled:
                last_motion_mask = detect_toolhead_motion_mask(
                    last_frame, frame,
                    min_area=min_area,
                    margin_px=margin_px
                )

            # Only detect failure when toolhead STOPPED
            if not moving:
                if detect_failure_ssim(last_frame, frame, threshold, last_motion_mask,
                                       debug=debug_mask, debug_dir=debug_dir):
                    failure_count += 1
                    logging.warning(f"Failure suspicion {failure_count}/{needed}")
                else:
                    failure_count = 0

                if failure_count >= needed:
                    await perform_failure_action(action, session, moonraker_url)
                    failure_count = 0

            last_frame = frame
            await asyncio.sleep(check_interval)

if __name__ == "__main__":
    asyncio.run(main())
