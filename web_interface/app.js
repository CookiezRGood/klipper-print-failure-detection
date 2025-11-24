const app = new Vue({
    el: 'body',
    data: {
        cameraUrl: '',
        ssimThreshold: 0.97,
        stillnessThreshold: 0.20,
        layerStep: 0.15,
        failureStatus: 'Inactive'
    },
    mounted() {
        this.fetchSettings();
        this.fetchCameraSnapshot();
        this.fetchFailureStatus();
    },
    methods: {
        fetchSettings() {
            fetch('/api/settings')
                .then(response => response.json())
                .then(data => {
                    this.ssimThreshold = data.ssim_threshold;
                    this.stillnessThreshold = data.stillness_threshold;
                    this.layerStep = data.layer_min_step;
                });
        },
        fetchCameraSnapshot() {
            fetch('/api/camera_snapshot')
                .then(response => response.json())
                .then(data => {
                    this.cameraUrl = data.snapshot_url;
                    document.getElementById('camera-preview').src = this.cameraUrl;
                });
        },
        fetchFailureStatus() {
            fetch('/api/failure_status')
                .then(response => response.json())
                .then(data => {
                    this.failureStatus = data.status;
                    document.getElementById('failure-status').innerText = this.failureStatus;
                });
        },
        pausePrint() {
            fetch('/api/pause', { method: 'POST' });
        },
        cancelPrint() {
            fetch('/api/cancel', { method: 'POST' });
        }
    }
});
