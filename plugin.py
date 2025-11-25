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
logging.info(">>> STARTING PLUGIN: TRIPLE CHECK LOGIC <<<")

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')

default_config = {
    "camera_url": "http://127.0.0.1/webcam/?action=snapshot",
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 200,
    "ssim_threshold": 0.85,
    "mask_margin": -5,
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
    
    # TRACKING STATE
    "best_motion_mask": None,   # Captures the largest shape seen during movement
    "toolhead_template": None,  # The visual ID of the toolhead
    "template_bbox": None,      # Size of the toolhead
    
    "current_ssim": 1.0,
    "failure_count": 0,
    "action_triggered": False,
    "monitoring_active": False,
    "just_finished_motion": False
}

@app.route('/api/action/start', methods=['POST', 'GET'])
def action_start():
    state["monitoring_active"] = True
    state["last_stable_frame"] = None 
    state["ref_mask"] = None
    state["best_motion_mask"] = None
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
                state["action_triggered"] = False
                state["best_motion_mask"] = None
                
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

            # --- ACTIVE LOOP ---
            resp = requests.get(config['camera_url'], timeout=2)
            if resp.status_code == 200:
                arr = np.frombuffer(resp.content, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                
                state["latest_frame"] = img.copy()
                debug_img = img.copy()
                height, width = img.shape[:2]

                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                gray_sharp = cv2.GaussianBlur(gray, (5, 5), 0) 
                gray_motion = cv2.GaussianBlur(gray, (21, 21), 0)

                if state["previous_gray"] is None:
                    state["previous_gray"] = gray_motion
                    time.sleep(0.1)
                    continue

                # Motion Detection
                frame_delta = cv2.absdiff(state["previous_gray"], gray_motion)
                thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
                mask_dilated = cv2.dilate(thresh, np.ones((15,15), np.uint8), iterations=2)
                mask_coverage = cv2.countNonZero(mask_dilated) / (height * width)

                # Init First Reference
                if state["last_stable_frame"] is None:
                    state["last_stable_frame"] = gray
                    state["ref_mask"] = np.zeros_like(gray)
                    state["previous_gray"] = gray_motion
                    state["best_motion_mask"] = np.zeros_like(gray)
                    continue

                # ============================
                # STATE: MOVING
                # ============================
                if mask_coverage > 0.001:
                    state["status"] = "monitoring"
                    state["current_ssim"] = 1.0 
                    state["just_finished_motion"] = True
                    
                    # LATCHING LOGIC:
                    # Always remember the "biggest" organic shape we saw during this movement.
                    # This solves the "Partial Mask" issue where stopping shrinks the mask.
                    if state["best_motion_mask"] is None:
                        state["best_motion_mask"] = mask_dilated.copy()
                    else:
                        # If current mask is bigger/better, update our "Best" guess
                        curr_pixels = cv2.countNonZero(mask_dilated)
                        best_pixels = cv2.countNonZero(state["best_motion_mask"])
                        if curr_pixels > best_pixels:
                            state["best_motion_mask"] = mask_dilated.copy()

                    # 1. LEARN PHASE (First big motion)
                    contours, _ = cv2.findContours(mask_dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if contours:
                        c = max(contours, key=cv2.contourArea)
                        x, y, w, h = cv2.boundingRect(c)
                        
                        if state["toolhead_template"] is None:
                            if w > 30 and h > 30:
                                state["toolhead_template"] = gray_sharp[y:y+h, x:x+w].copy()
                                state["template_bbox"] = (w, h)
                                cv2.putText(debug_img, "LEARNING ID...", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                    cv2.drawContours(debug_img, contours, -1, (0, 255, 0), 2)
                    cv2.putText(debug_img, "Motion...", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                # ============================
                # STATE: STOPPED (THE TRIPLE CHECK)
                # ============================
                else:
                    state["status"] = "checking"
                    
                    # Default: Assume failure unless proven otherwise
                    reset_accepted = False
                    
                    # Only attempt reset if we just stopped moving
                    if state["just_finished_motion"]:
                        
                        # CHECK 1: IDENTITY (Template Match)
                        valid_toolhead = False
                        new_head_mask = np.zeros_like(gray)
                        
                        if state["toolhead_template"] is not None:
                            try:
                                res = cv2.matchTemplate(gray_sharp, state["toolhead_template"], cv2.TM_CCOEFF_NORMED)
                                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                                
                                if max_val > 0.55:
                                    valid_toolhead = True
                                    
                                    # Update Template (Evolution)
                                    tx, ty = max_loc
                                    tw, th = state["template_bbox"]
                                    tx, ty = max(0, tx), max(0, ty)
                                    tw, th = min(width-tx, tw), min(height-ty, th)
                                    new_crop = gray_sharp[ty:ty+th, tx:tx+tw]
                                    cv2.addWeighted(state["toolhead_template"], 0.95, new_crop, 0.05, 0, state["toolhead_template"])
                                    
                                    # Create precise mask at the FOUND location (not motion location)
                                    # This fixes "Ghosting" by using the matched location
                                    # We use the "Best Motion Mask" shape, but centered on the match
                                    # (Actually, easier to just use the Best Motion Mask if it overlaps the match)
                                    
                                    # Simple approach: Use the Best Motion Mask captured during movement
                                    if state["best_motion_mask"] is not None:
                                        new_head_mask = state["best_motion_mask"].copy()
                                        
                                        # Apply Padding Setting
                                        pad = int(config.get("mask_margin", -5))
                                        if pad < 0:
                                            new_head_mask = cv2.erode(new_head_mask, np.ones((abs(pad),abs(pad)),np.uint8), iterations=1)
                                        elif pad > 0:
                                            new_head_mask = cv2.dilate(new_head_mask, np.ones((pad,pad),np.uint8), iterations=1)
                                    
                                    cv2.putText(debug_img, f"ID OK ({max_val:.2f})", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                                else:
                                    cv2.putText(debug_img, f"ID FAIL ({max_val:.2f})", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                            except: pass
                        
                        # CHECK 2 & 3: INTRUDER (Residuals)
                        # If identity passed, we verify the REST of the bed is clean
                        if valid_toolhead:
                            # Double Mask: Block Old Head AND New Head
                            # We use state['ref_mask'] (Old) and new_head_mask (New)
                            double_mask = cv2.bitwise_or(state["ref_mask"], new_head_mask)
                            
                            # Dilate for logic safety
                            safe_mask = cv2.dilate(double_mask, np.ones((20,20),np.uint8), iterations=1)
                            
                            # Compare Current vs Old Reference
                            diff = cv2.absdiff(gray, state["last_stable_frame"])
                            diff[safe_mask > 0] = 0 # Blind to toolheads
                            
                            _, diff_t = cv2.threshold(diff, 40, 255, cv2.THRESH_BINARY)
                            intruder_px = cv2.countNonZero(diff_t)
                            intruder_pct = intruder_px / (width * height)
                            
                            # If residual change is small (<0.5%), we accept the reset
                            if intruder_pct < 0.005:
                                reset_accepted = True
                                cv2.putText(debug_img, "BED CLEAN - RESET", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                            else:
                                cv2.putText(debug_img, "INTRUDER - REJECT", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                                # Draw the intruder
                                cnts, _ = cv2.findContours(diff_t, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                                cv2.drawContours(debug_img, cnts, -1, (0,0,255), 2)

                        # EXECUTE RESET
                        if reset_accepted:
                            state["last_stable_frame"] = gray
                            state["ref_mask"] = new_head_mask.copy()
                            state["failure_count"] = 0
                            state["best_motion_mask"] = None # Clear buffer
                            state["just_finished_motion"] = False
                        else:
                            # Reset Failed: We treat this frame as a standard check
                            # We do NOT clear just_finished_motion yet, we let it fail into the SSIM check
                            state["just_finished_motion"] = False 

                    # === STANDARD CHECK ===
                    # Compare Current vs Reference
                    # (If reset happened, Current == Reference, so Score = 1.0)
                    # (If reset failed, Current != Reference, so Score = Low)
                    
                    # Use current best mask (or empty if ID failed)
                    # Note: If reset failed, we use the OLD mask logic
                    
                    check_mask = state["ref_mask"].copy() # Only mask the KNOWN GOOD toolhead
                    # We explicitly do NOT mask the "New Object" if it wasn't verified as a toolhead
                    
                    gray_masked = gray.copy()
                    ref_masked = state["last_stable_frame"].copy()
                    gray_masked[check_mask > 0] = 0
                    ref_masked[check_mask > 0] = 0
                    
                    score = ssim(gray_masked, ref_masked)
                    state["current_ssim"] = score
                    
                    if score < float(config["ssim_threshold"]):
                        if state["failure_count"] < int(config["consecutive_failures"]):
                            state["failure_count"] += 1
                        if state["failure_count"] >= int(config["consecutive_failures"]):
                            state["status"] = "failure_detected"
                            trigger_printer_action()
                        
                        cv2.putText(debug_img, f"FAIL: {int(score*100)}%", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                    else:
                        state["failure_count"] = 0
                        cv2.putText(debug_img, f"MATCH: {int(score*100)}%", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    
                    # Draw Mask for debug
                    debug_img[check_mask > 0] = 0

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

# ... (Routes unchanged) ...
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
