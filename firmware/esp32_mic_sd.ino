#include <WiFi.h>
#include <HTTPClient.h>
#include "FS.h"
#include "SD_MMC.h"

// ================= CONFIG =================
#define MIC_PIN        34
#define SAMPLE_RATE    16000
#define RECORD_SECONDS 10
#define WAV_HEADER_SZ  44

// -------- WiFi --------
const char* ssid = "SSID";
const char* password = "Password";

// -------- Cloud --------
const char* UPLOAD_URL = "https://stt-premium-app.redbeach-eaccae08.centralindia.azurecontainerapps.io/api/upload";
const char* ACK_URL    = "https://stt-premium-app.redbeach-eaccae08.centralindia.azurecontainerapps.io/api/ack?file=";

// ================= GLOBALS =================
int chunkIndex = 0;

// ================= WAV HEADER =================
void writeWavHeader(File &file, uint32_t dataSize) {
  uint32_t sampleRate = SAMPLE_RATE;
  uint16_t bitsPerSample = 16;
  uint16_t channels = 1;
  uint32_t byteRate = sampleRate * channels * bitsPerSample / 8;
  uint16_t blockAlign = channels * bitsPerSample / 8;

  file.seek(0);
  file.write("RIFF", 4);
  uint32_t chunkSize = 36 + dataSize;
  file.write((uint8_t*)&chunkSize, 4);
  file.write("WAVEfmt ", 8);

  uint32_t subChunk1 = 16;
  uint16_t audioFmt = 1;

  file.write((uint8_t*)&subChunk1, 4);
  file.write((uint8_t*)&audioFmt, 2);
  file.write((uint8_t*)&channels, 2);
  file.write((uint8_t*)&sampleRate, 4);
  file.write((uint8_t*)&byteRate, 4);
  file.write((uint8_t*)&blockAlign, 2);
  file.write((uint8_t*)&bitsPerSample, 2);

  file.write("data", 4);
  file.write((uint8_t*)&dataSize, 4);
}

// ================= RECORD AUDIO =================
String recordAudio() {
  String filename = "/audio_" + String(chunkIndex) + ".wav";
  File file = SD_MMC.open(filename, FILE_WRITE);

  if (!file) {
    Serial.println("Failed to open file");
    return "";
  }

  // Reserve header
  for (int i = 0; i < WAV_HEADER_SZ; i++) file.write((uint8_t)0);

  uint32_t samples = SAMPLE_RATE * RECORD_SECONDS;
  uint32_t dataSize = samples * 2;

  Serial.println("Recording audio...");
  for (uint32_t i = 0; i < samples; i++) {
    int adc = analogRead(MIC_PIN);       // 0–4095
    int16_t pcm = (adc - 2048) << 4;     // scale to 16-bit
    file.write((uint8_t*)&pcm, 2);
    delayMicroseconds(1000000 / SAMPLE_RATE);
  }

  writeWavHeader(file, dataSize);
  file.close();

  Serial.println("Saved: " + filename);
  return filename;
}

// ================= UPLOAD FILE =================
bool uploadFile(String path) {
  File file = SD_MMC.open(path);
  if (!file) return false;

  HTTPClient http;
  
  // Append filename to URL so server knows what we are uploading
  String url = String(UPLOAD_URL) + "?filename=" + path.substring(1); 
  http.begin(url);
  http.addHeader("Content-Type", "audio/wav");

  Serial.println("Uploading " + path + " to " + url);
  int code = http.sendRequest("POST", &file, file.size());

  http.end();
  file.close();

  return (code == 200);
}

// ================= WAIT FOR ACK =================
bool waitForAck(String filename) {
  HTTPClient http;
  String url = String(ACK_URL) + filename;

  Serial.println("Waiting for ACK...");
  for (int i = 0; i < 30; i++) {  // ~60 seconds max
    http.begin(url);
    int code = http.GET();
    if (code == 200) {
      String payload = http.getString();
      if (payload.indexOf("done") >= 0) {
        http.end();
        Serial.println("ACK received");
        return true;
      }
    }
    http.end();
    delay(2000);
  }
  return false;
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);

  WiFi.begin(ssid, password);
  Serial.print("WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConnected");

  if (!SD_MMC.begin()) {
    Serial.println("SD init failed");
    while (true);
  }

  analogReadResolution(12);
  analogSetPinAttenuation(MIC_PIN, ADC_11db);
}

// ================= LOOP =================
void loop() {
  String file = recordAudio();
  if (file == "") return;

  if (uploadFile(file)) {
    if (waitForAck(file.substring(1))) {
      SD_MMC.remove(file);
      Serial.println("File deleted");
      chunkIndex++;
    }
  }

  delay(2000);
}
