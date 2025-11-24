import logging
from flask import Flask, jsonify, request
import threading

# Set up logging to show info about the startup process
logging.basicConfig(level=logging.INFO)
logging.info("Starting the Print Failure Detection Plugin...")

# Initialize Flask app
app = Flask(__name__)

# Sample plugin configuration
current_config = {
    "ssim_threshold": 0.97,
    "stillness_threshold": 0.20,
    "layer_min_step": 0.15,
    "camera_url": "http://192.168.10.153/webcam/?action=snapshot"
}

# Endpoint to get current settings
@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    global current_config
    if request.method == 'POST':
        # Update settings from the frontend
        data = request.json
        current_config.update(data)
    return jsonify(current_config)

# Endpoint to get failure detection status
@app.route('/api/failure_status', methods=['GET'])
def failure_status():
    # Return a dummy status for now (you can update this with actual status)
    status = {
        "status": "active"  # You can change this dynamically based on detection logic
    }
    return jsonify(status)

# Function to run Flask in the background
def run_plugin():
    logging.info("Running Flask app...")
    app.run(host='0.0.0.0', port=7126, threaded=True)

# Start the Flask app in a separate thread
plugin_thread = threading.Thread(target=run_plugin)
plugin_thread.daemon = True
plugin_thread.start()

# Keep the main script running indefinitely (necessary to keep Flask running)
while True:
    pass
