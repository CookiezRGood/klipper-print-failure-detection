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
logging.info(">>> STARTING PLUGIN: ID VERIFICATION + SIZE FIX <<<")

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')

default_config = {
    "camera_url": "http://127.0.0.1/webcam/?action=snapshot",
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 200,
    "ssim_threshold": 0.85,
    "mask_margin": -10,         # Default -10 to shrink the mask
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
    "last_stable_frame": None,
    "ref_mask": None,
    "active_mask": None,
    "toolhead_template": None,
    "template_bbox": None,
    "current_ssim": 1.0,
    "failure_count": 0,
    "action_triggered": False,
    "monitoring_active": False 
}

@app.route('/api/action/start', methods=['POST', 'GET'])
def action_start():
    state["monitoring_active"] = True
    state["last_stable_frame"] = None 
    state["ref_mask"] = None
    state["active_mask"] = None
    state["toolhead_template"] = None
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
    except Exception: pass
    return "standby"

def trigger_printer_action():
    if state["action_triggered"]: return 
    action = config.get("on_failure", "nothing")
    url = config.get("moonraker_url", "http://127.0.0.1:7125").rstrip('/')
    logging.info(f"FAILURE CONFIRMED. Executing action: {action}")
    try:
        console_msg = f"M118 >>> FAILURE DETECTED! Action: {action.upper()} <<<"
        requests.post(f"{url}/printer/gcode/script", json={"script": console_msg})
        if action == "pause": requests.post(f"{url}/printer/print/pause")
        elif action == "cancel": requests.post(f"{url}/printer/print/cancel")
        state["action_triggered"] = True
    except Exception as e: logging.info(f"Failed to send command: {e}")

