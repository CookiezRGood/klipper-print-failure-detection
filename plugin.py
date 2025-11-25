import logging
import threading
import time
import cv2
import numpy as np
import requests
import json
import os
from flask import Flask, jsonify, request, send_from_directory, Response

try:
    from core.detection import ssim
except ImportError:
    def ssim(img1, img2): return 1.0

logging.basicConfig(level=logging.INFO)
logging.info(">>> STARTING PLUGIN: DOUBLE BLIND MASKING <<<")

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')

default_config = {
    "camera_url": "http://127.0.0.1/webcam/?action=snapshot",
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 200,      # Faster interval for better motion tracking
    "ssim_threshold": 0.85,
    "mask_margin": 20,          # Slightly larger margin to be safe
    "max_mask_percent": 0.25,
    "consecutive_failures": 3,
    "on_failure": "pause",
    "aspect_ratio": "16:9",
    "preview_refresh_rate": 500
}

config = default_config.copy()
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, 'r') as f:
            loaded = json.load(f)
            if "check_interval" in loaded and float(loaded["check_interval"]) < 10:
                loaded["check_interval"] = int(float(loaded["check_interval"]) * 1000)
            config.update(loaded)
    except Exception: pass

def save_config_to_file():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception: pass

state = {
    "latest_frame": None,
    "debug_frame": None,
    "status": "idle",
    "previous_gray": None,
    
    # DOUBLE BLIND STATE VARIABLES
    "last_stable_frame": None,  # The "Golden Standard" image
    "ref_mask": None,           # The mask used for the Golden Standard
    "active_mask": None,        # The currently detected toolhead position
    
    "current_ssim": 1.0,
    "failure_count": 0,
    "action_triggered": False,
    "monitoring_active": False 
}

# --- API TRIGGERS ---
@app.route('/api/action/start', methods=['POST', 'GET'])
def action_start():
    state["monitoring_active"] = True
    # Reset everything on start
    state["last_stable_frame"] = None 
    state["ref_mask"] = None
    state["active_mask"] = None
    state["failure_count"] = 0
    logging.info("Signal Received: Monitoring STARTED")
    return jsonify({"success": True})

@app.route('/api/action/stop', methods=['POST', 'GET'])
def action_stop():
    state["monitoring_active"] = False
    logging.info("Signal Received: Monitoring STOPPED")
    return jsonify({"success": True})

def get_printer_state():
    url = config.get("moonraker_url", "http://127.0.0.1:7125").rstrip('/')
    try:
        r = requests.get(f"{url}/printer/objects/query?print_stats", timeout=0.5)
        if r.status_code == 200:
            data = r.json()
            return data.get("result", {}).get("status", {}).get("print_stats", {}).get("state", "standby")
    except Exception:
        pass
    return "standby"

def trigger_printer_action():
    if state["action_triggered"]: return 

    action = config.get("on_failure", "nothing")
    url = config.get("moonraker_url", "http://127.0.0.1:7125").rstrip('/')
    
    logging.info(f"FAILURE CONFIRMED. Executing action: {action}")

    try:
        console_msg = f"M118 >>> FAILURE DETECTED! Action: {action.upper()} <<<"
        requests.post(f"{url}/printer/gcode/script", json={"script": console_msg})

        if action == "pause":
            requests.post(f"{url}/printer/print/pause")
        elif action == "cancel":
            requests.post(f"{url}/printer/print/cancel")
        
        state["action_triggered"] = True
        
    except Exception as e:
        logging.info(f"Failed to send command to Moonraker: {e}")

