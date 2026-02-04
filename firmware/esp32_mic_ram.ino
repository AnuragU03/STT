#include <WiFi.h>
#include <HTTPClient.h>

// ================= CONFIG =================
#define MIC_PIN        34
#define SAMPLE_RATE    16000
// RAM Constraint: 5 seconds * 16000 Hz * 2 bytes = 160 KB
// This fits in most ESP32 modules (WROOM/WROVER). 
// If it crashes, reduce to 3 seconds.
#define RECORD_SECONDS 5 

#define WAV_HEADER_SZ  44

// -------- WiFi --------
const char* ssid = "SSID";
const char* password = "Password";

// -------- Cloud --------
// NOTE: Appending filename query param manually in the loop
const char* UPLOAD_URL = "https://stt-premium-app.redbeach-eaccae08.centralindia.azurecontainerapps.io/api/upload";

// ================= GLOBALS =================
int chunkIndex = 0;
uint8_t *audioBuffer = NULL;
size_t bufferSize = 0;

// ================= WAV HEADER =================
void writeWavHeader(uint8_t *buffer, uint32_t dataSize) {
  uint32_t sampleRate = SAMPLE_RATE;
  uint16_t bitsPerSample = 16;
  uint16_t channels = 1;
  uint32_t byteRate = sampleRate * channels * bitsPerSample / 8;
  uint16_t blockAlign = channels * bitsPerSample / 8;
  uint32_t chunkSize = 36 + dataSize;
  
  // RIFF
  memcpy(buffer + 0, "RIFF", 4);
  memcpy(buffer + 4, &chunkSize, 4);
  memcpy(buffer + 8, "WAVEfmt ", 8);
  
  // Subchunk 1
  uint32_t subChunk1 = 16;
  uint16_t audioFmt = 1;
  memcpy(buffer + 16, &subChunk1, 4);
  memcpy(buffer + 20, &audioFmt, 2);
  memcpy(buffer + 22, &channels, 2);
  memcpy(buffer + 24, &sampleRate, 4);
  memcpy(buffer + 28, &byteRate, 4);
  memcpy(buffer + 32, &blockAlign, 2);
  memcpy(buffer + 34, &bitsPerSample, 2);
  
  // Subchunk 2
  memcpy(buffer + 36, "data", 4);
  memcpy(buffer + 40, &dataSize, 4);
}

// ================= RECORD AUDIO (TO RAM) =================
void recordAudio() {
  uint32_t samples = SAMPLE_RATE * RECORD_SECONDS;
  uint32_t dataSize = samples * 2;
  
  Serial.println("Recording " + String(RECORD_SECONDS) + "s to RAM...");
  
  // 1. Write Header
  writeWavHeader(audioBuffer, dataSize);
  
  // 2. Write Data
  // Start writing after the 44-byte header
  uint8_t *pcmPtr = audioBuffer + WAV_HEADER_SZ;
  
  for (uint32_t i = 0; i < samples; i++) {
    int adc = analogRead(MIC_PIN);       
    int16_t pcm = (adc - 2048) << 4;     
    
    // Copy 2 bytes to buffer
    memcpy(pcmPtr, &pcm, 2);
    pcmPtr += 2;
    
    // Simple delay for sampling rate (Not precise, good enough for MVP)
    delayMicroseconds(1000000 / SAMPLE_RATE);
  }
  
  Serial.println("Recording Complete.");
}

// ================= UPLOAD BUFFER =================
void uploadBuffer() {
  HTTPClient http;
  
  // Append filename
  String filename = "audio_" + String(chunkIndex) + ".wav";
  String url = String(UPLOAD_URL) + "?filename=" + filename;
  
  http.begin(url);
  http.addHeader("Content-Type", "audio/wav");
  
  Serial.println("Uploading " + filename + " (" + String(bufferSize) + " bytes)...");
  
  int code = http.sendRequest("POST", audioBuffer, bufferSize);
  
  if (code == 200) {
     Serial.println("Upload Success");
     chunkIndex++;
  } else {
     Serial.println("Upload Failed: " + String(code));
     // Retry? Or skip? For real-time, we skip to avoid lag.
  }
  
  http.end();
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);

  // Buffer Init
  uint32_t dataSize = (SAMPLE_RATE * RECORD_SECONDS) * 2;
  bufferSize = WAV_HEADER_SZ + dataSize;
  
  Serial.printf("Allocating RAM: %d bytes\n", bufferSize);
  audioBuffer = (uint8_t*)ps_malloc(bufferSize); // Try PSRAM first
  if (audioBuffer == NULL) {
      Serial.println("PSRAM not found/full, trying internal RAM...");
      audioBuffer = (uint8_t*)malloc(bufferSize);
  }
  
  if (audioBuffer == NULL) {
    Serial.println("CRITICAL: Not enough RAM!");
    while(1);
  }

  // WiFi
  WiFi.begin(ssid, password);
  Serial.print("WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConnected");

  // Audio Config
  analogReadResolution(12);
  analogSetPinAttenuation(MIC_PIN, ADC_11db);
}

// ================= LOOP =================
void loop() {
  recordAudio();
  uploadBuffer();
  // Loop immediately for continuous recording
}
