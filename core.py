import cv2
import aiohttp
import asyncio
import time
import yaml
import numpy as np

class MJPEG:
    def __init__(self, camera_ip: str):
        self.camera_ip = camera_ip
    
    async def snap(self) -> bytes:
        async with aiohttp.ClientSession() as session:
            async with session.get(self.camera_ip, timeout=aiohttp.ClientTimeout(total=5.0)) as response:
                if response.status == 200:
                    return await response.read()
        return None

def detect_movement_background_subtraction(image1, image2, threshold=5000):
    """
    Detects movement between two images using background subtraction.
    If the number of changed pixels exceeds the threshold, it returns True (indicating failure).

    Args:
        image1: The first image (OpenCV image).
        image2: The second image (OpenCV image).
        threshold: The threshold of changed pixels that triggers failure detection.

    Returns:
        True if failure is detected, False otherwise.
    """
    bg_subtractor = cv2.createBackgroundSubtractorMOG2()
    fg_mask1 = bg_subtractor.apply(image1)
    fg_mask2 = bg_subtractor.apply(image2)

    # Calculate the number of changed pixels
    changed_pixels = cv2.countNonZero(fg_mask2)
    
    if changed_pixels > threshold:
        return True  # Failure detected
    return False

def load_settings():
    """Load configuration from the settings.yaml file"""
    with open("config.yaml", 'r') as file:
        settings = yaml.safe_load(file)
    return settings

async def main():
    # Load settings from config.yaml
    settings = load_settings()

    # Get camera IP and other settings from the config
    camera_ip = settings.get("camera_ip", "http://your-camera-ip")  # Default IP if not found
    failure_threshold = settings.get("failure_threshold", 5000)
    capture_delay = settings.get("capture_delay", 5)
    pause_on_failure = settings.get("pause_on_failure", True)

    camera = MJPEG(camera_ip)
    
    # Capture the first image
    image1 = await camera.snap()
    if not image1:
        print("Failed to capture image from camera.")
        return

    # Simulate a delay before capturing the second image
    await asyncio.sleep(capture_delay)

    # Capture the second image
    image2 = await camera.snap()
    if not image2:
        print("Failed to capture image from camera.")
        return

    # Convert to OpenCV images (this assumes MJPEG frames are JPEG or similar format)
    np_image1 = np.frombuffer(image1, np.uint8)
    np_image2 = np.frombuffer(image2, np.uint8)
    image1_cv = cv2.imdecode(np_image1, cv2.IMREAD_COLOR)
    image2_cv = cv2.imdecode(np_image2, cv2.IMREAD_COLOR)

    # Check for movement between the two images
    if detect_movement_background_subtraction(image1_cv, image2_cv, threshold=failure_threshold):
        print("Print failure detected!")
        if pause_on_failure:
            print("Pausing the print...")
            # Trigger action: Pause/Cancel print here (e.g., send G-code commands to the printer)
    else:
        print("No failure detected.")

# Run the detection asynchronously
asyncio.run(main())
