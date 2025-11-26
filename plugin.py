import logging
import threading
import time
import cv2
import numpy as np
import requests
import json
import os
from flask import Flask, jsonify, request, Response, send_from_directory

# Import TFLite Runtime
try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    logging.warning("CRITICAL: tflite-runtime not found. AI will not work.")
    tflite = None

# --- LOGGING ---
log = logging.getLogger('werkzeug')
log.disabled = True
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logging.info(">>> STARTING PLUGIN: TFLITE MODE <<<")

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.tflite')

default_config = {
    "camera_url": "http://127.0.0.1/webcam/?action=snapshot",
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 500,      # TFLite is fast! We can check often.
    "ai_threshold": 0.50,
    "consecutive_failures": 2,
    "on_failure": "pause",
    "aspect_ratio": "16:9",
    "preview_refresh_rate": 500
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
    "annotated_frame": None,
    "status": "idle",
    "failure_score": 0.0,
    "failure_count": 0,
    "action_triggered": False,
    "monitoring_active": False 
}

# --- AI ENGINE ---
interpreter = None
input_details = None
output_details = None
input_height = 640
input_width = 640

def load_model():
    global interpreter, input_details, output_details, input_height, input_width
    if not os.path.exists(MODEL_PATH):
        logging.error(f"CRITICAL: model.tflite NOT FOUND at {MODEL_PATH}")
        return False
    
    try:
        interpreter = tflite.Interpreter(model_path=MODEL_PATH)
        interpreter.allocate_tensors()
        
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()
        
        # Get expected input size from model (usually 640x640)
        input_shape = input_details[0]['shape']
        input_height = input_shape[1]
        input_width = input_shape[2]
        
        logging.info(f"TFLite Model Loaded. Input Shape: {input_shape}")
        return True
    except Exception as e:
        logging.error(f"Failed to load TFLite: {e}")
        return False

ai_ready = load_model()

def post_process_yolo(output_data, img_width, img_height, conf_threshold):
    """
    Decodes raw YOLO TFLite output [1, 4+Nc, 8400] into boxes.
    """
    # Transpose to [8400, 4+Nc] to make rows easier to read
    # output_data shape is typically (1, 84, 8400) for COCO (80 classes + 4 coords)
    # or (1, 5, 8400) for 1 class
    output = np.transpose(output_data[0])
    
    boxes = []
    confidences = []
    class_ids = []
    
    # Calculate scaling factors
    x_factor = img_width / input_width
    y_factor = img_height / input_height

    # Loop through all 8400 rows (predictions)
    # Optimization: Filter by confidence BEFORE loop using numpy masks would be faster,
    # but loop is clearer for logic.
    
    # Extract max confidence for each row
    # Rows are [cx, cy, w, h, class_scores...]
    scores = output[:, 4:]
    max_scores = np.max(scores, axis=1)
    max_indices = np.argmax(scores, axis=1)
    
    # Filter by threshold
    valid_indices = np.where(max_scores >= conf_threshold)[0]
    
    for i in valid_indices:
        score = max_scores[i]
        class_id = max_indices[i]
        row = output[i]
        
        # Extract box (cx, cy, w, h)
        cx, cy, w, h = row[0], row[1], row[2], row[3]
        
        # Convert to top-left (x, y) and scale to original image size
        left = int((cx - w/2) * x_factor)
        top = int((cy - h/2) * y_factor)
        width = int(w * x_factor)
        height = int(h * y_factor)
        
        boxes.append([left, top, width, height])
        confidences.append(float(score))
        class_ids.append(int(class_id))

    # Apply Non-Maximum Suppression (NMS) to remove overlapping boxes
    # Score threshold is already applied, NMS threshold usually 0.45
    indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, 0.45)
    
    final_results = []
    if len(indices) > 0:
        for i in indices.flatten():
            final_results.append({
                "box": boxes[i],
                "conf": confidences[i],
                "class": class_ids[i]
            })
            
    return final_results

def run_inference(image):
    if not ai_ready or interpreter is None: return 0.0, []
    
    try:
        original_h, original_w = image.shape[:2]
        
        # 1. Resize
        resized = cv2.resize(image, (input_width, input_height))
        
        # 2. Normalize (YOLO usually expects float32 0-1)
        input_data = np.expand_dims(resized, axis=0)
        
        if input_details[0]['dtype'] == np.float32:
            input_data = (input_data.astype(np.float32) / 255.0)
        
        # 3. Run
        interpreter.set_tensor(input_details[0]['index'], input_data)
        interpreter.invoke()
        
        # 4. Get Output
        output_data = interpreter.get_tensor(output_details[0]['index'])
        
        # 5. Post Process
        user_conf = float(config.get("ai_threshold", 0.5))
        detections = post_process_yolo(output_data, original_w, original_h, user_conf)
        
        if not detections:
            return 0.0, []
            
        # Return highest confidence score and list of boxes
        top_score = max(d['conf'] for d in detections)
        return top_score, detections
        
    except Exception as e:
        logging.error(f"Inference Error: {e}")
        return 0.0, []

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
        console_msg = f"M118 >>> TFLITE DETECTED FAILURE! Action: {action.upper()} <<<"
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

            resp = requests.get(config['camera_url'], timeout=2)
            if resp.status_code == 200:
                arr = np.frombuffer(resp.content, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                state["latest_frame"] = img
                if not should_run:
                    state["annotated_frame"] = img
            else:
                state["status"] = "connection_error"
                time.sleep(2)
                continue

            if not should_run:
                state["status"] = "idle"
                state["failure_count"] = 0
                state["action_triggered"] = False
                time.sleep(1)
                continue

            # --- TFLITE INFERENCE ---
            state["status"] = "monitoring"
            
            if ai_ready:
                score, detections = run_inference(state["latest_frame"])
                state["failure_score"] = score
                
                # Draw Boxes
                debug_img = state["latest_frame"].copy()
                for d in detections:
                    x, y, w, h = d['box']
                    cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 0, 255), 2)
                    cv2.putText(debug_img, f"FAIL {int(d['conf']*100)}%", (x, y-5), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                
                state["annotated_frame"] = debug_img
                
                max_retries = int(config["consecutive_failures"])
                
                if score > float(config["ai_threshold"]):
                    if state["failure_count"] < max_retries:
                        state["failure_count"] += 1
                    
                    logging.info(f"ALERT: Failure {score:.2f} | Count: {state['failure_count']}/{max_retries}")
                    
                    if state["failure_count"] >= max_retries:
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
    return jsonify({
        "status": state["status"],
        "score": state["failure_score"],
        "failures": state["failure_count"],
        "max_retries": config["consecutive_failures"]
    })
@app.route('/api/latest_frame')
def latest_frame():
    img = state["annotated_frame"] if state["annotated_frame"] is not None else np.zeros((360, 640, 3), np.uint8)
    _, buffer = cv2.imencode('.jpg', img)
    return Response(buffer.tobytes(), mimetype='image/jpeg')
@app.route('/api/debug_frame')
def debug_frame(): return latest_frame()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=7126, threaded=True)
