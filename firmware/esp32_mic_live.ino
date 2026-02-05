#include <WiFi.h>
#include <WebServer.h>
#include <WiFiClientSecure.h>
#include "driver/i2s.h"

// ================= WIFI =================
const char* ssid = "Menoone";
const char* password = "Password";

// ================= CLOUD =================
const char* CLOUD_HOST = "stt-premium-app.redbeach-eaccae08.centralindia.azurecontainerapps.io";
const int   CLOUD_PORT = 443; // MUST be 443 for Azure HTTPS
const char* CLOUD_PATH = "/api/upload?filename=live.wav";

// ================= AUDIO CONFIG =================
#define SAMPLE_RATE 16000

// ================= I2S PINS =================
#define I2S_WS   25
#define I2S_SD   33
#define I2S_SCK  26

WebServer server(80);

// ================= STREAM STATE =================
bool streaming = false;
WiFiClientSecure streamClient; // Secure Client for HTTPS

// ================= WAV HEADER (STREAMED AS FIRST CHUNK) =================
void sendWavHeader(WiFiClientSecure &client) {
  uint32_t sampleRate = SAMPLE_RATE;
  uint16_t channels = 1;
  uint16_t bits = 16;
  uint32_t byteRate = sampleRate * channels * bits / 8;
  uint16_t blockAlign = channels * bits / 8;
  uint32_t dataSize = 0xFFFFFFFF; // Unknown length

  // Prepare header buffer (44 bytes)
  uint8_t header[44];
  
  // RIFF
  memcpy(header, "RIFF", 4);
  uint32_t fileSize = 36 + dataSize;
  memcpy(header + 4, &fileSize, 4);
  memcpy(header + 8, "WAVEfmt ", 8);
  
  // fmt chunk
  uint32_t subChunk1 = 16;
  uint16_t audioFmt = 1;
  memcpy(header + 16, &subChunk1, 4);
  memcpy(header + 20, &audioFmt, 2);
  memcpy(header + 22, &channels, 2);
  memcpy(header + 24, &sampleRate, 4);
  memcpy(header + 28, &byteRate, 4);
  memcpy(header + 32, &blockAlign, 2);
  memcpy(header + 34, &bits, 2);
  
  // data chunk
  memcpy(header + 36, "data", 4);
  memcpy(header + 40, &dataSize, 4);

  // Send Chunk Size (44 bytes = 0x2C)
  client.print("2C\r\n");
  // Send Data
  client.write(header, 44);
  // Send Chunk Terminator
  client.print("\r\n");
}

// ================= I2S INIT =================
void setupI2S() {
  i2s_config_t config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 512,
    .use_apll = true
  };

  i2s_pin_config_t pins = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = -1,
    .data_in_num = I2S_SD
  };

  i2s_driver_install(I2S_NUM_0, &config, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pins);
  i2s_zero_dma_buffer(I2S_NUM_0);
}

// ================= WEB =================
void handleRoot() {
  server.send(200, "text/html",
    "<h2>ESP32 Live Audio Stream</h2>"
    "<button onclick=\"fetch('/start')\">Start Stream</button><br><br>"
    "<button onclick=\"fetch('/stop')\">Stop Stream</button>"
  );
}

// ================= START STREAM =================
void handleStart() {
  if (streaming) {
    server.send(200, "text/plain", "Already streaming");
    return;
  }

  streamClient.setInsecure(); // Skip cert validation for simplicity
  if (!streamClient.connect(CLOUD_HOST, CLOUD_PORT)) {
    server.send(500, "text/plain", "Cloud connection failed");
    return;
  }

  // HTTP chunked POST
  streamClient.print(
    "POST " + String(CLOUD_PATH) + " HTTP/1.1\r\n"
    "Host: " + String(CLOUD_HOST) + "\r\n"
    "Content-Type: audio/wav\r\n"
    "Transfer-Encoding: chunked\r\n\r\n"
  );

  sendWavHeader(streamClient);
  streaming = true;

  server.send(200, "text/plain", "Live streaming started");
}

// ================= STOP STREAM =================
void handleStop() {
  if (!streaming) {
    server.send(200, "text/plain", "Not streaming");
    return;
  }

  // End chunked transfer
  streamClient.print("0\r\n\r\n");
  streamClient.stop();
  streaming = false;

  server.send(200, "text/plain", "Streaming stopped");
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) delay(500);
  Serial.println("WiFi Connected. IP: " + WiFi.localIP().toString());

  setupI2S();

  server.on("/", handleRoot);
  server.on("/start", handleStart);
  server.on("/stop", handleStop);
  server.begin();
}

// ================= LOOP =================
void loop() {
  server.handleClient();

  if (!streaming) return;

  int32_t buffer[512];
  size_t bytesRead;

  i2s_read(I2S_NUM_0, buffer, sizeof(buffer), &bytesRead, 0);

  // Convert & stream PCM
  for (int i = 0; i < bytesRead / 4; i++) {
    int32_t sample = buffer[i] >> 16;
    sample *= 2;    // Boost volume

    if (sample > 32767) sample = 32767;
    if (sample < -32768) sample = -32768;

    int16_t pcm = (int16_t)sample;

    // Chunk size: 2 bytes (1 sample) - Inefficient but low latency
    // Better: buffer 512 bytes then send chunk
    // But keeping original logic for now
    char chunk[8];
    sprintf(chunk, "%X\r\n", 2); 
    streamClient.print(chunk);
    streamClient.write((uint8_t*)&pcm, 2);
    streamClient.print("\r\n");
  }
}
