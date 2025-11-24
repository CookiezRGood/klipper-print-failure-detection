import logging
import threading
import time
import cv2
import numpy as np
import requests
from flask import Flask, jsonify, request, send_from_directory, Response

# Import your core logic
from core.motion import is_toolhead_still
from core.detection import ssim
from core.utils import log_info, log_warning

# Set up logging
logging.basicConfig(level=logging.INFO)
logging.info("Starting Print Failure Detection Plugin...")

app = Flask(__name__, static_folder='web_interface')

# Global State
state = {
    "latest_frame": None,
    "debug_frame": None,
    "last_position": [0, 0, 0],
    "status": "idle",
    "mask": None
}

config = {
    "ssim_threshold": 0.97,
    "stillness_threshold": 0.20,
    "layer_min_step": 0.15,
    "camera_url": "http://192.168.10.153/webcam/?action=snapshot",
    "check_interval": 1.0
}

# --- Background Processing Loop ---
def background_monitor():
    log_info("Background monitor started.")
    while True:
        try:
            # 1. Fetch Image
            resp = requests.get(config['camera_url'], timeout=2)
            if resp.status_code == 200:
                # Convert bytes to numpy image
                arr = np.frombuffer(resp.content, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                
                # Update global state (Raw Frame)
                state["latest_frame"] = img

                # 2. Create Debug Frame (Simulate Masking)
                # In a real scenario, you'd calculate the mask here based on motion.
                # For now, we'll draw a box to show it's working.
                debug_img = img.copy()
                
                # Example: Draw a red box in the center (The "Mask")
                h, w = debug_img.shape[:2]
                center_x, center_y = w // 2, h // 2
                cv2.rectangle(debug_img, (center_x - 50, center_y - 50), (center_x + 50, center_y + 50), (0, 0, 255), 2)
                cv2.putText(debug_img, "Motion Mask Area", (center_x - 60, center_y - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                
                state["debug_frame"] = debug_img
                state["status"] = "monitoring"
            else:
                state["status"] = "camera_error"

        except Exception as e:
            # log_warning(f"Monitor loop error: {e}")
            state["status"] = "error"
        
        time.sleep(config["check_interval"])

# Start the background thread
monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

# --- Routes ---

@app.route('/')
def serve_index():
    return send_from_directory('web_interface', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('web_interface', path)

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        data = request.json
        config.update(data)
        log_info("Settings updated")
    return jsonify(config)

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({"status": state["status"]})

@app.route('/api/latest_frame')
def latest_frame():
    # Helper to encode image to JPG bytes
    img = state["latest_frame"]
    if img is None:
        return "No image", 404
    _, buffer = cv2.imencode('.jpg', img)
    return Response(buffer.tobytes(), mimetype='image/jpeg')

@app.route('/api/debug_frame')
def debug_frame():
    # Returns the image with the MASK overlay
    img = state["debug_frame"]
    if img is None:
        return "No debug image", 404
    _, buffer = cv2.imencode('.jpg', img)
    return Response(buffer.tobytes(), mimetype='image/jpeg')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=7126, threaded=True)
