// Function to update SSIM threshold from the slider
function updateSSIMThreshold(value) {
    document.getElementById('ssim-value').innerText = value;
    fetch('/api/settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            ssim_threshold: parseFloat(value)
        })
    });
}

// Function to toggle masking option
function toggleMasking(isChecked) {
    fetch('/api/settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            dynamic_mask: isChecked
        })
    });
}

// Function to fetch camera feed
function refreshCamera() {
    fetch('/api/camera_snapshot')
        .then(response => response.json())
        .then(data => {
            document.getElementById('camera-preview').src = data.snapshot_url;
        });
}

// Fetch and display current settings when page loads
window.onload = function() {
    fetch('/api/settings')
        .then(response => response.json())
        .then(data => {
            document.getElementById('ssim-threshold').value = data.ssim_threshold;
            document.getElementById('ssim-value').innerText = data.ssim_threshold;
            document.getElementById('mask-toggle').checked = data.dynamic_mask || false;
            refreshCamera();
        });
}
