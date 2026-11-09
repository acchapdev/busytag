// busytag firmware for the Waveshare ESP32-C6-LCD-1.47.
//
// The host sends one JSON object per line over USB serial and gets one JSON reply line
// ({"ok":true,...} or {"ok":false,"error":"..."}). The firmware draws the status screen
// itself, so the host never uploads images. Protocol (see src/busytag/esp32.py):
//   {"cmd":"hello"}                                    identify; reply has fw, size, settings
//   {"cmd":"status","top":"attention","rows":[[label,state,detail,"RRGGBB"],...],
//    "led":{"effect":"pulse","color":"RRGGBB","low":"RRGGBB"}}
//   {"cmd":"idle"}                                     idle screen, LED off
//   {"cmd":"led","effect":"solid|pulse|off","color":"RRGGBB","low":"RRGGBB"}
//   {"cmd":"brightness"[,"value":1-100]}               backlight, saved in flash
//   {"cmd":"rotate"[,"value":0-3]}                     screen rotation, saved in flash
//   {"cmd":"fill","color":"RRGGBB"}
//   {"cmd":"screen"}                                   what is shown: {"screen":{cmd...},"led":{...}}

#include <Arduino.h>
#include <SPI.h>
#include <Preferences.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <ArduinoJson.h>
#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/FreeSansBold12pt7b.h>

#define FIRMWARE_VERSION "0.2.0"

// Board wiring (Waveshare ESP32-C6-LCD-1.47)
#define PIN_MOSI 6
#define PIN_SCLK 7
#define PIN_CS 14
#define PIN_DC 15
#define PIN_RST 21
#define PIN_BACKLIGHT 22
#define PIN_RGB_LED 8
// This board's LED takes RGB order, not the usual WS2812 GRB (verified: GRB showed red as green)
#define LED_ORDER LED_COLOR_ORDER_RGB

// Landscape with the USB-C on the right; `rotate 1` flips it if the case is the other way
#define DEFAULT_ROTATION 3

Adafruit_ST7789 tft(&SPI, PIN_CS, PIN_DC, PIN_RST);
GFXcanvas16 *canvas;
Preferences prefs;

int brightness = 80;
int rotation = DEFAULT_ROTATION;
String last_screen = "{\"cmd\":\"idle\"}";

// LED effect, run from loop()
enum Effect { EFFECT_OFF, EFFECT_SOLID, EFFECT_PULSE };
Effect led_effect = EFFECT_OFF;
uint32_t led_color = 0, led_low = 0, led_written = 0xFFFFFFFF;
const uint32_t PULSE_PERIOD_MS = 1600;

char line[4096];
size_t line_length = 0;
bool line_overflow = false;

// --- helpers -----------------------------------------------------------------

uint32_t parse_hex(const char *text, uint32_t fallback = 0) {
  if (!text || strlen(text) != 6) return fallback;
  char *end;
  uint32_t value = strtoul(text, &end, 16);
  return *end ? fallback : value;
}

String hex_color(uint32_t color) {
  char text[7];
  snprintf(text, sizeof(text), "%06lX", (unsigned long)(color & 0xFFFFFF));
  return text;
}

uint16_t rgb565(uint32_t color) {
  return ((color >> 8) & 0xF800) | ((color >> 5) & 0x07E0) | ((color >> 3) & 0x001F);
}

uint16_t text_width(const String &text) {
  int16_t x, y;
  uint16_t w, h;
  canvas->getTextBounds(text, 0, 0, &x, &y, &w, &h);
  return w + x;
}

// Shorten with "..." until it fits (the current font must be set)
String fit(String text, int max_width) {
  if (text_width(text) <= max_width) return text;
  while (text.length() && text_width(text + "...") > max_width) text.remove(text.length() - 1);
  return text + "...";
}

int draw_wrapped(const String &text, int x, int y, int max_width, int line_height, int max_lines) {
  String current;
  int lines = 0;
  int start = 0;
  while (start <= (int)text.length() && lines < max_lines) {
    int space = text.indexOf(' ', start);
    String word = text.substring(start, space < 0 ? text.length() : space);
    start = space < 0 ? text.length() + 1 : space + 1;
    String candidate = current.length() ? current + " " + word : word;
    if (text_width(candidate) <= max_width || !current.length()) {
      current = candidate;
      continue;
    }
    bool last = lines == max_lines - 1;
    canvas->setCursor(x, y + lines * line_height);
    canvas->print(fit(last ? current + " " + word + " ..." : current, max_width));
    lines++;
    current = word;
  }
  if (current.length() && lines < max_lines) {
    canvas->setCursor(x, y + lines * line_height);
    canvas->print(fit(current, max_width));
    lines++;
  }
  return lines;
}

void flush_canvas() {
  tft.drawRGBBitmap(0, 0, canvas->getBuffer(), canvas->width(), canvas->height());
}

