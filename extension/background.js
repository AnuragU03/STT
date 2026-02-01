// background.js - Service Worker

// Constants
const OFFSCREEN_DOCUMENT_PATH = 'offscreen.html';
const SERVER_URL = 'https://stt-premium-app.redbeach-eaccae08.centralindia.azurecontainerapps.io/api/upload-hardware';

// State
let recordingTabId = null;
let isRecording = false;

// Listen for messages from Popup or Offscreen
// Listen for messages from Popup or Offscreen
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'START_RECORDING') {
        startRecording(message.streamId).then(() => {
            sendResponse({ success: true });
        });
        return true; // Keep channel open
    } else if (message.type === 'STOP_RECORDING') {
        stopRecording().then(() => {
            sendResponse({ success: true });
        });
        return true; // Keep channel open
    } else if (message.type === 'RECORDING_COMPLETE') {
        uploadRecording(message.blob);
        // No sendResponse needed here usually, but good practice to handle if sender waits
    } else if (message.type === 'LOG') {
        console.log("[Offscreen]", message.data);
    }
});

async function startRecording(streamId) {
    // Clean up any existing recording first
    if (isRecording) {
        console.log("[Background] Stopping existing recording first...");
        await stopRecording();
        // Give it a moment to fully cleanup
        await new Promise(resolve => setTimeout(resolve, 500));
    }

    console.log("[Background] Starting recording with streamId:", streamId);

    // 1. Create Offscreen Document (if not exists)
    await setupOffscreenDocument(OFFSCREEN_DOCUMENT_PATH);

    // 2. Get current tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    recordingTabId = tab.id;
    isRecording = true;

    // 3. Send command to Offscreen to start recording logic
    // IMPORTANT: Pass the streamId from popup!
    chrome.runtime.sendMessage({
        type: 'INIT_RECORDING',
        data: {
            streamId: streamId,  // <-- This was missing!
            targetTabId: recordingTabId
        }
    });

    // Update badge
    chrome.action.setBadgeText({ text: "REC" });
    chrome.action.setBadgeBackgroundColor({ color: "#FF0000" });
}

async function stopRecording() {
    console.log("[Background] Stop recording called. isRecording:", isRecording);

    isRecording = false;
    chrome.action.setBadgeText({ text: "" });

    // Tell offscreen to stop and cleanup
    try {
        chrome.runtime.sendMessage({ type: 'STOP_RECORDING_LOGIC' });
    } catch (e) {
        console.warn("[Background] Could not send stop message:", e);
    }

    // Give time for cleanup
    await new Promise(resolve => setTimeout(resolve, 300));
}

async function uploadRecording(dataUrl) {
    console.log("[Background] Starting upload...");

    try {
        // Convert Data URL to Blob
        if (!dataUrl || typeof dataUrl !== 'string' || !dataUrl.startsWith('data:')) {
            throw new Error("Invalid data URL received from recording");
        }

        // Fetch the data URL to convert to blob
        const response = await fetch(dataUrl);
        const blob = await response.blob();

        console.log("[Background] Blob created:", blob.type, blob.size, "bytes");

        if (blob.size === 0) {
            throw new Error("Recording is empty (0 bytes)");
        }

        // Create FormData
        const formData = new FormData();
        formData.append("file", blob, `meeting_${Date.now()}.webm`);

        // Upload to server
        console.log("[Background] Uploading to:", SERVER_URL);
        const uploadRes = await fetch(SERVER_URL, {
            method: 'POST',
            body: formData
        });

        if (uploadRes.ok) {
            const result = await uploadRes.json();
            console.log("[Background] Upload Success!", result);
            chrome.runtime.sendMessage({ type: 'UPLOAD_SUCCESS' });
        } else {
            const errorText = await uploadRes.text();
            console.error("[Background] Upload Failed:", uploadRes.status, errorText);
            chrome.runtime.sendMessage({ type: 'UPLOAD_FAILED', error: `${uploadRes.status}: ${errorText}` });
        }
    } catch (e) {
        console.error("[Background] Upload Error:", e);
        chrome.runtime.sendMessage({ type: 'UPLOAD_FAILED', error: e.message });
    }
}

// Utility to create offscreen doc
let creating; // A global promise to avoid race conditions
async function setupOffscreenDocument(path) {
    // Check if existing
    const existingContexts = await chrome.runtime.getContexts({
        contextTypes: ['OFFSCREEN_DOCUMENT'],
        documentUrls: [chrome.runtime.getURL(path)]
    });

    if (existingContexts.length > 0) {
        return;
    }

    // Create
    if (creating) {
        await creating;
    } else {
        creating = chrome.offscreen.createDocument({
            url: path,
            reasons: ['USER_MEDIA'],
            justification: 'Recording meeting audio',
        });
        await creating;
        creating = null;
    }
}
