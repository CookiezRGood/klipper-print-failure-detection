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
logging.info(">>> STARTING PLUGIN WITH STICKY REFERENCE + ASPECT RATIO <<<")

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')

default_config = {
    "camera_url": "http://127.0.0.1/webcam/?action=snapshot",
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 0.5,
    "ssim_threshold": 0.85,
    "mask_margin": 15,
    "max_mask_percent": 0.25,
    "consecutive_failures": 3,
    "on_failure": "pause",
    "aspect_ratio": "16:9"  # <--- NEW DEFAULT
}

config = default_config.copy()
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, 'r') as f:
            config.update(json.load(f))
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
    "current_ssim": 1.0,
    "failure_count": 0,
    "action_triggered": False 
}

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
            
            if klipper_state not in ["printing", "paused"]:
                state["status"] = "idle"
                state["last_stable_frame"] = None 
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

                if state["previous_gray"] is None or state["last_stable_frame"] is None:
                    state["previous_gray"] = gray
                    state["last_stable_frame"] = gray
                    time.sleep(1)
                    continue

                frame_delta = cv2.absdiff(state["previous_gray"], gray)
                thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
                mask_dilated = cv2.dilate(thresh, dilate_kernel, iterations=2)
                mask_coverage = cv2.countNonZero(mask_dilated) / (height * width)

                if mask_coverage > 0.001:
                    state["status"] = "monitoring"
                    state["current_ssim"] = 1.0 
                    
                    contours, _ = cv2.findContours(mask_dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if contours:
                        large_contours = [c for c in contours if cv2.contourArea(c) > 500]
                        cv2.drawContours(debug_img, large_contours, -1, (0, 255, 0), 2)
                        if large_contours:
                            c = max(large_contours, key=cv2.contourArea)
                            x, y, w, h = cv2.boundingRect(c)
                            cv2.putText(debug_img, "Motion", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                else:
                    if state["last_stable_frame"] is not None:
                        score = ssim(gray, state["last_stable_frame"])
                        state["current_ssim"] = score
                        threshold = float(config["ssim_threshold"])

                        if score >= threshold:
                            state["failure_count"] = 0
                            state["status"] = "checking"
                            state["last_stable_frame"] = gray 
                            cv2.putText(debug_img, f"MATCH: {int(score*100)}%", (10, 30), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                        else:
                            if state["failure_count"] < int(config["consecutive_failures"]):
                                state["failure_count"] += 1
                            
                            logging.info(f"Mismatch detected! Score: {score:.2f}. Retries: {state['failure_count']}")
                            
                            if state["failure_count"] >= int(config["consecutive_failures"]):
                                state["status"] = "failure_detected"
                                trigger_printer_action()
                            
                            cv2.putText(debug_img, f"MISMATCH: {int(score*100)}%", (10, 30), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

                state["previous_gray"] = gray
                state["debug_frame"] = debug_img
            else:
                state["status"] = "camera_error"

        except Exception as e:
            state["status"] = "connection_error"
            logging.error(f"Loop Error: {e}")
        
        time.sleep(float(config["check_interval"]))

monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

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
