<template>
  <div class="plugin-container">
    <h1>Print Failure Detection</h1>

    <div class="camera-section">
      <h2>Camera Preview</h2>
      <img :src="cameraUrl" alt="Camera Feed" width="320" height="240">
      <button @click="refreshCamera">Refresh Camera</button>
    </div>

    <div class="status-section">
      <h2>Status:</h2>
      <p>{{ status }}</p>
    </div>

    <div class="settings-section">
      <h2>Settings</h2>
      <label for="ssim-threshold">SSIM Threshold:</label>
      <input type="range" id="ssim-threshold" min="0" max="1" step="0.01" v-model="ssimThreshold">
      <span>{{ ssimThreshold }}</span>
    </div>

    <div class="masking-section">
      <h2>Masking Options</h2>
      <label for="mask-toggle">Enable Masking:</label>
      <input type="checkbox" v-model="maskingEnabled">
    </div>
  </div>
</template>

<script>
export default {
  data() {
    return {
      cameraUrl: 'http://192.168.10.153/webcam/?action=snapshot',
      status: 'Waiting for detection...',
      ssimThreshold: 0.97,
      maskingEnabled: false,
    };
  },
  methods: {
    refreshCamera() {
      fetch('/api/camera_snapshot')
        .then((response) => response.json())
        .then((data) => {
          this.cameraUrl = data.snapshot_url;
        });
    },
  },
};
</script>

<style scoped>
/* Add your plugin-specific CSS here */
</style>
