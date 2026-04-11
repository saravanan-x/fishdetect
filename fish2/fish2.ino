#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_BMP085.h>
#include "esp_camera.h"
#include <esp_http_server.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "DHT.h"
#include <OneWire.h>
#include <DallasTemperature.h>

volatile float currentDistance = 0.0f;
volatile float waterTemp = -99.0f;
volatile float surfaceTemp = -99.0f;
volatile float pressure_hPa = -1.0f;
volatile float altitude_m = -1.0f;
volatile int turbidityValue = 0;
String waterQuality = "Unknown";

bool bmp_ok = false;

// ================= WIFI =================
const char* ssid = "bps_wifi";
const char* password = "sagabps@235";

// ================= PINS =================
#define TRIG_PIN      42
#define ECHO_PIN      41
#define DHT11_PIN     20
#define ONE_WIRE_BUS  19
#define TURBIDITY_PIN 47     // ← Turbidity sensor digital output
#define I2C_SDA       21
#define I2C_SCL       14
#define LED_GPIO_NUM  2

// ================= SENSORS =================
DHT dht(DHT11_PIN, DHT11);
Adafruit_BMP085 bmp;
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature ds18b20(&oneWire);

float duration, distance;

float getDistanceCM(){
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  duration = pulseIn(ECHO_PIN, HIGH);
  distance = (duration*.0343)/2;
  Serial.print("Distance: ");
  Serial.println(distance);
  return distance;
}


// ================= CAMERA PINS =================
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

// ================= MJPEG STREAM HANDLER =================
static esp_err_t stream_handler(httpd_req_t *req) {
    camera_fb_t * fb = NULL;
    esp_err_t res = ESP_OK;
    char part_buf[64];

    res = httpd_resp_set_type(req, "multipart/x-mixed-replace; boundary=frame");
    if (res != ESP_OK) return res;

    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

    while (true) {
        fb = esp_camera_fb_get();
        if (!fb) {
            Serial.println("Camera capture failed");
            return ESP_FAIL;
        }

        // Send frame header
        int len = snprintf(part_buf, sizeof(part_buf),
                           "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n",
                           fb->len);

        res = httpd_resp_send_chunk(req, part_buf, len);
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
        }
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, "\r\n", 2);
        }

        esp_camera_fb_return(fb);

        if (res != ESP_OK) break;

        delay(30); 
    }

    return res;
}

// ================= HANDLERS =================
static esp_err_t sensors_handler(httpd_req_t *req) {
    char json[300];
    snprintf(json, sizeof(json),
             "{\"distance\":%.1f,\"waterTemp\":%.1f,\"surfaceTemp\":%.1f,\"pressure\":%.1f,\"altitude\":%.1f,\"turbidity\":%d,\"quality\":\"%s\"}",
             currentDistance, waterTemp, surfaceTemp, pressure_hPa, altitude_m, turbidityValue, waterQuality.c_str());

    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-cache");
    httpd_resp_set_hdr(req, "Connection", "close");
    return httpd_resp_send(req, json, HTTPD_RESP_USE_STRLEN);
}

// ================= SERVER =================
httpd_handle_t server = NULL;

void startServer() {
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_uri_handlers = 8;

    httpd_uri_t uris[] = {
        {"/sensors", HTTP_GET, sensors_handler, NULL},
        {"/stream",  HTTP_GET, stream_handler,  NULL}
    };

    if (httpd_start(&server, &config) == ESP_OK) {
        for (auto &u : uris) httpd_register_uri_handler(server, &u);
        Serial.println("HTTP server started → JSON: /sensors | Video stream: /stream");
    } else {
        Serial.println("HTTP server failed");
    }
}

// ================= SETUP =================
void setup() {
    Serial.begin(115200);
    delay(300);

    pinMode(LED_GPIO_NUM, OUTPUT);
    digitalWrite(LED_GPIO_NUM, LOW);
    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);
    pinMode(TURBIDITY_PIN, INPUT);        // Turbidity sensor

    Serial.println("\n=== Sensor Init ===");
    dht.begin();
    ds18b20.begin();
    Serial.print("DS18B20 devices found: ");
    Serial.println(ds18b20.getDeviceCount());

    Wire.begin(I2C_SDA, I2C_SCL);
    // I2C scanner...
    Serial.println("Scanning I2C bus...");
    int devices = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.printf("I2C device found at 0x%02X\n", addr);
            devices++;
        }
    }
    if (devices == 0) Serial.println("No I2C devices found!");

    bmp_ok = bmp.begin();
    if (bmp_ok) Serial.println("BMP180/085 initialized OK");
    else Serial.println("BMP180/085 NOT found");

    Serial.println("Initializing camera...");
    if (!initCamera()) {
        Serial.println("Camera failed → halting");
        while (true) delay(1000);
    }

    WiFi.begin(ssid, password);
    Serial.print("WiFi ");
    while (WiFi.status() != WL_CONNECTED) {
        delay(400);
        Serial.print(".");
    }
    Serial.println("\nConnected → http://" + WiFi.localIP().toString());

    startServer();
}

// ================= CAMERA INIT (unchanged) =================
bool initCamera() {
    camera_config_t config{};
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

    if (psramFound()) {
        config.frame_size = FRAMESIZE_QVGA;    
        config.jpeg_quality = 25;              
        config.fb_count = 2;                    
        config.fb_location = CAMERA_FB_IN_PSRAM;
    } else {
        config.frame_size = FRAMESIZE_QQVGA;    
        config.jpeg_quality = 30;
        config.fb_count = 1;
        config.fb_location = CAMERA_FB_IN_DRAM;
    }

    config.grab_mode = CAMERA_GRAB_LATEST;

    if (esp_camera_init(&config) != ESP_OK) return false;

    sensor_t *s = esp_camera_sensor_get();
    if (s) {
        s->set_brightness(s, 1);
        s->set_contrast(s, 1);
        s->set_saturation(s, 0);
        s->set_exposure_ctrl(s, 1);
        s->set_ae_level(s, 1);
        s->set_aec_value(s, 400);
        s->set_agc_gain(s, 0);
        s->set_gainceiling(s, (gainceiling_t)4);
    }
    return true;
}

// ================= LOOP =================
void loop() {
    currentDistance = getDistanceCM();

    // DHT11
    float t_dht = dht.readTemperature();
    if (!isnan(t_dht)) surfaceTemp = t_dht;

    // DS18B20
    ds18b20.requestTemperatures();
    float t_ds = ds18b20.getTempCByIndex(0);
    if (t_ds != DEVICE_DISCONNECTED_C && t_ds > -50 && t_ds < 100) waterTemp = t_ds;

    // BMP
    if (bmp_ok) {
        pressure_hPa = bmp.readPressure() / 100.0f;
        altitude_m = bmp.readAltitude(1013.25);   // Change to your local sea-level hPa if needed
    }

    // Turbidity Sensor (Digital)
    turbidityValue = digitalRead(TURBIDITY_PIN);
    waterQuality = (turbidityValue == HIGH) ? "Good" : "Bad";

    // Debug print
    Serial.printf("Dist: %.1f cm | DHT: %.1f °C | DS18: %.1f °C | Pres: %.1f hPa | Alt: %.1f m | Turbidity: %d (%s)\n",
                  currentDistance, surfaceTemp, waterTemp, pressure_hPa, altitude_m, turbidityValue, waterQuality.c_str());

    delay(2000);
}