def background_monitor():
    logging.info("Background monitor started.")
    
    while True:
        try:
            klipper_state = get_printer_state()
            
            # 1. AUTO RESET
            if klipper_state in ["complete", "error", "cancelled"]:
                state["monitoring_active"] = False

            # 2. IDLE / SLEEP LOGIC
            should_run = (klipper_state in ["printing", "paused"]) or state["monitoring_active"]

            if not should_run:
                state["status"] = "idle"
                # Reset memory
                state["last_stable_frame"] = None 
                state["ref_mask"] = None
                state["active_mask"] = None
                state["failure_count"] = 0
                state["action_triggered"] = False
                
                resp = requests.get(config['camera_url'], timeout=2)
                if resp.status_code == 200:
                    arr = np.frombuffer(resp.content, np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    state["latest_frame"] = img
                    state["debug_frame"] = img
                
                time.sleep(1) 
                continue 

            # 3. AWAITING TRIGGER
            if not state["monitoring_active"]:
                state["status"] = "awaiting_macro"
                resp = requests.get(config['camera_url'], timeout=2)
                if resp.status_code == 200:
                    arr = np.frombuffer(resp.content, np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    debug_img = img.copy()
                    cv2.putText(debug_img, "WAITING FOR START SIGNAL...", (20, 50), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 165, 0), 2)
                    state["latest_frame"] = img
                    state["debug_frame"] = debug_img
                time.sleep(1)
                continue

            # 4. ACTIVE DETECTION
            dilate_kernel = np.ones((int(config['mask_margin']), int(config['mask_margin'])), np.uint8)
            resp = requests.get(config['camera_url'], timeout=2)
            
            if resp.status_code == 200:
                arr = np.frombuffer(resp.content, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                
                state["latest_frame"] = img.copy()
                debug_img = img.copy()
                height, width = img.shape[:2]

                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)

                # Initialize Previous Frame
                if state["previous_gray"] is None:
                    state["previous_gray"] = gray
                    time.sleep(0.1)
                    continue

                # --- MOTION CALCULATION ---
                frame_delta = cv2.absdiff(state["previous_gray"], gray)
                thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
                mask_dilated = cv2.dilate(thresh, dilate_kernel, iterations=2)
                mask_coverage = cv2.countNonZero(mask_dilated) / (height * width)

                # Initialize First Reference (Empty Mask)
                if state["last_stable_frame"] is None:
                    state["last_stable_frame"] = gray
                    state["ref_mask"] = np.zeros_like(gray) # No toolhead mask yet
                    state["previous_gray"] = gray
                    continue

                # --- IS MOVING? ---
                if mask_coverage > 0.001:
                    state["status"] = "monitoring"
                    state["current_ssim"] = 1.0 
                    
                    # SAVE THE ACTIVE MASK (Where the head IS right now)
                    state["active_mask"] = mask_dilated.copy()

                    # Draw Visualization
                    contours, _ = cv2.findContours(mask_dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(debug_img, contours, -1, (0, 255, 0), 2)
                    cv2.putText(debug_img, "Motion Tracking...", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                # --- IS STILL? ---
                else:
                    # Ensure we have masks to work with
                    if state["active_mask"] is None:
                        state["active_mask"] = np.zeros_like(gray)
                    
                    # --- DOUBLE BLIND MASKING ---
                    # 1. Combine Current Head Mask + Old Reference Head Mask
                    combined_mask = cv2.bitwise_or(state["active_mask"], state["ref_mask"])
                    
                    # 2. Black out these areas in BOTH images
                    # This removes the toolhead from the equation entirely
                    gray_masked = gray.copy()
                    ref_masked = state["last_stable_frame"].copy()
                    
                    gray_masked[combined_mask > 0] = 0
                    ref_masked[combined_mask > 0] = 0

                    # 3. Compare the Remaining (Print Bed) areas
                    score = ssim(gray_masked, ref_masked)
                    state["current_ssim"] = score
                    threshold = float(config["ssim_threshold"])

                    if score >= threshold:
                        # --- EVOLUTION (Valid) ---
                        state["failure_count"] = 0
                        state["status"] = "checking"
                        
                        # Update Reference to this new valid state
                        state["last_stable_frame"] = gray 
                        state["ref_mask"] = state["active_mask"].copy() # Save THIS head position for next time
                        
                        # Debug: Show what we are comparing (The Masked Result)
                        # We overlay the masked black areas on the debug image
                        debug_img[combined_mask > 0] = 0 
                        cv2.putText(debug_img, f"MATCH: {int(score*100)}%", (10, 30), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    else:
                        # --- REVOLUTION (Failure) ---
                        if state["failure_count"] < int(config["consecutive_failures"]):
                            state["failure_count"] += 1
                        
                        if state["failure_count"] >= int(config["consecutive_failures"]):
                            state["status"] = "failure_detected"
                            trigger_printer_action()
                        
                        # Show the masked areas to prove we ignored the head
                        debug_img[combined_mask > 0] = 0
                        cv2.putText(debug_img, f"MISMATCH: {int(score*100)}%", (10, 30), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

                state["previous_gray"] = gray
                state["debug_frame"] = debug_img
            else:
                state["status"] = "camera_error"

        except Exception as e:
            state["status"] = "connection_error"
            logging.error(f"Loop Error: {e}")
        
        sleep_ms = float(config.get("check_interval", 500))
        time.sleep(sleep_ms / 1000.0)

monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

# --- ROUTES ---
@app.route('/')
def serve_index(): return send_from_directory('web_interface', 'index.html')

@app.route('/<path:path>')
def serve_static(path): return send_from_directory('web_interface', path)

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        config.update(request.json)
        save_config_to_file()
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
    img = state["latest_frame"] if state["latest_frame"] is not None else np.zeros((360, 640, 3), np.uint8)
    _, buffer = cv2.imencode('.jpg', img)
    return Response(buffer.tobytes(), mimetype='image/jpeg')

@app.route('/api/debug_frame')
def debug_frame():
    img = state["debug_frame"] if state["debug_frame"] is not None else np.zeros((360, 640, 3), np.uint8)
    _, buffer = cv2.imencode('.jpg', img)
    return Response(buffer.tobytes(), mimetype='image/jpeg')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=7126, threaded=True)
