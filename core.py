import aiohttp
import asyncio
import cv2
import numpy as np
import yaml
import logging

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
# Mask processing for SSIM
# ------------------------------------------------------------

def apply_mask(gray, mask_cfg):
    """
    Masks out top/bottom/left/right rectangular regions.
    """
    h, w = gray.shape
    mask = np.ones((h, w), dtype=np.uint8) * 255

    top    = mask_cfg.get("top", 0)
    bottom = mask_cfg.get("bottom", 0)
    left   = mask_cfg.get("left", 0)
    right  = mask_cfg.get("right", 0)

    if top > 0:
        mask[:top, :] = 0
    if bottom > 0:
        mask[h-bottom:, :] = 0
    if left > 0:
        mask[:, :left] = 0
    if right > 0:
        mask[:, w-right:] = 0

    return cv2.bitwise_and(gray, gray, mask=mask)


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

    sigma1_sq = cv2.GaussianBlur(img1 * img1, (11,11), 1.5) - mu1_sq
    sigma2_sq = cv2.GaussianBlur(img2 * img2, (11,11), 1.5) - mu2_sq
    sigma12   = cv2.GaussianBlur(img1 * img2, (11,11), 1.5) - mu1_mu2

    numerator   = (2 * mu1_mu2 + C1) * (2 * sigma12 + C2)
    denominator = (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)

    ssim_map = numerator / (denominator + 1e-9)
    return float(ssim_map.mean())

def preprocess(frame):
    """grayscale + light blur to kill MJPEG noise"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5,5), 0)
    return gray

def detect_failure_ssim(frame1, frame2, threshold, mask_cfg):
    g1 = preprocess(frame1)
    g2 = preprocess(frame2)

    g1 = apply_mask(g1, mask_cfg)
    g2 = apply_mask(g2, mask_cfg)

    score = ssim(g1, g2)
    logging.info(f"SSIM score: {score:.4f}")

    return score < threshold

# ------------------------------------------------------------
# Moonraker Print Actions
# ------------------------------------------------------------

async def perform_failure_action(action, session, moonraker_url):
    try:
        if action == "pause":
            await session.post(f"{moonraker_url}/printer/print/pause")
            logging.warning(">>> Print paused due to failure")

        elif action == "cancel":
            await session.post(f"{moonraker_url}/printer/print/cancel")
            logging.warning(">>> Print canceled due to failure")

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

    mask_cfg = config.get("mask", {})

    failure_count = 0
    last_frame = None

    async with aiohttp.ClientSession() as session:
        while True:

            # 1. toolhead still?
            still = await is_toolhead_still(session, moonraker_url)

            if not still:
                logging.info("Toolhead moving, skipping.")
                await asyncio.sleep(check_interval)
                continue

            # 2. snapshot
            frame_data = await camera.snap()
            if not frame_data:
                logging.warning("Camera returned no frame.")
                await asyncio.sleep(check_interval)
                continue

            frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8),
                                 cv2.IMREAD_COLOR)

            if last_frame is None:
                last_frame = frame
                await asyncio.sleep(check_interval)
                continue

            # 3. SSIM detection
            if detect_failure_ssim(last_frame, frame, threshold, mask_cfg):
                failure_count += 1
                logging.warning(f"Failure suspicion {failure_count}/{needed}")
            else:
                failure_count = 0

            # 4. Trigger action
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
