#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>

// ================= WIFI =================
const char* ssid = "RAGHAVENDRA 1 2G";
const char* password = "Password";

// ================= SETUP =================
// Select your device (Uncomment ONE)
//#define DEVICE_MAC "e08cfeb530b0" // Cam 1
#define DEVICE_MAC "e08cfeb61a74" // Cam 2

// ================= CLOUD =================
const char* UPLOAD_HOST = "stt-premium-app.redbeach-eaccae08.centralindia.azurecontainerapps.io";
const char* UPLOAD_PATH = "/api/upload_image";
const int   UPLOAD_PORT = 443;

// ... (Rest of Setup)

// ================= MULTIPART UPLOAD =================
void uploadImage(camera_fb_t *fb) {
  WiFiClientSecure client;
  client.setInsecure(); // Skip cert check

  if (!client.connect(UPLOAD_HOST, UPLOAD_PORT)) {
    Serial.println("Connection failed");
    return;
  }

  String boundary = "------------------------esp32cam";
  
  // Header for MAC Address
  String bodyHead = "--" + boundary + "\r\n" +
                    "Content-Disposition: form-data; name=\"mac_address\"\r\n\r\n" +
                    String(DEVICE_MAC) + "\r\n";
                    
  // Header for File
  bodyHead += "--" + boundary + "\r\n" +
              "Content-Disposition: form-data; name=\"file\"; filename=\"capture.jpg\"\r\n" +
              "Content-Type: image/jpeg\r\n\r\n";
              
  // Tail
  String bodyTail = "\r\n--" + boundary + "--\r\n";

  uint32_t totalLen = bodyHead.length() + fb->len + bodyTail.length();

  // POST Header
  client.println("POST " + String(UPLOAD_PATH) + " HTTP/1.1");
  client.println("Host: " + String(UPLOAD_HOST));
  client.println("Content-Length: " + String(totalLen));
  client.println("Content-Type: multipart/form-data; boundary=" + boundary);
  client.println();

  // Send Body
  client.print(bodyHead);
  client.write(fb->buf, fb->len);
  client.print(bodyTail);

  // Read Response
  while (client.connected()) {
    String line = client.readStringUntil('\n');
    if (line == "\r") break;
  }
  String response = client.readStringUntil('\n');
  Serial.println("Response: " + response);
  
  client.stop();
}

// ================= CAPTURE LOOP =================
unsigned long lastCapture = 0;

void loop() {
  server.handleClient();
  
  if (millis() - lastCapture > 30000) { // Wait 30 seconds before next capture
    lastCapture = millis();
    
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Capture failed");
      return;
    }
    
    uploadImage(fb);
    esp_camera_fb_return(fb);
  }
}
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

WebServer server(80);

// ================= WEB PAGE =================
const char PAGE[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<body>
  <h2>ESP32-CAM Image Upload</h2>
  <button onclick="fetch('/capture')">Capture & Upload</button>
</body>
</html>
)rawliteral";

// ================= CAPTURE + UPLOAD =================
void handleCapture() {
  Serial.println("[CAPTURE] Capturing image...");

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[ERROR] Camera capture failed");
    server.send(500, "text/plain", "Capture failed");
    return;
  }

  Serial.printf("[UPLOAD] Image size: %d bytes\n", fb->len);

  HTTPClient http;
  http.begin(UPLOAD_URL);
  
  // FIX: Explicitly set content type
  http.addHeader("Content-Type", "image/jpeg");

  int code = http.POST(fb->buf, fb->len);

  Serial.printf("[UPLOAD] Response code: %d\n", code);

  http.end();
  esp_camera_fb_return(fb);

  if (code == 200) {
    server.send(200, "text/plain", "Image uploaded successfully");
  } else {
    server.send(500, "text/plain", "Upload failed");
  }
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  Serial.println("\n[BOOT] ESP32-CAM Image Upload");

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;

  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAMESIZE_VGA;
  config.jpeg_quality = 12;
  config.fb_count     = 1;

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("[ERROR] Camera init failed");
    while (true);
  }

  // ===== Fix image orientation =====
  sensor_t *s = esp_camera_sensor_get();
  s->set_vflip(s, 1);
  s->set_hmirror(s, 1);

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) delay(500);

  Serial.print("[WiFi] IP: ");
  Serial.println(WiFi.localIP());

  server.on("/", []() {
    server.send_P(200, "text/html", PAGE);
  });

  server.on("/capture", HTTP_GET, handleCapture);
  server.begin();

  Serial.println("[WEB] Server started");
}

// ================= LOOP =================
void loop() {
  server.handleClient();
}
