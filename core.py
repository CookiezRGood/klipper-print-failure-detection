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
# Moonraker Toolhead Motion Detection (Position-Based)
# ------------------------------------------------------------

last_position = None

async def is_toolhead_still(session, moonraker_url):
    """Toolhead is considered still if its position hasn't changed between checks."""
    global last_position
    try:
        url = f"{moonraker_url}/printer/objects/query?toolhead"
        async with session.get(url) as r:
            data = await r.json()

            pos = data["result"]["status"]["toolhead"]["position"]

            if last_position is None:
                last_position = pos
                return False  # First sample — assume moving

            movement = sum(abs(pos[i] - last_position[i]) for i in range(3))
            last_position = pos

            return movement < 0.01  # mm threshold

    except Exception as e:
        logging.error(f"Moonraker query failed: {e}")
        return False

# ------------------------------------------------------------
# SSIM (Structural Similarity) Implementation
# ------------------------------------------------------------

def ssim(img1, img2):
    """
    Compute SSIM between two grayscale images.
    Returns value in [0,1], where 1 means identical.
    """
    # SSIM constants
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    img1 = img1.astype(np.float64)
    img2 = img2.astype(np.float64)

    # Gaussian blur to reduce noise and estimate local statistics
    mu1 = cv2.GaussianBlur(img1, (11, 11), 1.5)
    mu2 = cv2.GaussianBlur(img2, (11, 11), 1.5)

    mu1_sq = mu1 * mu1
    mu2_sq = mu2 * mu2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = cv2.GaussianBlur(img1 * img1, (11, 11), 1.5) - mu1_sq
    sigma2_sq = cv2.GaussianBlur(img2 * img2, (11, 11), 1.5) - mu2_sq
    sigma12   = cv2.GaussianBlur(img1 * img2, (11, 11), 1.5) - mu1_mu2

    numerator   = (2 * mu1_mu2 + C1) * (2 * sigma12 + C2)
    denominator = (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)

    ssim_map = numerator / (denominator + 1e-9)
    return float(ssim_map.mean())

def preprocess(frame):
    """Convert to grayscale + light blur to kill MJPEG flicker."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    return gray

def detect_failure_ssim(frame1, frame2, ssim_threshold):
    """
    Returns True if SSIM drops below threshold.
    """
    g1 = preprocess(frame1)
    g2 = preprocess(frame2)

    score = ssim(g1, g2)
    logging.info(f"SSIM score: {score:.4f}")

    return score < ssim_threshold

# ------------------------------------------------------------
# Moonraker Print Actions
# ------------------------------------------------------------

async def perform_failure_action(action, session, moonraker_url):
    """Pause or cancel print via Moonraker."""
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

    check_interval = config.get("check_interval", 5)
    ssim_threshold = config.get("ssim_threshold", 0.97)
    needed         = config.get("consecutive_failures", 3)
    action         = config.get("on_failure", "pause")

    failure_count = 0
    last_frame = None

    async with aiohttp.ClientSession() as session:
        while True:
            still = await is_toolhead_still(session, moonraker_url)

            if not still:
                logging.info("Toolhead moving — skipping check.")
                await asyncio.sleep(check_interval)
                continue

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

            if detect_failure_ssim(last_frame, frame, ssim_threshold):
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
