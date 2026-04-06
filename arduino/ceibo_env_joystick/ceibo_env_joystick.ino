#include <DHT.h>

// CEIBO Arduino bridge
// Reads a DHT22 temperature/humidity probe and a 2-axis joystick,
// then streams compact JSON lines over USB serial to the Raspberry Pi.

#define DHT_PIN 2
#define DHT_TYPE DHT22

const int JOYSTICK_X_PIN = A0;
const int JOYSTICK_Y_PIN = A1;
const int JOYSTICK_SW_PIN = 4;

const unsigned long SENSOR_INTERVAL_MS = 1000;
const unsigned long BUTTON_DEBOUNCE_MS = 40;
const int JOYSTICK_CENTER = 512;
const int JOYSTICK_DEAD_ZONE = 90;

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long lastSensorPublishMs = 0;
unsigned long lastButtonChangeMs = 0;
bool lastButtonStableState = HIGH;
bool lastButtonReading = HIGH;

int clampPercent(long value) {
  if (value < -100) return -100;
  if (value > 100) return 100;
  return (int)value;
}

int axisToPercent(int rawValue) {
  long centered = rawValue - JOYSTICK_CENTER;
  if (centered > -JOYSTICK_DEAD_ZONE && centered < JOYSTICK_DEAD_ZONE) {
    return 0;
  }

  if (centered > 0) {
    return clampPercent(map(centered, JOYSTICK_DEAD_ZONE, 511, 0, 100));
  }

  return clampPercent(map(centered, -JOYSTICK_DEAD_ZONE, -512, 0, -100));
}

const char* directionFromAxes(int xPercent, int yPercent) {
  if (xPercent == 0 && yPercent == 0) return "center";
  if (abs(xPercent) > abs(yPercent)) {
    return xPercent > 0 ? "right" : "left";
  }
  return yPercent > 0 ? "up" : "down";
}

void publishSnapshot(bool forceButtonEvent) {
  float humidity = dht.readHumidity();
  float temperatureC = dht.readTemperature();
  int rawX = analogRead(JOYSTICK_X_PIN);
  int rawY = analogRead(JOYSTICK_Y_PIN);
  bool pressed = (lastButtonStableState == LOW);
  int xPercent = axisToPercent(rawX);
  int yPercent = axisToPercent(rawY);
  const char* direction = directionFromAxes(xPercent, yPercent);

  Serial.print("{");
  Serial.print("\"device\":\"ceibo-arduino\",");
  Serial.print("\"temperature_c\":");
  if (isnan(temperatureC)) {
    Serial.print("null");
  } else {
    Serial.print(temperatureC, 1);
  }
  Serial.print(",\"humidity_pct\":");
  if (isnan(humidity)) {
    Serial.print("null");
  } else {
    Serial.print(humidity, 1);
  }
  Serial.print(",\"joystick\":{");
  Serial.print("\"x\":");
  Serial.print(xPercent);
  Serial.print(",\"y\":");
  Serial.print(yPercent);
  Serial.print(",\"pressed\":");
  Serial.print(pressed ? "true" : "false");
  Serial.print(",\"direction\":\"");
  Serial.print(direction);
  Serial.print("\"");
  if (forceButtonEvent) {
    Serial.print(",\"button_event\":true");
  }
  Serial.print("},\"ts_ms\":");
  Serial.print(millis());
  Serial.println("}");
}

void setup() {
  pinMode(JOYSTICK_SW_PIN, INPUT_PULLUP);
  Serial.begin(115200);
  dht.begin();
  delay(1200);
  publishSnapshot(false);
}

void loop() {
  unsigned long now = millis();
  bool buttonReading = digitalRead(JOYSTICK_SW_PIN);

  if (buttonReading != lastButtonReading) {
    lastButtonChangeMs = now;
    lastButtonReading = buttonReading;
  }

  bool buttonChanged = false;
  if ((now - lastButtonChangeMs) > BUTTON_DEBOUNCE_MS && buttonReading != lastButtonStableState) {
    lastButtonStableState = buttonReading;
    buttonChanged = true;
  }

  if (buttonChanged) {
    publishSnapshot(true);
  }

  if ((now - lastSensorPublishMs) >= SENSOR_INTERVAL_MS) {
    lastSensorPublishMs = now;
    publishSnapshot(false);
  }
}