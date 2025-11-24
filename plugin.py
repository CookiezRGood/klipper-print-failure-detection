import logging
from flask import Flask, jsonify, request
import threading

# Set up logging
logging.basicConfig(level=logging.INFO)
logging.info("Starting the Print Failure Detection Plugin...")

# Set up the Flask app
app = Flask(__name__)

# Sample configuration
current_config = {
    "ssim_threshold": 0.97,
    "stillness_threshold": 0.20,
    "layer_min_step": 0.15,
    "camera_url": "http://192.168.10.153/webcam/?action=snapshot"
}

# API to get current settings
@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    global current_config
    if request.method == 'POST':
        # Update settings from the frontend
        data = request.json
        current_config.update(data)
    return jsonify(current_config)

# API to get failure detection status
@app.route('/api/failure_status', methods=['GET'])
def failure_status():
    # Return a dummy status (update this to reflect actual plugin state)
    status = {
        "status": "active"  # Change this based on actual plugin state
    }
    return jsonify(status)

# Function to run the Flask app
def run_plugin():
    logging.info("Running Flask app...")
    app.run(host='0.0.0.0', port=7126)

# Run the plugin in a separate thread
plugin_thread = threading.Thread(target=run_plugin)
plugin_thread.daemon = True
plugin_thread.start()