void set_backlight(int percent) {
  ledcWrite(PIN_BACKLIGHT, map(constrain(percent, 1, 100), 0, 100, 0, 1023));
}

void apply_rotation() {
  tft.setRotation(rotation);
  delete canvas;
  canvas = new GFXcanvas16(tft.width(), tft.height());
}

// --- screens -----------------------------------------------------------------

struct Look {
  const char *state;
  const char *headline;
  uint32_t background;
  uint32_t text;
};

const Look LOOKS[] = {
  {"attention", "NEEDS YOU", 0xC2410C, 0xFB923C},
  {"error", "ERROR", 0xB91C1C, 0xF87171},
  {"done", "DONE", 0x15803D, 0x4ADE80},
  {"working", "WORKING", 0x1D4ED8, 0x60A5FA},
};

const Look &look_for(const char *state) {
  for (const Look &look : LOOKS) {
    if (state && strcmp(look.state, state) == 0) return look;
  }
  return LOOKS[3];
}

void draw_idle() {
  int w = canvas->width(), h = canvas->height();
  canvas->fillScreen(rgb565(0x0B0F19));
  canvas->setTextColor(rgb565(0x6B7280));
  canvas->setFont(&FreeSansBold12pt7b);
  String title = "busytag";
  canvas->setCursor((w - text_width(title)) / 2, h / 2 - 4);
  canvas->print(title);
  canvas->setFont(&FreeSans9pt7b);
  canvas->setTextColor(rgb565(0x4B5563));
  String note = "no active agents";
  canvas->setCursor((w - text_width(note)) / 2, h / 2 + 22);
  canvas->print(note);
  flush_canvas();
}

// Landscape: colored header, most urgent agent on the left, every agent on the right
void draw_status(const char *top, JsonArray rows) {
  int w = canvas->width(), h = canvas->height();
  const Look &look = look_for(top);
  int header = 42;

  canvas->fillScreen(rgb565(0x0B0F19));
  canvas->fillRect(0, 0, w, header, rgb565(look.background));
  canvas->setTextColor(ST77XX_WHITE);
  canvas->setFont(&FreeSansBold12pt7b);
  canvas->setCursor(10, 29);
  canvas->print(look.headline);
  if (rows.size() > 1) {
    canvas->setFont(&FreeSans9pt7b);
    String count = String(rows.size()) + " agents";
    canvas->setCursor(w - 10 - text_width(count), 27);
    canvas->print(count);
  }
  if (rows.size() == 0) {
    flush_canvas();
    return;
  }

  // Most urgent agent: name and what it is waiting for
  int left_width = 176;
  JsonArray first = rows[0];
  canvas->setFont(&FreeSansBold12pt7b);
  canvas->setTextColor(ST77XX_WHITE);
  canvas->setCursor(10, header + 28);
  canvas->print(fit(first[0] | "", left_width));
  canvas->setFont(&FreeSans9pt7b);
  canvas->setTextColor(rgb565(0xD1D5DB));
  draw_wrapped(first[2] | "", 10, header + 52, left_width, 20, 4);

  // Every active agent: dot in its type color, name in its state color
  int panel_x = 194, panel_y = header + 8;
  int panel_w = w - panel_x - 6, panel_h = h - panel_y - 6;
  canvas->fillRoundRect(panel_x, panel_y, panel_w, panel_h, 8, rgb565(0x111827));
  int row_height = 22;
  int max_rows = (panel_h - 6) / row_height;
  int count = rows.size();
  int shown = count <= max_rows ? count : max_rows - 1;
  int y = panel_y + 3 + row_height / 2;
  for (int i = 0; i < shown; i++) {
    JsonArray row = rows[i];
    canvas->fillCircle(panel_x + 11, y, 5, rgb565(parse_hex(row[3] | "FFFFFF", 0xFFFFFF)));
    canvas->setTextColor(rgb565(look_for(row[1] | "").text));
    canvas->setCursor(panel_x + 22, y + 6);
    canvas->print(fit(row[0] | "", panel_w - 28));
    y += row_height;
  }
  if (count > shown) {
    canvas->setTextColor(rgb565(0x9CA3AF));
    canvas->setCursor(panel_x + 22, y + 6);
    canvas->print("+" + String(count - shown) + " more");
  }
  flush_canvas();
}

// --- LED ---------------------------------------------------------------------

void set_led(JsonVariantConst led) {
  const char *effect = led["effect"] | "off";
  led_color = parse_hex(led["color"] | "000000");
  led_low = parse_hex(led["low"] | "000000");
  led_effect = strcmp(effect, "pulse") == 0 ? EFFECT_PULSE
             : strcmp(effect, "solid") == 0 ? EFFECT_SOLID
             : EFFECT_OFF;
}

uint32_t mix(uint32_t a, uint32_t b, float t) {
  uint32_t out = 0;
  for (int shift = 0; shift <= 16; shift += 8) {
    float ca = (a >> shift) & 0xFF, cb = (b >> shift) & 0xFF;
    out |= (uint32_t)(ca + (cb - ca) * t + 0.5f) << shift;
  }
  return out;
}

