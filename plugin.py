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
logging.info(">>> STARTING PLUGIN: MINI DASHBOARD SUPPORT <<<")

# Import TFLite Runtime
try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    logging.warning("CRITICAL: tflite-runtime not found. AI will not work.")
    tflite = None

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.tflite')

CLASS_NAMES = ["Spaghetti", "Stringing", "Zits"]

default_config = {
    "cameras": [
        {"id": 0, "name": "Primary", "url": "http://127.0.0.1/webcam/?action=snapshot", "enabled": True},
        {"id": 1, "name": "Secondary", "url": "", "enabled": False}
    ],
    "camera_count": 2,
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 500,
    "warn_threshold": 0.30,
    "ai_threshold": 0.50,
    "consecutive_failures": 2,
    "on_failure": "pause",
    "aspect_ratio": "16:9"
}

config = default_config.copy()
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, 'r') as f:
            loaded = json.load(f)
            if "camera_url" in loaded:
                config["cameras"][0]["url"] = loaded["camera_url"]
            config.update(loaded)
    except Exception: pass

def save_config_to_file():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception: pass

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
interpreter = None
input_details = None
output_details = None
input_height = 640
input_width = 640
input_dtype = np.float32

def load_model():
    global interpreter, input_details, output_details, input_height, input_width, input_dtype
    if not os.path.exists(MODEL_PATH):
        logging.error(f"CRITICAL: model.tflite NOT FOUND at {MODEL_PATH}")
        return False
    
    try:
        interpreter = tflite.Interpreter(model_path=MODEL_PATH)
        interpreter.allocate_tensors()
        
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()
        
        input_shape = input_details[0]['shape']
        input_height = input_shape[1]
        input_width = input_shape[2]
        input_dtype = input_details[0]['dtype']
        
        logging.info(f"TFLite Model Loaded. Shape: {input_shape}")
        return True
    except Exception as e:
        logging.error(f"Failed to load TFLite: {e}")
        return False

ai_ready = load_model()

def post_process_yolo(output_data, img_width, img_height, conf_threshold):
    if output_data.shape[1] < output_data.shape[2]:
        output = np.transpose(output_data[0])
    else:
        output = output_data[0]

    boxes = []
    confidences = []
    class_ids = []
    
    sample_coords = output[:, :4].flatten()
    is_normalized = np.max(sample_coords) <= 1.5 
    
    if is_normalized:
        x_factor = img_width
        y_factor = img_height
    else:
        x_factor = img_width / input_width
        y_factor = img_height / input_height

    scores = output[:, 4:]
    max_scores = np.max(scores, axis=1)
    max_indices = np.argmax(scores, axis=1)
    
    valid_indices = np.where(max_scores >= conf_threshold)[0]
    
    for i in valid_indices:
        score = float(max_scores[i])
        class_id = int(max_indices[i])
        row = output[i]
        
        cx, cy, w, h = row[0], row[1], row[2], row[3]
        
        left = int((cx - w/2) * x_factor)
        top = int((cy - h/2) * y_factor)
        width = int(w * x_factor)
        height = int(h * y_factor)
        
        left = max(0, left)
        top = max(0, top)
        width = min(width, img_width - left)
        height = min(height, img_height - top)
        
        boxes.append([left, top, width, height])
        confidences.append(score)
        class_ids.append(class_id)

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
        resized = cv2.resize(image, (input_width, input_height))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        input_data = np.expand_dims(rgb, axis=0)
        
        if input_details[0]['dtype'] == np.float32:
            input_data = (input_data.astype(np.float32) / 255.0)
        elif input_details[0]['dtype'] == np.uint8:
            input_data = input_data.astype(np.uint8)
            
        interpreter.set_tensor(input_details[0]['index'], input_data)
        interpreter.invoke()
        
        output_data = interpreter.get_tensor(output_details[0]['index'])
        
        user_conf = float(config.get("warn_threshold", 0.3))
        detections = post_process_yolo(output_data, original_w, original_h, user_conf)
        
        if not detections: return 0.0, []
        
        top_score = max(d['conf'] for d in detections)
        return top_score, detections
        
    except Exception as e:
        logging.error(f"Inference Error: {e}")
        return 0.0, []

# --- ROUTES ---
@app.route('/')
def serve_index(): return send_from_directory('web_interface', 'index.html')

# NEW MINI DASHBOARD ROUTE
@app.route('/mini')
def serve_mini(): return send_from_directory('web_interface', 'mini.html')

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
    max_score = max(state["cameras"][0]["score"], state["cameras"][1]["score"])
    return jsonify({
        "status": state["status"],
        "score": max_score,
        "failures": state["failure_count"],
        "max_retries": config["consecutive_failures"]
    })

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
