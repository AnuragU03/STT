document.addEventListener('DOMContentLoaded', () => {
    const startBtn = document.getElementById('startBtn');
    const stopBtn = document.getElementById('stopBtn');
    const statusDiv = document.getElementById('status');

    // Check current state from storage
    chrome.storage.local.get(['recording'], (result) => {
        if (result.recording) {
            setUIState(true);
        }
    });

    startBtn.addEventListener('click', async () => {
        try {
            statusDiv.textContent = "Requesting mic permission...";

            // 0. Request Microphone Permission FIRST (user gesture in popup)
            try {
                await navigator.mediaDevices.getUserMedia({ audio: true });
                console.log("Mic permission granted!");
            } catch (micError) {
                console.warn("Mic permission denied/dismissed:", micError);
                // Continue anyway - we can still record tab audio
            }

            statusDiv.textContent = "Starting recording...";

            // 1. Get Stream ID for Tab Audio (Speakers)
            // This MUST be called in the popup context (user gesture)
            const streamId = await new Promise((resolve, reject) => {
                chrome.tabCapture.getMediaStreamId({ consumerTabId: null }, (id) => {
                    if (chrome.runtime.lastError) reject(chrome.runtime.lastError);
                    else resolve(id);
                });
            });

            // 2. Send start message to Background with the stream ID
            chrome.runtime.sendMessage({
                type: 'START_RECORDING',
                streamId: streamId
            }, (response) => {
                if (response && response.success) {
                    setUIState(true);
                    chrome.storage.local.set({ recording: true });
                } else {
                    statusDiv.textContent = "Failed to start.";
                }
            });

        } catch (error) {
            console.error(error);
            statusDiv.textContent = "Error: " + error.message;
        }
    });

    stopBtn.addEventListener('click', () => {
        statusDiv.textContent = "Stopping & Uploading...";
        chrome.runtime.sendMessage({ type: 'STOP_RECORDING' }, (response) => {
            setUIState(false);
            chrome.storage.local.set({ recording: false });
            statusDiv.textContent = "Recording stopped. Processing...";
        });
    });

    // Listen for upload status
    chrome.runtime.onMessage.addListener((message) => {
        if (message.type === 'UPLOAD_SUCCESS') {
            statusDiv.textContent = "✅ Uploaded! Check Dashboard.";
        } else if (message.type === 'UPLOAD_FAILED') {
            statusDiv.textContent = "❌ Upload Failed: " + message.error;
        }
    });

    function setUIState(isRec) {
        if (isRec) {
            startBtn.style.display = 'none';
            stopBtn.style.display = 'block';
            statusDiv.textContent = "Recording in progress...";
        } else {
            startBtn.style.display = 'block';
            stopBtn.style.display = 'none';
        }
    }
});
