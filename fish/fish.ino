#include <Arduino.h>
#include <WiFi.h>
#include "esp_camera.h"
#include <esp_http_server.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// ================= WIFI CONFIG =================
const char* ssid = "bps_cam";
const char* password = "12345678";
const int defaultFPS = 2;

// ================= HC-SR04 =================
#define TRIG_PIN 40 // CHANGE if needed
#define ECHO_PIN 41 // CHANGE if needed
float getDistanceCM() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  float distance = duration * 0.034 / 2.0;
  return distance;
}

// ================= CAMERA PINS (ESP32-S3) =================
#define PWDN_GPIO_NUM -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 15
#define SIOD_GPIO_NUM 4
#define SIOC_GPIO_NUM 5
#define Y2_GPIO_NUM 11
#define Y3_GPIO_NUM 9
#define Y4_GPIO_NUM 8
#define Y5_GPIO_NUM 10
#define Y6_GPIO_NUM 12
#define Y7_GPIO_NUM 18
#define Y8_GPIO_NUM 17
#define Y9_GPIO_NUM 16
#define VSYNC_GPIO_NUM 6
#define HREF_GPIO_NUM 7
#define PCLK_GPIO_NUM 13
#define LED_GPIO_NUM 2

// ================= STREAM DEFINITIONS =================
#define PART_BOUNDARY "123456789000000000000987654321"
static const char* STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";
httpd_handle_t server = NULL;

// ================= CAMERA INIT =================
bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if(psramFound()){
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 12;
    config.fb_count = 2;
    config.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 15;
    config.fb_count = 1;
    config.fb_location = CAMERA_FB_IN_DRAM;
  }
  config.grab_mode = CAMERA_GRAB_LATEST;
  return esp_camera_init(&config) == ESP_OK;
}

// ================= HTTP HANDLERS =================
// Sensor data handler (kept for Python dashboard)
static esp_err_t data_handler(httpd_req_t *req){
  float distance = getDistanceCM();
  char json[64];
  snprintf(json,sizeof(json),"{\"value\":%.2f}",distance);
  httpd_resp_set_type(req,"application/json");
  httpd_resp_send(req,json,strlen(json));
  return ESP_OK;
}

// Video stream handler (main focus)
static esp_err_t stream_handler(httpd_req_t *req){
  httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
  camera_fb_t *fb = NULL;
  char part_buf[64];
  while(true){
    fb = esp_camera_fb_get();
    if(!fb) break;
    size_t hlen = snprintf(part_buf,64,STREAM_PART,fb->len);
    httpd_resp_send_chunk(req,part_buf,hlen);
    httpd_resp_send_chunk(req,(const char*)fb->buf,fb->len);
    httpd_resp_send_chunk(req,STREAM_BOUNDARY,strlen(STREAM_BOUNDARY));
    esp_camera_fb_return(fb);
    delay(1000/defaultFPS);
  }
  return ESP_OK;
}

// Single frame capture (useful for Python processing)
static esp_err_t capture_handler(httpd_req_t *req){
  camera_fb_t *fb = esp_camera_fb_get();
  if(!fb){
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_send(req, (const char*)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  return ESP_OK;
}

// ================= SERVER START =================
void startServer(){
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  httpd_uri_t stream_uri = { "/stream", HTTP_GET, stream_handler, NULL };
  httpd_uri_t data_uri = { "/data", HTTP_GET, data_handler, NULL };
  httpd_uri_t capture_uri = { "/capture", HTTP_GET, capture_handler, NULL };
  if(httpd_start(&server,&config)==ESP_OK){
    httpd_register_uri_handler(server,&stream_uri);
    httpd_register_uri_handler(server,&data_uri);
    httpd_register_uri_handler(server,&capture_uri);
  }
}

// ================= SETUP =================
void setup(){
  Serial.begin(115200);
  pinMode(LED_GPIO_NUM, OUTPUT);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  if(!initCamera()){
    Serial.println("Camera Failed!");
    while(true);
  }
  WiFi.mode(WIFI_AP);
  WiFi.softAP(ssid,password);
  Serial.println("AP Started");
  Serial.println(WiFi.softAPIP());
  startServer();
}

// ================= LOOP =================
void loop(){
  delay(10000);
}