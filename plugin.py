import logging
import threading
import time
import cv2
import numpy as np
import requests
from flask import Flask, jsonify, request, send_from_directory, Response

# Set up logging
logging.basicConfig(level=logging.INFO)
logging.info("Starting Print Failure Detection Plugin...")

app = Flask(__name__, static_folder='web_interface')

# Global State
state = {
    "latest_frame": None,
    "debug_frame": None,
    "status": "idle",
    "previous_gray": None
}

config = {
    "ssim_threshold": 0.97,
    "stillness_threshold": 0.20,
    "check_interval": 0.2,
    "camera_url": "http://192.168.10.153/webcam/?action=snapshot",
    "mask_margin": 15,
    "max_mask_percent": 0.15  # SAFETY: If mask covers >15% of screen, it's a failure
}

def background_monitor():
    log_info("Background monitor started.")
    dilate_kernel = np.ones((config['mask_margin'], config['mask_margin']), np.uint8)

    while True:
        try:
            # 1. Fetch Image
            resp = requests.get(config['camera_url'], timeout=2)
            if resp.status_code == 200:
                arr = np.frombuffer(resp.content, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                
                state["latest_frame"] = img.copy()
                debug_img = img.copy()
                height, width = img.shape[:2]
                total_pixels = height * width

                # 2. Motion Detection
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)

                if state["previous_gray"] is None:
                    state["previous_gray"] = gray
                else:
                    # A. Calculate Difference
                    frame_delta = cv2.absdiff(state["previous_gray"], gray)
                    thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]

                    # B. Expand the mask (The "Bubble" around the toolhead)
                    mask_dilated = cv2.dilate(thresh, dilate_kernel, iterations=2)

                    # --- SAFETY CHECK: IS THE MASK TOO BIG? ---
                    # Count how many white pixels are in the mask
                    mask_pixels = cv2.countNonZero(mask_dilated)
                    mask_coverage = mask_pixels / total_pixels

                    if mask_coverage > config['max_mask_percent']:
                        # The moving object is HUGE. This is likely spaghetti stuck to the head.
                        state["status"] = "failure_detected"
                        
                        # Draw a RED warning box
                        cv2.putText(debug_img, f"FAILURE: MOVING OBJECT TOO LARGE ({int(mask_coverage*100)}%)", 
                                  (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                        cv2.rectangle(debug_img, (0,0), (width, height), (0, 0, 255), 10)
                        
                    else:
                        # Normal Operation
                        contours, _ = cv2.findContours(mask_dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        
                        if contours:
                            # Draw the Green Mask (Normal)
                            large_contours = [c for c in contours if cv2.contourArea(c) > 500]
                            
                            # Visual Effect: Semi-transparent green
                            overlay = debug_img.copy()
                            cv2.drawContours(overlay, large_contours, -1, (0, 255, 0), -1)
                            cv2.addWeighted(overlay, 0.3, debug_img, 0.7, 0, debug_img)
                            
                            state["status"] = "monitoring"
                        else:
                            state["status"] = "monitoring"

                    state["previous_gray"] = gray

                state["debug_frame"] = debug_img
            else:
                state["status"] = "camera_error"

        except Exception as e:
            # logging.error(f"Error: {e}")
            state["status"] = "error"
        
        time.sleep(config["check_interval"])

def log_info(msg):
    logging.info(msg)

monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

@app.route('/')
def serve_index():
    return send_from_directory('web_interface', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('web_interface', path)

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        data = request.json
        config.update(data)
    return jsonify(config)

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({"status": state["status"]})

@app.route('/api/latest_frame')
def latest_frame():
    img = state["latest_frame"]
    if img is None: return "No image", 404
    _, buffer = cv2.imencode('.jpg', img)
    return Response(buffer.tobytes(), mimetype='image/jpeg')

@app.route('/api/debug_frame')
def debug_frame():
    img = state["debug_frame"]
    if img is None: return "No debug image", 404
    _, buffer = cv2.imencode('.jpg', img)
    return Response(buffer.tobytes(), mimetype='image/jpeg')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=7126, threaded=True)
