import time
import threading
import logging
from flask import Flask, jsonify, request

plugin_name = "print_failure_detection"

# Set up logging
logging.basicConfig(level=logging.INFO)

# Create the Mainsail app and API endpoints
app = Flask(__name__)

# Placeholder to store current config
current_config = {
    "ssim_threshold": 0.97,
    "stillness_threshold": 0.20,
    "layer_min_step": 0.15,
    "camera_url": "http://192.168.10.153/webcam/?action=snapshot"
}

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    global current_config

    if request.method == 'POST':
        # Update config from the frontend
        data = request.json
        current_config.update(data)

    return jsonify(current_config)

@app.route('/api/failure_status', methods=['GET'])
def failure_status():
    # Check the current failure detection status (can be based on the detection loop state)
    status = {
        "status": "active" if some_failure_detection_is_active else "paused"
    }
    return jsonify(status)

@app.route('/api/camera_snapshot', methods=['GET'])
def camera_snapshot():
    # Return a snapshot from the camera
    # For simplicity, return the camera URL directly here
    return jsonify({"snapshot_url": current_config["camera_url"]})

# Run the app
def start_plugin():
    app.run(host='0.0.0.0', port=7126)

# Run the backend in a separate thread so it doesn't block Mainsail
plugin_thread = threading.Thread(target=start_plugin)
plugin_thread.daemon = True
plugin_thread.start()
