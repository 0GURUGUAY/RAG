#if defined(CORE_TEENSY)
constexpr float VREF = 3.3f;
#else
constexpr float VREF = 5.0f;
#endif

constexpr unsigned long FRAME_INTERVAL_MS = 1000;
constexpr int LED_PIN = LED_BUILTIN;

unsigned long lastFrameMs = 0;
unsigned long frameIndex = 0;

float clampFloat(float value, float low, float high) {
  if (value < low) return low;
  if (value > high) return high;
  return value;
}

int clampInt(int value, int low, int high) {
  if (value < low) return low;
  if (value > high) return high;
  return value;
}

float pseudoNoise(float amplitude) {
  const long bucket = random(-1000, 1001);
  return amplitude * (static_cast<float>(bucket) / 1000.0f);
}

float buildTemperatureC(unsigned long ms) {
  const float seconds = ms / 1000.0f;
  const float slowWave = sinf(seconds / 37.0f);
  const float fastWave = 0.45f * sinf(seconds / 8.5f + 1.1f);
  return clampFloat(21.5f + 3.2f * slowWave + fastWave + pseudoNoise(0.35f), 14.0f, 32.0f);
}

float buildHumidityPct(unsigned long ms) {
  const float seconds = ms / 1000.0f;
  const float slowWave = sinf(seconds / 51.0f + 0.7f);
  const float fastWave = 0.30f * sinf(seconds / 11.0f);
  return clampFloat(61.0f + 12.0f * slowWave + 5.5f * fastWave + pseudoNoise(1.4f), 35.0f, 92.0f);
}

int buildJoystickAxis(unsigned long ms, float divisor, float phase) {
  const float seconds = ms / 1000.0f;
  const float wave = sinf(seconds / divisor + phase);
  const float value = 512.0f + 410.0f * wave + pseudoNoise(22.0f);
  return clampInt(static_cast<int>(value), 0, 1023);
}

int buildJoystickButton(unsigned long index) {
  return (index % 17 == 0 || index % 29 == 0) ? 1 : 0;
}

void printFloatOrNull(float value, int digits) {
  if (isnan(value)) {
    Serial.print("null");
    return;
  }
  Serial.print(value, digits);
}

void emitFrame() {
  const unsigned long now = millis();
  const float temperatureC = buildTemperatureC(now);
  const float humidityPct = buildHumidityPct(now);
  const int joystickX = buildJoystickAxis(now, 6.5f, 0.0f);
  const int joystickY = buildJoystickAxis(now, 9.0f, 1.7f);
  const int joystickButton = buildJoystickButton(frameIndex);

  Serial.print('{');
  Serial.print("\"device\":\"ceibo-teensy4-fake\",");
  Serial.print("\"sensor\":\"bench-simulator\",");
  Serial.print("\"frame\":");
  Serial.print(frameIndex);
  Serial.print(',');
  Serial.print("\"uptime_ms\":");
  Serial.print(now);
  Serial.print(',');
  Serial.print("\"vref\":");
  Serial.print(VREF, 2);
  Serial.print(',');
  Serial.print("\"temperature_c\":");
  printFloatOrNull(temperatureC, 2);
  Serial.print(',');
  Serial.print("\"humidity_pct\":");
  printFloatOrNull(humidityPct, 2);
  Serial.print(',');
  Serial.print("\"joystick\":{");
  Serial.print("\"x\":");
  Serial.print(joystickX);
  Serial.print(',');
  Serial.print("\"y\":");
  Serial.print(joystickY);
  Serial.print(',');
  Serial.print("\"button\":");
  Serial.print(joystickButton);
  Serial.print('}');
  Serial.println('}');

  digitalWrite(LED_PIN, (frameIndex % 2 == 0) ? HIGH : LOW);
  frameIndex += 1;
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

#if defined(CORE_TEENSY)
  analogReadResolution(10);
#endif

  Serial.begin(115200);
  const unsigned long waitStart = millis();
  while (!Serial && (millis() - waitStart) < 4000) {
  }

  randomSeed(
    static_cast<unsigned long>(micros()) ^
    static_cast<unsigned long>(analogRead(A0)) ^
    static_cast<unsigned long>(analogRead(A1))
  );
}

void loop() {
  const unsigned long now = millis();
  if (now - lastFrameMs < FRAME_INTERVAL_MS) {
    return;
  }
  lastFrameMs = now;
  emitFrame();
}