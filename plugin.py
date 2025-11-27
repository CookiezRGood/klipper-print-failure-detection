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
logging.info(">>> STARTING PLUGIN: MULTI-CAM + MANUAL DRAWING <<<")

# Import YOLO Engine
try:
    from ultralytics import YOLO
except ImportError:
    logging.warning("CRITICAL: Ultralytics not found. AI will not work.")
    YOLO = None

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.pt')

# --- CLASS NAMES ---
CLASS_NAMES = ["Spaghetti", "Stringing", "Zits"]

default_config = {
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
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, 'r') as f:
            loaded = json.load(f)
            # Migration for old config style
            if "camera_url" in loaded:
                config["cameras"][0]["url"] = loaded["camera_url"]
            config.update(loaded)
    except Exception: pass

def save_config_to_file():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception: pass

# --- GLOBAL STATE ---
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
        logging.info("Loading YOLOv8 Model...")
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

def trigger_printer_action(reason="Failure"):
    if state["action_triggered"]: return 
    action = config.get("on_failure", "nothing")
    url = config.get("moonraker_url", "http://127.0.0.1:7125").rstrip('/')
    logging.info(f"FAILURE CONFIRMED: {reason}. Action: {action}")
    try:
        console_msg = f"M118 >>> AI DETECTED {reason.upper()}! Action: {action.upper()} <<<"
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
            
            # --- MULTI-CAMERA LOOP ---
            max_frame_score = 0.0
            active_cam_count = 0
            
            for cam in config["cameras"]:
                cam_id = cam["id"]
                
                # If disabled or empty URL, skip
                if not cam["enabled"] or not cam["url"]:
                    # Keep state clean/empty
                    state["cameras"][cam_id]["score"] = 0.0
                    # We don't clear the frame here so the "Disabled" overlay can work in UI
                    continue
                
                active_cam_count += 1

                # 1. Fetch Image
                try:
                    resp = requests.get(cam["url"], timeout=2)
                    if resp.status_code == 200:
                        arr = np.frombuffer(resp.content, np.uint8)
                        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        
                        # If Idle/Off, just save raw frame
                        if not should_run:
                            state["cameras"][cam_id]["frame"] = img
                            state["cameras"][cam_id]["score"] = 0.0
                            continue
                        
                        # 2. Run AI Inference
                        if model:
                            user_conf = float(config.get("ai_threshold", 0.5))
                            results = model(img, conf=user_conf, verbose=False)
                            result = results[0]
                            
                            # --- MANUAL DRAWING ---
                            debug_img = img.copy()
                            box_count = len(result.boxes)
                            cam_high_score = 0.0
                            
                            if box_count > 0:
                                for box in result.boxes:
                                    coords = box.xyxy[0].cpu().numpy().astype(int)
                                    conf = float(box.conf[0])
                                    cls_id = int(box.cls[0])
                                    
                                    if conf > cam_high_score: cam_high_score = conf
                                    
                                    label = "Failure"
                                    if cls_id < len(CLASS_NAMES): label = CLASS_NAMES[cls_id]
                                    
                                    x1, y1, x2, y2 = coords
                                    
                                    # Clamp
                                    h_img, w_img = debug_img.shape[:2]
                                    x1 = max(0, min(x1, w_img)); x2 = max(0, min(x2, w_img))
                                    y1 = max(0, min(y1, h_img)); y2 = max(0, min(y2, h_img))
                                    
                                    # Draw Red Box
                                    cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 0, 255), 2)
                                    
                                    # Smart Label
                                    text = f"{label} {int(conf*100)}%"
                                    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                                    
                                    if y1 < 20: text_y = y1 + th + 5
                                    else: text_y = y1 - 5
                                    
                                    cv2.rectangle(debug_img, (x1, text_y - th - 2), (x1 + tw, text_y + 2), (0, 0, 255), -1)
                                    cv2.putText(debug_img, text, (x1, text_y), 
                                              cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                                # Update this camera's score
                                state["cameras"][cam_id]["score"] = cam_high_score
                                # Update global max
                                if cam_high_score > max_frame_score:
                                    max_frame_score = cam_high_score
                                    
                            else:
                                state["cameras"][cam_id]["score"] = 0.0
                            
                            # Save drawn frame
                            state["cameras"][cam_id]["frame"] = debug_img
                except Exception:
                    # Connection error to this specific camera
                    pass

            # --- GLOBAL STATE UPDATE ---
            if not should_run:
                state["status"] = "idle"
                state["failure_count"] = 0
                state["action_triggered"] = False
                time.sleep(1)
                continue

            state["status"] = "monitoring"
            
            # Global Failure Logic
            threshold = float(config.get("ai_threshold", 0.5))
            max_retries = int(config["consecutive_failures"])
            
            if max_frame_score > threshold:
                if state["failure_count"] < max_retries:
                    state["failure_count"] += 1
                
                logging.info(f"ALERT: Failure detected! Score: {max_frame_score:.2f} | Count: {state['failure_count']}")
                
                if state["failure_count"] >= max_retries:
                    state["status"] = "failure_detected"
                    trigger_printer_action(reason="AI Detection")
            else:
                # Decay
                if state["failure_count"] > 0:
                     state["failure_count"] -= 1

        except Exception as e:
            logging.error(f"Loop Error: {e}")
        
        time.sleep(float(config["check_interval"]) / 1000.0)

monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

# --- API ROUTES ---
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
    # If cam_id doesn't exist or has no frame, return black image
    if cam_id not in state["cameras"] or state["cameras"][cam_id]["frame"] is None:
        blank = np.zeros((360, 640, 3), np.uint8)
        # Optional: Draw "NO SIGNAL" text on black frame
        cv2.putText(blank, "NO SIGNAL / DISABLED", (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 1, (100,100,100), 2)
        _, buffer = cv2.imencode('.jpg', blank)
        return Response(buffer.tobytes(), mimetype='image/jpeg')
        
    _, buffer = cv2.imencode('.jpg', state["cameras"][cam_id]["frame"])
    return Response(buffer.tobytes(), mimetype='image/jpeg')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=7126, threaded=True)
