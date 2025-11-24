import logging
import threading
import time
import cv2
import numpy as np
import requests
import json
import os
from flask import Flask, jsonify, request, send_from_directory, Response

# Import SSIM logic
try:
    from core.detection import ssim
except ImportError:
    def ssim(img1, img2): return 1.0

logging.basicConfig(level=logging.INFO)
logging.info("Starting Print Failure Detection Plugin...")

app = Flask(__name__, static_folder='web_interface')

# --- CONFIGURATION MANAGEMENT ---
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')

# 1. Universal Defaults (The "Generic Base")
default_config = {
    "camera_url": "http://YOUR_PRINTER_IP/webcam/?action=snapshot",
    "check_interval": 0.5,
    "ssim_threshold": 0.90,
    "stillness_threshold": 0.20,
    "mask_margin": 15,
    "max_mask_percent": 0.25,
    "consecutive_failures": 3
}

# 2. Load User Settings (Persistent)
config = default_config.copy()
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, 'r') as f:
            user_settings = json.load(f)
            config.update(user_settings)
            logging.info("Loaded user settings.")
    except Exception as e:
        logging.error(f"Failed to load settings file: {e}")

def save_config_to_file():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        logging.info("Settings saved to disk.")
    except Exception as e:
        logging.error(f"Failed to save settings: {e}")

# --- GLOBAL STATE ---
state = {
    "latest_frame": None,
    "debug_frame": None,
    "status": "idle",
    "previous_gray": None,
    "last_stable_frame": None,
    "current_ssim": 1.0,
    "failure_count": 0
}

def background_monitor():
    log_info("Background monitor started.")
    
    while True:
        try:
            # Update Kernel based on current margin setting
            dilate_kernel = np.ones((int(config['mask_margin']), int(config['mask_margin'])), np.uint8)
            
            resp = requests.get(config['camera_url'], timeout=2)
            if resp.status_code == 200:
                arr = np.frombuffer(resp.content, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                
                state["latest_frame"] = img.copy()
                debug_img = img.copy()
                height, width = img.shape[:2]
                total_pixels = height * width

                # Motion Detection
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)

                if state["previous_gray"] is None:
                    state["previous_gray"] = gray
                    state["last_stable_frame"] = gray
                    time.sleep(1)
                    continue

                frame_delta = cv2.absdiff(state["previous_gray"], gray)
                thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
                mask_dilated = cv2.dilate(thresh, dilate_kernel, iterations=2)

                mask_pixels = cv2.countNonZero(mask_dilated)
                mask_coverage = mask_pixels / total_pixels

                # Logic Fork
                if mask_coverage > 0.001:
                    # MOTION: Reset and Monitor
                    state["status"] = "monitoring"
                    state["current_ssim"] = 1.0
                    state["failure_count"] = 0
                    state["last_stable_frame"] = gray 
                    
                    contours, _ = cv2.findContours(mask_dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if contours:
                        large_contours = [c for c in contours if cv2.contourArea(c) > 500]
                        overlay = debug_img.copy()
                        cv2.drawContours(overlay, large_contours, -1, (0, 255, 0), -1)
                        cv2.addWeighted(overlay, 0.3, debug_img, 0.7, 0, debug_img)
                        
                        if large_contours:
                            c = max(large_contours, key=cv2.contourArea)
                            x, y, w, h = cv2.boundingRect(c)
                            cv2.putText(debug_img, "Mask Active", (x, y - 10), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                else:
                    # STILL: Check SSIM
                    if state["last_stable_frame"] is not None:
                        score = ssim(gray, state["last_stable_frame"])
                        state["current_ssim"] = score

                        if score < float(config["ssim_threshold"]):
                            if state["failure_count"] < int(config["consecutive_failures"]):
                                state["failure_count"] += 1
                            
                            if state["failure_count"] >= int(config["consecutive_failures"]):
                                state["status"] = "failure_detected"
                        else:
                            state["failure_count"] = 0
                            state["status"] = "checking"
                            state["last_stable_frame"] = gray 

                state["previous_gray"] = gray
                state["debug_frame"] = debug_img
            else:
                state["status"] = "camera_error"

        except Exception as e:
            # If camera fails (e.g., wrong IP), we don't crash, just wait
            state["status"] = "connection_error"
        
        time.sleep(float(config["check_interval"]))

def log_info(msg):
    logging.info(msg)

monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

@app.route('/')
def serve_index(): return send_from_directory('web_interface', 'index.html')

@app.route('/<path:path>')
def serve_static(path): return send_from_directory('web_interface', path)

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        data = request.json
        config.update(data)
        save_config_to_file() # Save to disk immediately
        return jsonify({"status": "saved", "config": config})
    return jsonify(config)

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({
        "status": state["status"],
        "ssim": state["current_ssim"],
        "failures": state["failure_count"],
        "max_retries": config["consecutive_failures"]
    })

@app.route('/api/latest_frame')
def latest_frame():
    img = state["latest_frame"]
    if img is None: 
        # Return a black image if no camera found yet
        blank = np.zeros((360, 640, 3), np.uint8)
        _, buffer = cv2.imencode('.jpg', blank)
        return Response(buffer.tobytes(), mimetype='image/jpeg')
    _, buffer = cv2.imencode('.jpg', img)
    return Response(buffer.tobytes(), mimetype='image/jpeg')

@app.route('/api/debug_frame')
def debug_frame():
    img = state["debug_frame"]
    if img is None: 
        blank = np.zeros((360, 640, 3), np.uint8)
        cv2.putText(blank, "NO SIGNAL", (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)
        _, buffer = cv2.imencode('.jpg', blank)
        return Response(buffer.tobytes(), mimetype='image/jpeg')
    _, buffer = cv2.imencode('.jpg', img)
    return Response(buffer.tobytes(), mimetype='image/jpeg')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=7126, threaded=True)
