import logging
import threading
import time
import cv2
import numpy as np
import requests
import json
import os
from flask import Flask, jsonify, request, Response, send_from_directory

# --- LOGGING ---
log = logging.getLogger('werkzeug')
log.disabled = True
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logging.info(">>> STARTING PLUGIN: MULTI-CAMERA SUPPORT <<<")

try:
    from ultralytics import YOLO
except ImportError:
    logging.warning("CRITICAL: Ultralytics not found.")
    YOLO = None

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.pt')

default_config = {
    # New Camera Structure
    "cameras": [
        {"id": 0, "name": "Primary", "url": "http://127.0.0.1/webcam/?action=snapshot", "enabled": True},
        {"id": 1, "name": "Secondary", "url": "", "enabled": False}
    ],
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 2000,
    "ai_threshold": 0.50,
    "consecutive_failures": 1,
    "on_failure": "pause",
    "aspect_ratio": "16:9",
    "preview_refresh_rate": 500
}

config = default_config.copy()

# --- SETTINGS MIGRATION ---
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, 'r') as f:
            loaded = json.load(f)
            
            # Migrate old single camera_url to new structure
            if "camera_url" in loaded:
                logging.info("Migrating legacy settings to Multi-Camera format...")
                config["cameras"][0]["url"] = loaded["camera_url"]
                del loaded["camera_url"] # Remove old key
            
            config.update(loaded)
            
            # Ensure structure integrity
            if "cameras" not in config or not isinstance(config["cameras"], list):
                config["cameras"] = default_config["cameras"]
                
    except Exception: pass

def save_config_to_file():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception: pass

# --- GLOBAL STATE ---
# Now stores state PER CAMERA
state = {
    "status": "idle",
    "failure_count": 0,
    "action_triggered": False,
    "monitoring_active": False,
    "cameras": {
        0: {"frame": None, "score": 0.0},
        1: {"frame": None, "score": 0.0}
    }
}

# --- AI ENGINE ---
model = None

def load_model():
    global model
    if not os.path.exists(MODEL_PATH):
        logging.error(f"CRITICAL: model.pt NOT FOUND at {MODEL_PATH}")
        return False
    
    try:
        model = YOLO(MODEL_PATH, task='detect')
        logging.info("YOLOv8 Model Loaded.")
        return True
    except Exception as e:
        logging.error(f"Failed to load YOLO: {e}")
        return False

ai_ready = load_model()

# --- ROUTES ---
@app.route('/api/action/start', methods=['POST', 'GET'])
def action_start():
    state["monitoring_active"] = True
    state["failure_count"] = 0
    state["action_triggered"] = False
    logging.info("Monitoring STARTED")
    return jsonify({"success": True})

@app.route('/api/action/stop', methods=['POST', 'GET'])
def action_stop():
    state["monitoring_active"] = False
    logging.info("Monitoring STOPPED")
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
    logging.info(f"FAILURE CONFIRMED. Action: {action}")
    try:
        console_msg = f"M118 >>> FAILURE DETECTED! Action: {action.upper()} <<<"
        requests.post(f"{url}/printer/gcode/script", json={"script": console_msg})
        if action == "pause": requests.post(f"{url}/printer/print/pause")
        elif action == "cancel": requests.post(f"{url}/printer/print/cancel")
        state["action_triggered"] = True
    except Exception: pass

def background_monitor():
    while True:
        try:
            klipper_state = get_printer_state()
            if klipper_state in ["complete", "error", "cancelled"]:
                state["monitoring_active"] = False

            should_run = (klipper_state in ["printing", "paused"]) or state["monitoring_active"]

            # --- PROCESS EACH ENABLED CAMERA ---
            max_frame_score = 0.0
            any_cam_active = False

            for cam in config["cameras"]:
                cam_id = cam["id"]
                if not cam["enabled"] or not cam["url"]: 
                    continue
                
                any_cam_active = True
                
                # Fetch
                try:
                    resp = requests.get(cam["url"], timeout=2)
                    if resp.status_code == 200:
                        arr = np.frombuffer(resp.content, np.uint8)
                        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        
                        # If Idle, just save raw frame and skip AI
                        if not should_run:
                            state["cameras"][cam_id]["frame"] = img
                            state["cameras"][cam_id]["score"] = 0.0
                            continue

                        # Run AI
                        if model:
                            results = model(img, conf=float(config.get("ai_threshold", 0.5)), verbose=False)
                            result = results[0]
                            annotated = result.plot()
                            
                            # Check for boxes
                            if len(result.boxes) > 0:
                                top_conf = float(result.boxes.conf[0])
                                if top_conf > max_frame_score:
                                    max_frame_score = top_conf
                                state["cameras"][cam_id]["score"] = top_conf
                            else:
                                state["cameras"][cam_id]["score"] = 0.0
                            
                            state["cameras"][cam_id]["frame"] = annotated
                except Exception:
                    pass # Skip camera if connection fails

            if not should_run:
                state["status"] = "idle"
                state["failure_count"] = 0
                state["action_triggered"] = False
                time.sleep(1)
                continue

            # --- GLOBAL FAILURE LOGIC ---
            state["status"] = "monitoring"
            
            threshold = float(config.get("ai_threshold", 0.5))
            
            # If ANY camera sees failure > threshold
            if max_frame_score > threshold:
                if state["failure_count"] < int(config["consecutive_failures"]):
                    state["failure_count"] += 1
                
                logging.info(f"ALERT: Failure detected! Score: {max_frame_score:.2f} | Count: {state['failure_count']}")
                
                if state["failure_count"] >= int(config["consecutive_failures"]):
                    state["status"] = "failure_detected"
                    trigger_printer_action()
            else:
                state["failure_count"] = 0

        except Exception as e:
            logging.error(f"Loop Error: {e}")
        
        time.sleep(float(config["check_interval"]) / 1000.0)

monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

# Routes
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
    # Return max score across all cameras for the main bar
    max_score = max(state["cameras"][0]["score"], state["cameras"][1]["score"])
    return jsonify({
        "status": state["status"],
        "score": max_score,
        "failures": state["failure_count"],
        "max_retries": config["consecutive_failures"]
    })

@app.route('/api/frame/<int:cam_id>')
def get_frame(cam_id):
    # Safety check
    if cam_id not in state["cameras"] or state["cameras"][cam_id]["frame"] is None:
        blank = np.zeros((360, 640, 3), np.uint8)
        cv2.putText(blank, "NO SIGNAL", (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)
        _, buffer = cv2.imencode('.jpg', blank)
        return Response(buffer.tobytes(), mimetype='image/jpeg')
        
    _, buffer = cv2.imencode('.jpg', state["cameras"][cam_id]["frame"])
    return Response(buffer.tobytes(), mimetype='image/jpeg')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=7126, threaded=True)
