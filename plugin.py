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
logging.info(">>> STARTING PLUGIN: INTRUDER DETECTION <<<")

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')

default_config = {
    "camera_url": "http://127.0.0.1/webcam/?action=snapshot",
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 200,
    "ssim_threshold": 0.85,
    "mask_padding": -10,        # Negative numbers SHRINK the mask (tighter fit)
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
    logging.info("Signal Received: Monitoring STARTED (Learning Mode)")
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
                    cv2.putText(debug_img, "WAITING FOR START SIGNAL...", (20, 50), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 165, 0), 2)
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
                gray_sharp = cv2.GaussianBlur(gray, (5, 5), 0) 
                gray = cv2.GaussianBlur(gray, (21, 21), 0)

                if state["previous_gray"] is None:
                    state["previous_gray"] = gray
                    time.sleep(0.1)
                    continue

                frame_delta = cv2.absdiff(state["previous_gray"], gray)
                thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
                mask_dilated = cv2.dilate(thresh, np.ones((20,20), np.uint8), iterations=2)
                mask_coverage = cv2.countNonZero(mask_dilated) / (height * width)

                if state["last_stable_frame"] is None:
                    state["last_stable_frame"] = gray
                    state["ref_mask"] = np.zeros_like(gray)
                    state["previous_gray"] = gray
                    continue

                # --- MOTION DETECTED ---
                if mask_coverage > 0.001:
                    state["status"] = "monitoring"
                    state["current_ssim"] = 1.0 
                    
                    contours, _ = cv2.findContours(mask_dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    
                    valid_toolhead = False
                    
                    if contours:
                        c = max(contours, key=cv2.contourArea)
                        x, y, w, h = cv2.boundingRect(c)
                        
                        # A. LEARN PHASE
                        if state["toolhead_template"] is None:
                            if w > 20 and h > 20:
                                state["toolhead_template"] = gray_sharp[y:y+h, x:x+w].copy()
                                state["template_bbox"] = (w, h)
                                valid_toolhead = True
                                cv2.putText(debug_img, "LEARNING TOOLHEAD...", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                        
                        # B. SEARCH PHASE
                        else:
                            try:
                                res = cv2.matchTemplate(gray_sharp, state["toolhead_template"], cv2.TM_CCOEFF_NORMED)
                                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                                
                                if max_val > 0.6:
                                    valid_toolhead = True
                                    top_left = max_loc
                                    tw, th = state["template_bbox"]
                                    
                                    # --- TIGHT MASK LOGIC ---
                                    # Apply the mask padding to shrink the box
                                    pad = int(config.get("mask_padding", -10))
                                    mx, my, mw, mh = top_left[0], top_left[1], tw, th
                                    
                                    # Apply padding (Shrink if negative)
                                    mx -= pad
                                    my -= pad
                                    mw += (pad * 2)
                                    mh += (pad * 2)
                                    
                                    # Ensure boundaries
                                    mx, my = max(0, mx), max(0, my)
                                    mw, mh = min(width-mx, mw), min(height-my, mh)

                                    # Create the Precise Mask
                                    tight_mask = np.zeros_like(mask_dilated)
                                    cv2.rectangle(tight_mask, (mx, my), (mx+mw, my+mh), 255, -1)
                                    state["active_mask"] = tight_mask

                                    # Update Template (Evolution)
                                    new_crop = gray_sharp[top_left[1]:top_left[1]+th, top_left[0]:top_left[0]+tw]
                                    if new_crop.shape == state["toolhead_template"].shape:
                                        cv2.addWeighted(state["toolhead_template"], 0.95, new_crop, 0.05, 0, state["toolhead_template"])
                                    
                                    cv2.putText(debug_img, f"TOOLHEAD LOCKED ({max_val:.2f})", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                                else:
                                    cv2.putText(debug_img, f"UNKNOWN OBJECT ({max_val:.2f})", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                            except Exception: pass

                    # Draw Motion Blobs
                    cv2.drawContours(debug_img, contours, -1, (0, 255, 0), 2)
                    cv2.putText(debug_img, "Motion Tracking...", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                # --- STILL (CHECKING) ---
                else:
                    state["status"] = "checking"

                    if state["active_mask"] is None:
                        state["active_mask"] = np.zeros_like(gray)
                    
                    combined_mask = cv2.bitwise_or(state["active_mask"], state["ref_mask"])
                    
                    # 1. CHECK FOR INTRUDERS (Diff outside mask)
                    diff = cv2.absdiff(gray, state["last_stable_frame"])
                    diff[combined_mask > 0] = 0 # Ignore toolhead areas
                    _, diff_thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
                    
                    intruder_pixels = cv2.countNonZero(diff_thresh)
                    intruder_percent = intruder_pixels / (width * height)
                    
                    # 2. SSIM CHECK
                    gray_masked = gray.copy()
                    ref_masked = state["last_stable_frame"].copy()
                    gray_masked[combined_mask > 0] = 0
                    ref_masked[combined_mask > 0] = 0
                    score = ssim(gray_masked, ref_masked)
                    state["current_ssim"] = score

                    # --- DECISION LOGIC ---
                    # Fail if SSIM is low OR if Intruder Pixels are high
                    is_intruder = intruder_percent > 0.01 # 1% change on bed is significant
                    is_ssim_fail = score < float(config["ssim_threshold"])

                    if is_intruder or is_ssim_fail:
                        # FAILURE
                        if state["failure_count"] < int(config["consecutive_failures"]):
                            state["failure_count"] += 1
                        
                        if state["failure_count"] >= int(config["consecutive_failures"]):
                            state["status"] = "failure_detected"
                            trigger_printer_action()
                        
                        # VISUALIZE THE INTRUDER
                        debug_img[combined_mask > 0] = 0 # Draw black mask
                        # Draw red contours around the change
                        cnts, _ = cv2.findContours(diff_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        cv2.drawContours(debug_img, cnts, -1, (0, 0, 255), 2)
                        
                        msg = f"INTRUDER!" if is_intruder else f"SSIM FAIL: {int(score*100)}%"
                        cv2.putText(debug_img, msg, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    
                    else:
                        # SUCCESS (Safe to update reference)
                        state["failure_count"] = 0
                        state["last_stable_frame"] = gray 
                        state["ref_mask"] = state["active_mask"].copy() 
                        
                        debug_img[combined_mask > 0] = 0 
                        cv2.putText(debug_img, f"MATCH: {int(score*100)}%", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

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

# --- ROUTES (Unchanged) ---
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
