import logging
import threading
import time
import cv2
import numpy as np
import requests
from flask import Flask, jsonify, request, send_from_directory, Response

# Import SSIM logic if available, else fallback
try:
    from core.detection import ssim
except ImportError:
    def ssim(img1, img2): return 1.0

logging.basicConfig(level=logging.INFO)
logging.info("Starting Print Failure Detection Plugin...")

app = Flask(__name__, static_folder='web_interface')

# Global State
state = {
    "latest_frame": None,
    "debug_frame": None,
    "status": "idle",
    "previous_gray": None,
    "last_stable_frame": None,  # The reference image we compare against
    "current_ssim": 1.0,
    "failure_count": 0
}

config = {
    "ssim_threshold": 0.90,     # Lowered slightly to be less sensitive to lighting
    "check_interval": 0.2,
    "camera_url": "http://192.168.10.153/webcam/?action=snapshot",
    "mask_margin": 15,
    "max_mask_percent": 0.25,   # Increased to prevent false positives on large printheads
    "consecutive_failures": 3
}

def background_monitor():
    log_info("Background monitor started.")
    dilate_kernel = np.ones((config['mask_margin'], config['mask_margin']), np.uint8)

    while True:
        try:
            resp = requests.get(config['camera_url'], timeout=2)
            if resp.status_code == 200:
                arr = np.frombuffer(resp.content, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                
                state["latest_frame"] = img.copy()
                debug_img = img.copy()
                height, width = img.shape[:2]
                total_pixels = height * width

                # --- 1. Motion Detection ---
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)

                if state["previous_gray"] is None:
                    # First boot: Initialize everything
                    state["previous_gray"] = gray
                    state["last_stable_frame"] = gray
                    time.sleep(1) # Wait for camera to settle
                    continue

                # Calculate difference
                frame_delta = cv2.absdiff(state["previous_gray"], gray)
                thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
                mask_dilated = cv2.dilate(thresh, dilate_kernel, iterations=2)

                # Check how much of the screen is moving
                mask_pixels = cv2.countNonZero(mask_dilated)
                mask_coverage = mask_pixels / total_pixels

                # --- 2. Logic Fork ---
                
                if mask_coverage > 0.001:
                    # === MOTION DETECTED ===
                    # If the printer is moving, we assume it is VALID.
                    # We RESET the failure count and UPDATE the reference frame.
                    
                    state["status"] = "monitoring"
                    state["current_ssim"] = 1.0
                    state["failure_count"] = 0  # Clear any pending failures
                    state["last_stable_frame"] = gray # Update reference to new position
                    
                    # Draw the green mask for the UI
                    contours, _ = cv2.findContours(mask_dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if contours:
                        large_contours = [c for c in contours if cv2.contourArea(c) > 500]
                        overlay = debug_img.copy()
                        cv2.drawContours(overlay, large_contours, -1, (0, 255, 0), -1)
                        cv2.addWeighted(overlay, 0.3, debug_img, 0.7, 0, debug_img)
                        
                        # Attach label to the biggest blob
                        if large_contours:
                            c = max(large_contours, key=cv2.contourArea)
                            x, y, w, h = cv2.boundingRect(c)
                            cv2.putText(debug_img, "Mask Active", (x, y - 10), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                else:
                    # === NO MOTION (STILL) ===
                    # Only check for failure if we are completely still
                    
                    if state["last_stable_frame"] is not None:
                        score = ssim(gray, state["last_stable_frame"])
                        state["current_ssim"] = score

                        if score < config["ssim_threshold"]:
                            # --- POTENTIAL FAILURE ---
                            # Only increment if we haven't already hit the max
                            if state["failure_count"] < config["consecutive_failures"]:
                                state["failure_count"] += 1
                            
                            log_info(f"Low SSIM: {score:.3f} | Failures: {state['failure_count']}")
                            
                            # Trigger Failure State
                            if state["failure_count"] >= config["consecutive_failures"]:
                                state["status"] = "failure_detected"
                        
                        else:
                            # --- STABLE / HEALTHY ---
                            # Image matches reference. We are good.
                            # Slowly update reference to account for lighting changes
                            state["failure_count"] = 0
                            state["status"] = "checking"
                            state["last_stable_frame"] = gray 

                state["previous_gray"] = gray
                state["debug_frame"] = debug_img
            else:
                state["status"] = "camera_error"

        except Exception as e:
            state["status"] = "error"
        
        time.sleep(config["check_interval"])

def log_info(msg):
    logging.info(msg)

monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

@app.route('/')
def serve_index(): return send_from_directory('web_interface', 'index.html')

@app.route('/<path:path>')
def serve_static(path): return send_from_directory('web_interface', path)

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        data = request.json
        config.update(data)
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