def background_monitor():
    logging.info("Background monitor started.")
    
    while True:
        try:
            klipper_state = get_printer_state()
            if klipper_state in ["complete", "error", "cancelled"]:
                state["monitoring_active"] = False

            should_run = (klipper_state in ["printing", "paused"]) or state["monitoring_active"]

            if not should_run:
                state["status"] = "idle"
                state["last_stable_frame"] = None 
                state["failure_count"] = 0
                state["toolhead_template"] = None
                state["action_triggered"] = False
                
                resp = requests.get(config['camera_url'], timeout=2)
                if resp.status_code == 200:
                    arr = np.frombuffer(resp.content, np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    state["latest_frame"] = img
                    state["debug_frame"] = img
                time.sleep(1) 
                continue 

            if not state["monitoring_active"]:
                state["status"] = "awaiting_macro"
                resp = requests.get(config['camera_url'], timeout=2)
                if resp.status_code == 200:
                    arr = np.frombuffer(resp.content, np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    debug_img = img.copy()
                    cv2.putText(debug_img, "WAITING FOR START SIGNAL...", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 165, 0), 2)
                    state["latest_frame"] = img
                    state["debug_frame"] = debug_img
                time.sleep(1)
                continue

            # --- ACTIVE DETECTION ---
            resp = requests.get(config['camera_url'], timeout=2)
            if resp.status_code == 200:
                arr = np.frombuffer(resp.content, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                state["latest_frame"] = img.copy()
                debug_img = img.copy()
                height, width = img.shape[:2]

                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                # Separate streams: Sharp for ID, Blurred for Motion
                gray_sharp = cv2.GaussianBlur(gray, (5, 5), 0) 
                gray_motion = cv2.GaussianBlur(gray, (21, 21), 0)

                if state["previous_gray"] is None:
                    state["previous_gray"] = gray_motion
                    time.sleep(0.1)
                    continue

                frame_delta = cv2.absdiff(state["previous_gray"], gray_motion)
                thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
                
                # Base Dilation to connect components (cables + head)
                # This creates the "Bloated" mask you disliked
                mask_dilated = cv2.dilate(thresh, np.ones((15,15), np.uint8), iterations=2)
                
                mask_coverage = cv2.countNonZero(mask_dilated) / (height * width)

                if state["last_stable_frame"] is None:
                    state["last_stable_frame"] = gray
                    state["ref_mask"] = np.zeros_like(gray)
                    state["previous_gray"] = gray_motion
                    continue

                # --- MOTION PHASE ---
                if mask_coverage > 0.001:
                    state["status"] = "monitoring"
                    state["current_ssim"] = 1.0 
                    
                    contours, _ = cv2.findContours(mask_dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    
                    if contours:
                        c = max(contours, key=cv2.contourArea)
                        x, y, w, h = cv2.boundingRect(c)
                        
                        valid_toolhead = False
                        
                        # 1. IDENTIFICATION (Template Matching)
                        if state["toolhead_template"] is None:
                            # Learn Phase: Assume first big motion is toolhead
                            if w > 30 and h > 30:
                                state["toolhead_template"] = gray_sharp[y:y+h, x:x+w].copy()
                                state["template_bbox"] = (w, h)
                                valid_toolhead = True
                                cv2.putText(debug_img, "LEARNING TOOLHEAD...", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                        else:
                            # Search Phase
                            try:
                                res = cv2.matchTemplate(gray_sharp, state["toolhead_template"], cv2.TM_CCOEFF_NORMED)
                                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                                
                                # Threshold 0.5 is lenient enough for angles, strict enough for hands
                                if max_val > 0.50:
                                    valid_toolhead = True
                                    # Adaptive Update (Evolution)
                                    tx, ty = max_loc
                                    th, tw = state["toolhead_template"].shape[:2]
                                    # Safety bounds
                                    tx, ty = max(0, tx), max(0, ty)
                                    tw, th = min(width-tx, tw), min(height-ty, th)
                                    
                                    new_crop = gray_sharp[ty:ty+th, tx:tx+tw]
                                    if new_crop.shape == state["toolhead_template"].shape:
                                        cv2.addWeighted(state["toolhead_template"], 0.95, new_crop, 0.05, 0, state["toolhead_template"])
                                    
                                    cv2.putText(debug_img, f"ID CONFIRMED ({max_val:.2f})", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                                else:
                                    cv2.putText(debug_img, f"UNKNOWN OBJECT ({max_val:.2f})", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                            except Exception: pass

                        # 2. MASK GENERATION (If Valid)
                        if valid_toolhead:
                            # Create the base mask from the organic contour
                            organic_mask = np.zeros_like(mask_dilated)
                            cv2.drawContours(organic_mask, [c], -1, 255, -1)
                            
                            # --- APPLY USER SETTING: MASK MARGIN ---
                            # This was ignored before due to name mismatch (padding vs margin)
                            # Now we use config['mask_margin']
                            margin = int(config.get("mask_margin", -10))
                            
                            if margin < 0:
                                # Negative = SHRINK (Erode)
                                kernel_size = abs(margin)
                                kernel = np.ones((kernel_size, kernel_size), np.uint8)
                                organic_mask = cv2.erode(organic_mask, kernel, iterations=1)
                            elif margin > 0:
                                # Positive = GROW (Dilate)
                                kernel = np.ones((margin, margin), np.uint8)
                                organic_mask = cv2.dilate(organic_mask, kernel, iterations=1)
                            
                            state["active_mask"] = organic_mask.copy()
                            
                            # Visual Feedback: Blue Outline is the FINAL mask
                            final_cnts, _ = cv2.findContours(organic_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                            cv2.drawContours(debug_img, final_cnts, -1, (255, 0, 0), 2) 
                        
                        else:
                            # If not valid toolhead, we DROP the mask.
                            # This exposes the object to the SSIM check in the next phase.
                            state["active_mask"] = None

                # --- STILL PHASE ---
                else:
                    state["status"] = "checking"
                    
                    # Use empty mask if toolhead wasn't found
                    current_mask = state["active_mask"] if state["active_mask"] is not None else np.zeros_like(gray)
                    
                    # Double Blind
                    combined_mask = cv2.bitwise_or(current_mask, state["ref_mask"])
                    
                    # SSIM Check
                    gray_masked = gray.copy()
                    ref_masked = state["last_stable_frame"].copy()
                    gray_masked[combined_mask > 0] = 0
                    ref_masked[combined_mask > 0] = 0
                    
                    score = ssim(gray_masked, ref_masked)
                    state["current_ssim"] = score
                    
                    threshold = float(config["ssim_threshold"])

                    if score >= threshold:
                        state["failure_count"] = 0
                        state["last_stable_frame"] = gray 
                        # Only update reference mask if we actually saw the toolhead
                        if state["active_mask"] is not None:
                            state["ref_mask"] = state["active_mask"].copy()
                        
                        debug_img[combined_mask > 0] = 0 
                        cv2.putText(debug_img, f"MATCH: {int(score*100)}%", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    else:
                        if state["failure_count"] < int(config["consecutive_failures"]):
                            state["failure_count"] += 1
                        if state["failure_count"] >= int(config["consecutive_failures"]):
                            state["status"] = "failure_detected"
                            trigger_printer_action()
                        
                        # Draw mask
                        debug_img[combined_mask > 0] = 0
                        
                        # Draw difference (Intruder)
                        diff = cv2.absdiff(gray, state["last_stable_frame"])
                        diff[combined_mask > 0] = 0
                        _, diff_t = cv2.threshold(diff, 40, 255, cv2.THRESH_BINARY)
                        cnts, _ = cv2.findContours(diff_t, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        cv2.drawContours(debug_img, cnts, -1, (0, 0, 255), 2)
                        
                        cv2.putText(debug_img, f"MISMATCH: {int(score*100)}%", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

                state["previous_gray"] = gray_motion
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

# Routes (Unchanged)
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
