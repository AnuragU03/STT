// offscreen.js - The heavy lifter

let mediaRecorder;
let recordedChunks = [];
let audioContext;
let dest; // MediaStreamAudioDestinationNode
let micStream;
let tabStream;

chrome.runtime.onMessage.addListener((message) => {
    if (message.type === 'INIT_RECORDING') {
        // Cleanup any existing recording first
        cleanup();
        startRecordingLogic(message.data.streamId);
    } else if (message.type === 'STOP_RECORDING_LOGIC') {
        stopRecordingLogic();
    }
});

async function startRecordingLogic(streamId) {
    try {
        console.log("Initializing Audio Context...");
        audioContext = new AudioContext();
        dest = audioContext.createMediaStreamDestination();

        // 1. Get Tab Stream (Speakers) using the passed streamId
        if (streamId) {
            tabStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    mandatory: {
                        chromeMediaSource: 'tab',
                        chromeMediaSourceId: streamId
                    }
                },
                video: false
            });

            // Connect Tab stream to destination and also to speaker (so user can still hear it)
            const tabSource = audioContext.createMediaStreamSource(tabStream);
            tabSource.connect(dest);
            tabSource.connect(audioContext.destination); // Playback logic
        }

        // 2. Get Mic Stream
        try {
            micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
            const micSource = audioContext.createMediaStreamSource(micStream);
            micSource.connect(dest);
        } catch (e) {
            console.warn("Could not get microphone permission in offscreen:", e);
            // Just proceed with tab audio if mic fails
        }

        // 3. Start Recorder on the mixed stream
        const mixedStream = dest.stream;
        mediaRecorder = new MediaRecorder(mixedStream, { mimeType: 'audio/webm' });
        recordedChunks = [];

        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                recordedChunks.push(event.data);
            }
        };

        mediaRecorder.onstop = () => {
            const blob = new Blob(recordedChunks, { type: 'audio/webm' });

            // Convert blob to Data URL to pass back to background
            const reader = new FileReader();
            reader.onloadend = () => {
                chrome.runtime.sendMessage({
                    type: 'RECORDING_COMPLETE',
                    blob: reader.result
                });
            };
            reader.readAsDataURL(blob);

            // Cleanup
            cleanup();
        };

        mediaRecorder.start();
        console.log("Recording started!");

    } catch (e) {
        console.error("Error in offscreen recording:", e);
        chrome.runtime.sendMessage({ type: 'LOG', data: "Error: " + e.message });
    }
}

function stopRecordingLogic() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
    }
}

function cleanup() {
    if (tabStream) {
        tabStream.getTracks().forEach(track => track.stop());
        tabStream = null;
    }
    if (micStream) {
        micStream.getTracks().forEach(track => track.stop());
        micStream = null;
    }
    if (audioContext && audioContext.state !== 'closed') {
        audioContext.close();
    }
    audioContext = null;
    mediaRecorder = null;
    dest = null;
}