void update_led() {
  uint32_t color = 0;
  if (led_effect == EFFECT_SOLID) color = led_color;
  if (led_effect == EFFECT_PULSE) {
    // Triangle wave between the low and full color
    float phase = (millis() % PULSE_PERIOD_MS) / (float)PULSE_PERIOD_MS;
    color = mix(led_low, led_color, phase < 0.5f ? phase * 2 : 2 - phase * 2);
  }
  if (color == led_written) return;
  led_written = color;
  rgbLedWriteOrdered(PIN_RGB_LED, LED_ORDER, color >> 16, (color >> 8) & 0xFF, color & 0xFF);
}

// --- protocol ----------------------------------------------------------------

void reply_error(const char *message) {
  JsonDocument out;
  out["ok"] = false;
  out["error"] = message;
  serializeJson(out, Serial);
  Serial.println();
}

void handle(const char *text, bool redraw_only = false) {
  JsonDocument doc;
  if (deserializeJson(doc, text)) {
    if (!redraw_only) reply_error("invalid JSON");
    return;
  }
  const char *cmd = doc["cmd"] | "";
  JsonDocument out;
  out["ok"] = true;

  if (strcmp(cmd, "hello") == 0) {
    out["device"] = "busytag-esp32";
    out["fw"] = FIRMWARE_VERSION;
    out["board"] = "waveshare-esp32-c6-lcd-1.47";
    out["width"] = canvas->width();
    out["height"] = canvas->height();
    out["rotation"] = rotation;
    out["brightness"] = brightness;
    out["uptime_ms"] = millis();
  } else if (strcmp(cmd, "status") == 0) {
    draw_status(doc["top"] | "working", doc["rows"].as<JsonArray>());
    if (!redraw_only) set_led(doc["led"]);
    last_screen = text;
  } else if (strcmp(cmd, "idle") == 0) {
    draw_idle();
    led_effect = EFFECT_OFF;
    last_screen = text;
  } else if (strcmp(cmd, "fill") == 0) {
    canvas->fillScreen(rgb565(parse_hex(doc["color"] | "000000")));
    flush_canvas();
    last_screen = text;
  } else if (strcmp(cmd, "screen") == 0) {
    // The host saves this before showing agent status and replays it when they finish.
    // A status screen is reported by name only: the host never replays one.
    JsonDocument shown;
    deserializeJson(shown, last_screen);
    if (strcmp(shown["cmd"] | "", "status") == 0) out["screen"]["cmd"] = "status";
    else out["screen"] = shown;
    const char *effects[] = {"off", "solid", "pulse"};
    out["led"]["effect"] = effects[led_effect];
    out["led"]["color"] = hex_color(led_color);
    out["led"]["low"] = hex_color(led_low);
  } else if (strcmp(cmd, "led") == 0) {
    set_led(doc.as<JsonVariantConst>());
  } else if (strcmp(cmd, "brightness") == 0) {
    if (doc["value"].is<int>()) {
      brightness = constrain(doc["value"].as<int>(), 1, 100);
      set_backlight(brightness);
      prefs.putInt("bright", brightness);
    }
    out["brightness"] = brightness;
  } else if (strcmp(cmd, "rotate") == 0) {
    if (doc["value"].is<int>()) {
      rotation = doc["value"].as<int>() & 3;
      prefs.putInt("rot", rotation);
      apply_rotation();
      String screen = last_screen;
      handle(screen.c_str(), true);
    }
    out["rotation"] = rotation;
  } else {
    if (!redraw_only) reply_error("unknown command");
    return;
  }
  if (redraw_only) return;
  serializeJson(out, Serial);
  Serial.println();
}

void read_serial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c != '\n') {
      if (line_length < sizeof(line) - 1) line[line_length++] = c;
      else line_overflow = true;
      continue;
    }
    line[line_length] = 0;
    if (line_overflow) reply_error("line too long");
    else if (line_length) handle(line);
    line_length = 0;
    line_overflow = false;
  }
}

void setup() {
  // The default 256-byte USB receive buffer drops the tail of a status line
  Serial.setRxBufferSize(sizeof(line));
  Serial.begin(115200);
  prefs.begin("busytag", false);
  brightness = prefs.getInt("bright", brightness);
  rotation = prefs.getInt("rot", DEFAULT_ROTATION);

  ledcAttach(PIN_BACKLIGHT, 20000, 10);
  set_backlight(0);
  SPI.begin(PIN_SCLK, -1, PIN_MOSI, PIN_CS);
  tft.init(172, 320);
  tft.setSPISpeed(40000000);
  apply_rotation();
  draw_idle();
  set_backlight(brightness);
  rgbLedWriteOrdered(PIN_RGB_LED, LED_ORDER, 0, 0, 0);
}

void loop() {
  read_serial();
  update_led();
  delay(10);
}
