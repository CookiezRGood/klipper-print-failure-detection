import json
import os
import logging
import threading
import time
import cv2
import numpy as np
import requests
from flask import Flask, jsonify, request, Response, send_from_directory

# --- LOGGING ---
log = logging.getLogger('werkzeug')
log.disabled = True
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logging.info(">>> STARTING PLUGIN: COORDINATE FIX <<<")

app = Flask(__name__, static_folder='web_interface')

# Path to the settings file
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')

# Initialize the state variable
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

# Load existing settings if file exists, else use defaults
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    else:
        return {
            "cameras": [
                {"enabled": True, "id": 0, "name": "Primary", "url": "http://camera_ip_here/webcam/?action=snapshot"},
                {"enabled": True, "id": 1, "name": "Secondary", "url": "http://camera_ip_here/webcam2/?action=snapshot"}
            ],
            "moonraker_url": "http://127.0.0.1:7125",
            "check_interval": 500,
            "ai_threshold": 0.1,
            "consecutive_failures": 3,
            "on_failure": "nothing",
            "aspect_ratio": "4:3",
            "preview_refresh_rate": 500
        }

# Save settings to the user_settings.json file
def save_settings_to_file(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)

# --- Route to handle the settings ---
@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        settings_data = request.json
        save_settings_to_file(settings_data)  # Save the updated settings to the file
        return jsonify({"status": "saved", "config": settings_data})

    # Return current settings if GET request
    return jsonify(load_settings())

# --- Background Monitoring and AI Detection Logic ---
def background_monitor():
    while True:
        try:
            klipper_state = get_printer_state()
            if klipper_state in ["complete", "error", "cancelled"]:
                state["monitoring_active"] = False

            should_run = (klipper_state in ["printing", "paused"]) or state["monitoring_active"]

            # Loop Cameras
            max_frame_score = 0.0

            for cam in config["cameras"]:
                cam_id = cam["id"]
                if not cam["enabled"] or not cam["url"]: 
                    state["cameras"][cam_id]["score"] = 0.0
                    continue

                try:
                    resp = requests.get(cam["url"], timeout=2)
                    if resp.status_code == 200:
                        arr = np.frombuffer(resp.content, np.uint8)
                        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        
                        if not should_run:
                            state["cameras"][cam_id]["frame"] = img
                            state["cameras"][cam_id]["score"] = 0.0
                            continue
                        
                        if ai_ready:
                            score, detections = run_inference(img)
                            
                            debug_img = img.copy()
                            for d in detections:
                                x, y, w, h = d['box']
                                cls_id = d['class']
                                label = CLASS_NAMES[cls_id] if cls_id < len(CLASS_NAMES) else "Failure"
                                
                                # --- DRAWING FIX ---
                                # Ensure box fits in image
                                h_img, w_img = debug_img.shape[:2]
                                x = max(0, min(x, w_img))
                                y = max(0, min(y, h_img))
                                w = max(0, min(w, w_img - x))
                                h = max(0, min(h, h_img - y))

                                cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 0, 255), 2)
                                
                                # Label
                                text = f"{label} {int(d['conf']*100)}%"
                                (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                                text_y = y + th + 5 if y < 20 else y - 5
                                cv2.rectangle(debug_img, (x, text_y - th - 2), (x + tw, text_y + 2), (0, 0, 255), -1)
                                cv2.putText(debug_img, text, (x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                            
                            state["cameras"][cam_id]["frame"] = debug_img
                            state["cameras"][cam_id]["score"] = score
                            
                            if score > max_frame_score: 
                                max_frame_score = score

                except Exception: pass

            # Global Logic
            if not should_run:
                state["status"] = "idle"
                state["failure_count"] = 0
                state["action_triggered"] = False
                time.sleep(1)
                continue

            state["status"] = "monitoring"
            max_retries = int(config["consecutive_failures"])
            threshold = float(config.get("ai_threshold", 0.5))
            
            if max_frame_score > threshold:
                if state["failure_count"] < max_retries:
                    state["failure_count"] += 1
                
                logging.info(f"ALERT: Failure {max_frame_score:.2f} | Count: {state['failure_count']}")
                
                if state["failure_count"] >= max_retries:
                    state["status"] = "failure_detected"
                    trigger_printer_action(reason="AI Detection")
            else:
                if state["failure_count"] > 0:
                    state["failure_count"] -= 1

        except Exception as e:
            logging.error(f"Loop Error: {e}")
        
        # Use check_interval for both detection and UI refresh
        time.sleep(float(config["check_interval"]) / 1000.0)

monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

# Routes
@app.route('/')
def serve_index(): return send_from_directory('web_interface', 'index.html')
@app.route('/<path:path>')
def serve_static(path): return send_from_directory('web_interface', path)
@app.route('/api/frame/<int:cam_id>')
def get_frame(cam_id):
    if cam_id not in state["cameras"] or state["cameras"][cam_id]["frame"] is None:
        blank = np.zeros((360, 640, 3), np.uint8)
        cv2.putText(blank, "NO SIGNAL / DISABLED", (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 1, (100,100,100), 2)
        _, buffer = cv2.imencode('.jpg', blank)
        return Response(buffer.tobytes(), mimetype='image/jpeg')
    _, buffer = cv2.imencode('.jpg', state["cameras"][cam_id]["frame"])
    return Response(buffer.tobytes(), mimetype='image/jpeg')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=7126, threaded=True)
