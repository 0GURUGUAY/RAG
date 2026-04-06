// CEIBO Arduino bridge for AMT1001 + analog joystick
//
// Common AMT1001 modules expose:
// - an analog humidity output
// - an NTC thermistor line for temperature
//
// This sketch reads both channels, applies a practical conversion,
// and streams JSON lines over USB serial to the Raspberry Pi.

const int AMT_HUMIDITY_PIN = A0;
const int AMT_TEMPERATURE_PIN = A1;
const int JOYSTICK_X_PIN = A2;
const int JOYSTICK_Y_PIN = A3;
const int JOYSTICK_SW_PIN = 4;

const unsigned long SENSOR_INTERVAL_MS = 1000;
const unsigned long BUTTON_DEBOUNCE_MS = 40;

// Keep 10-bit resolution explicitly so Uno/Nano and Teensy 4.0 behave the same.
const float ADC_MAX = 1023.0;
#if defined(CORE_TEENSY)
const float VREF = 3.3;
#else
const float VREF = 5.0;
#endif

// AMT1001 humidity transfer function commonly used on these modules:
// Vout / Vs = 0.0062 * RH + 0.16
const float HUMIDITY_SCALE = 0.0062;
const float HUMIDITY_OFFSET = 0.16;

// Temperature side assumptions for a common 10k NTC setup.
// Adjust if your breakout uses another thermistor value/beta.
const float NTC_SERIES_RESISTOR_OHMS = 10000.0;
const float NTC_NOMINAL_OHMS = 10000.0;
const float NTC_BETA = 3950.0;
const float NTC_T0_KELVIN = 298.15; // 25 C

const int JOYSTICK_CENTER = 512;
const int JOYSTICK_DEAD_ZONE = 90;

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

float readVoltage(int pin) {
  int raw = analogRead(pin);
  return (raw * VREF) / ADC_MAX;
}

float readHumidityPct(float temperatureC) {
  float voltage = readVoltage(AMT_HUMIDITY_PIN);
  float ratio = voltage / VREF;
  float humidity = (ratio - HUMIDITY_OFFSET) / HUMIDITY_SCALE;

  // Simple temperature compensation often applied to this sensor family.
  if (!isnan(temperatureC)) {
    float compensation = 1.0546 - (0.00216 * temperatureC);
    if (compensation > 0.2) {
      humidity = humidity / compensation;
    }
  }

  if (humidity < 0.0) humidity = 0.0;
  if (humidity > 100.0) humidity = 100.0;
  return humidity;
}

float readTemperatureC() {
  int raw = analogRead(AMT_TEMPERATURE_PIN);
  if (raw <= 0 || raw >= 1023) {
    return NAN;
  }

  float resistance = NTC_SERIES_RESISTOR_OHMS * ((ADC_MAX / raw) - 1.0);
  if (resistance <= 0.0) {
    return NAN;
  }

  float steinhart = resistance / NTC_NOMINAL_OHMS;
  steinhart = log(steinhart);
  steinhart /= NTC_BETA;
  steinhart += 1.0 / NTC_T0_KELVIN;
  steinhart = 1.0 / steinhart;
  return steinhart - 273.15;
}

void publishSnapshot(bool forceButtonEvent) {
  float temperatureC = readTemperatureC();
  float humidityPct = readHumidityPct(temperatureC);

  int rawX = analogRead(JOYSTICK_X_PIN);
  int rawY = analogRead(JOYSTICK_Y_PIN);
  bool pressed = (lastButtonStableState == LOW);
  int xPercent = axisToPercent(rawX);
  int yPercent = axisToPercent(rawY);
  const char* direction = directionFromAxes(xPercent, yPercent);

  Serial.print("{");
  Serial.print("\"device\":\"ceibo-arduino\",");
  Serial.print("\"sensor\":\"amt1001\",");
  Serial.print("\"temperature_c\":");
  if (isnan(temperatureC)) {
    Serial.print("null");
  } else {
    Serial.print(temperatureC, 1);
  }
  Serial.print(",\"humidity_pct\":");
  if (isnan(humidityPct)) {
    Serial.print("null");
  } else {
    Serial.print(humidityPct, 1);
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
  Serial.print("},\"raw\":{");
  Serial.print("\"humidity_adc\":");
  Serial.print(analogRead(AMT_HUMIDITY_PIN));
  Serial.print(",\"temperature_adc\":");
  Serial.print(analogRead(AMT_TEMPERATURE_PIN));
  Serial.print("},\"ts_ms\":");
  Serial.print(millis());
  Serial.println("}");
}

void setup() {
  pinMode(JOYSTICK_SW_PIN, INPUT_PULLUP);
  Serial.begin(115200);
#if defined(CORE_TEENSY)
  analogReadResolution(10);
#endif
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