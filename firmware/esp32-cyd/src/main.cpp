// busytag firmware for the ESP32-2432S028 "Cheap Yellow Display" (CYD): a 320x240 ILI9341
// with an XPT2046 resistive touchscreen and an RGB LED, used in portrait (240x320).
//
// Same line protocol as firmware/esp32-c6-lcd (one JSON object per line each way, see
// src/busytag/esp32.py), plus touch:
//   - Tap an agent for its details; page through the list; Settings has brightness,
//     LED on/off, flip and sleep. All of this stays on the board.
//   - "Jump" in an agent's details queues an event. The host polls with {"cmd":"events"}
//     (`busytag watch`) and switches to that agent's terminal. The reply's "fresh" says
//     the board has reset since the host last drew on it.
//
// Status rows are [label, state, detail, "RRGGBB", id, age_seconds, can_jump]; the C6
// firmware reads only the first four.

#include <Arduino.h>
#include <SPI.h>
#include <Preferences.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <XPT2046_Touchscreen.h>
#include <ArduinoJson.h>
#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/FreeSansBold9pt7b.h>
#include <Fonts/FreeSansBold12pt7b.h>

#define FIRMWARE_VERSION "0.2.0"

// Board wiring (ESP32-2432S028). The display and touch are on separate SPI buses.
#define TFT_SCLK 14
#define TFT_MISO 12
#define TFT_MOSI 13
#define TFT_CS 15
#define TFT_DC 2
#define TFT_BACKLIGHT 21
#define TOUCH_CLK 25
#define TOUCH_MISO 39
#define TOUCH_MOSI 32
#define TOUCH_CS 33
#define TOUCH_IRQ 36
// RGB LED: three plain LEDs, active low
#define LED_RED 4
#define LED_GREEN 16
#define LED_BLUE 17

// Raw XPT2046 readings at the screen edges, in landscape (rotation 1) coordinates;
// see `touch` to recalibrate
#define TOUCH_X_MIN 200
#define TOUCH_X_MAX 3700
#define TOUCH_Y_MIN 240
#define TOUCH_Y_MAX 3800
#define TOUCH_MIN_PRESSURE 300

const int W = 240, H = 320;
// Landscape size, used to map raw touch readings
const int LW = 320, LH = 240;
// No PSRAM: a full-screen 16-bit canvas (150 KB) is bigger than the largest free heap
// block, so the screen is drawn in horizontal bands through one smaller canvas
const int BAND = 80;

SPIClass tft_spi(HSPI);
SPIClass touch_spi(VSPI);
Adafruit_ILI9341 tft(&tft_spi, TFT_DC, TFT_CS, -1);
XPT2046_Touchscreen touch(TOUCH_CS, TOUCH_IRQ);
GFXcanvas16 *canvas;
Preferences prefs;

int brightness = 80;
int rotation = 0;  // 0 or 2: portrait either way up
bool led_enabled = true;
bool asleep = false;
String last_screen = "{\"cmd\":\"idle\"}";
// True until the host draws something: after a reset the host's screen is gone
bool fresh = true;

// --- model -------------------------------------------------------------------

const int MAX_AGENTS = 12;
struct Agent {
  String label, state, detail, id;
  uint32_t color;
  uint32_t age;  // seconds, when the status arrived
  bool can_jump;
};
Agent agents[MAX_AGENTS];
int agent_count = 0;
String top_state = "working";
uint32_t status_at = 0;

enum Mode { MODE_IDLE, MODE_STATUS, MODE_FILL };
Mode mode = MODE_IDLE;
uint32_t fill_color = 0;

enum View { VIEW_MAIN, VIEW_DETAIL, VIEW_SETTINGS };
View view = VIEW_MAIN;
int page = 0;
String detail_id;
uint32_t jump_sent_at = 0;
uint32_t last_touch_at = 0;
uint32_t last_render_at = 0;
const uint32_t VIEW_TIMEOUT_MS = 60000;
const int ROWS_PER_PAGE = 5;

// Events for the host, oldest first
const int MAX_EVENTS = 4;
String events[MAX_EVENTS];
int event_count = 0;

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

void set_backlight(int percent) {
  ledcWrite(TFT_BACKLIGHT, map(constrain(percent, 0, 100), 0, 100, 0, 1023));
}

void queue_event(const String &event) {
  if (event_count == MAX_EVENTS) {
    for (int i = 1; i < MAX_EVENTS; i++) events[i - 1] = events[i];
    event_count--;
  }
  events[event_count++] = event;
}

String age_text(uint32_t seconds) {
  if (seconds < 60) return "now";
  if (seconds < 3600) return String(seconds / 60) + "m";
  if (seconds < 86400) return String(seconds / 3600) + "h";
  return String(seconds / 86400) + "d";
}

uint32_t agent_age(const Agent &agent) {
  return agent.age + (millis() - status_at) / 1000;
}

int find_agent(const String &id) {
  for (int i = 0; i < agent_count; i++) {
    if (agents[i].id == id) return i;
  }
  return -1;
}

// --- drawing (band-relative) ---------------------------------------------------

// Top of the band being drawn; every draw call subtracts it, and the canvas clips the rest
int oy = 0;

bool in_band(int y, int h) { return y + h > oy && y < oy + BAND; }

void fill_rect(int x, int y, int w, int h, uint32_t color) {
  if (in_band(y, h)) canvas->fillRect(x, y - oy, w, h, rgb565(color));
}

void round_rect(int x, int y, int w, int h, int r, uint32_t color) {
  if (in_band(y, h)) canvas->fillRoundRect(x, y - oy, w, h, r, rgb565(color));
}

void circle(int x, int y, int r, uint32_t color) {
  if (in_band(y - r, 2 * r + 1)) canvas->fillCircle(x, y - oy, r, rgb565(color));
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

void text(int x, int baseline, const String &value, uint32_t color) {
  // Glyphs reach about 20 px above and 6 px below the baseline
  if (!in_band(baseline - 20, 26)) return;
  canvas->setTextColor(rgb565(color));
  canvas->setCursor(x, baseline - oy);
  canvas->print(value);
}

void text_centered(int x, int w, int baseline, const String &value, uint32_t color) {
  text(x + (w - (int)text_width(value)) / 2, baseline, value, color);
}

int draw_wrapped(const String &value, int x, int y, int max_width, int line_height, int max_lines, uint32_t color) {
  String current;
  int lines = 0;
  int start = 0;
  while (start <= (int)value.length() && lines < max_lines) {
    int space = value.indexOf(' ', start);
    String word = value.substring(start, space < 0 ? value.length() : space);
    start = space < 0 ? value.length() + 1 : space + 1;
    String candidate = current.length() ? current + " " + word : word;
    if (text_width(candidate) <= max_width || !current.length()) {
      current = candidate;
      continue;
    }
    bool last = lines == max_lines - 1;
    text(x, y + lines * line_height, fit(last ? current + " " + word + " ..." : current, max_width), color);
    lines++;
    current = word;
  }
  if (current.length() && lines < max_lines) {
    text(x, y + lines * line_height, fit(current, max_width), color);
    lines++;
  }
  return lines;
}

// --- buttons -----------------------------------------------------------------

enum Action {
  ACT_NONE, ACT_PREV, ACT_NEXT, ACT_SETTINGS, ACT_OPEN, ACT_BACK, ACT_JUMP,
  ACT_DIMMER, ACT_BRIGHTER, ACT_LED, ACT_FLIP, ACT_SLEEP,
};
struct Button {
  int x, y, w, h;
  Action action;
  int arg;
};
const int MAX_BUTTONS = 16;
Button buttons[MAX_BUTTONS];
int button_count = 0;

// Buttons are recorded once per render, while drawing the first band
void add_button(int x, int y, int w, int h, Action action, int arg = 0) {
  if (oy != 0 || button_count == MAX_BUTTONS) return;
  buttons[button_count++] = {x, y, w, h, action, arg};
}

void draw_button(int x, int y, int w, int h, const String &label, Action action, uint32_t background = 0x1F2937, uint32_t color = 0xE5E7EB) {
  round_rect(x, y, w, h, 6, background);
  canvas->setFont(&FreeSansBold9pt7b);
  text_centered(x, w, y + h / 2 + 6, label, color);
  add_button(x, y, w, h, action);
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

const Look &look_for(const String &state) {
  for (const Look &look : LOOKS) {
    if (state == look.state) return look;
  }
  return LOOKS[3];
}

const uint32_t BACKGROUND = 0x0B0F19;
const uint32_t MUTED = 0x9CA3AF;
const int HEADER = 40;
const int BAR_Y = H - 36;
const int ROW_H = 48;

void draw_header(const String &title, uint32_t background, const String &right = "") {
  fill_rect(0, 0, W, HEADER, background);
  int right_width = 0;
  if (right.length()) {
    canvas->setFont(&FreeSans9pt7b);
    right_width = text_width(right);
    text(W - 10 - right_width, 26, right, 0xFFFFFF);
  }
  canvas->setFont(&FreeSansBold12pt7b);
  text(10, 28, fit(title, W - 30 - right_width), 0xFFFFFF);
}

void draw_idle() {
  canvas->setFont(&FreeSansBold12pt7b);
  text_centered(0, W, 144, "busytag", 0x6B7280);
  canvas->setFont(&FreeSans9pt7b);
  text_centered(0, W, 170, "no active agents", 0x4B5563);
  draw_button(W - 100, BAR_Y + 4, 96, 32, "Settings", ACT_SETTINGS);
}

int page_count() {
  return max(1, (agent_count + ROWS_PER_PAGE - 1) / ROWS_PER_PAGE);
}

void draw_list() {
  const Look &look = look_for(top_state);
  draw_header(look.headline, look.background, agent_count > 1 ? String(agent_count) + " agents" : "");
  int first = page * ROWS_PER_PAGE;
  for (int i = first; i < agent_count && i < first + ROWS_PER_PAGE; i++) {
    const Agent &agent = agents[i];
    int y = HEADER + (i - first) * ROW_H;
    circle(12, y + 16, 5, agent.color);
    canvas->setFont(&FreeSans9pt7b);
    String age = age_text(agent_age(agent));
    int age_width = text_width(age);
    text(W - 10 - age_width, y + 21, age, MUTED);
    canvas->setFont(&FreeSansBold9pt7b);
    text(24, y + 21, fit(agent.label, W - 44 - age_width), look_for(agent.state).text);
    canvas->setFont(&FreeSans9pt7b);
    String detail = agent.detail.length() ? agent.detail : agent.state;
    text(24, y + 40, fit(detail, W - 34), 0xD1D5DB);
    fill_rect(8, y + ROW_H - 1, W - 16, 1, 0x1F2937);
    add_button(0, y, W, ROW_H, ACT_OPEN, i);
  }
  if (page_count() > 1) {
    draw_button(4, BAR_Y + 4, 44, 32, "<", ACT_PREV);
    draw_button(92, BAR_Y + 4, 44, 32, ">", ACT_NEXT);
    canvas->setFont(&FreeSans9pt7b);
    text_centered(48, 44, BAR_Y + 26, String(page + 1) + "/" + String(page_count()), MUTED);
  }
  draw_button(W - 100, BAR_Y + 4, 96, 32, "Settings", ACT_SETTINGS);
}

void draw_detail() {
  int index = find_agent(detail_id);
  const Agent &agent = agents[index];
  const Look &look = look_for(agent.state);
  draw_header(look.headline, look.background);
  canvas->setFont(&FreeSansBold12pt7b);
  text(10, HEADER + 30, fit(agent.label, W - 20), 0xFFFFFF);
  circle(15, HEADER + 48, 5, agent.color);
  canvas->setFont(&FreeSans9pt7b);
  text(28, HEADER + 54, agent.state + ", " + age_text(agent_age(agent)) + (agent_age(agent) < 60 ? "" : " ago"), MUTED);
  String detail = agent.detail.length() ? agent.detail : "No details";
  draw_wrapped(detail, 10, HEADER + 80, W - 20, 20, 8, 0xD1D5DB);

  draw_button(4, BAR_Y + 4, 80, 32, "Back", ACT_BACK);
  if (agent.can_jump) {
    bool sent = jump_sent_at && millis() - jump_sent_at < 3000;
    draw_button(W - 150, BAR_Y + 4, 146, 32, sent ? "Sent" : "Jump to it", ACT_JUMP, sent ? 0x15803D : 0x2563EB, 0xFFFFFF);
  } else {
    canvas->setFont(&FreeSans9pt7b);
    text(W - 10 - text_width("no terminal"), BAR_Y + 26, "no terminal", 0x4B5563);
  }
}

void draw_settings() {
  draw_header("Settings", 0x374151, "fw " FIRMWARE_VERSION);
  canvas->setFont(&FreeSans9pt7b);
  text(12, 84, "Brightness", 0xE5E7EB);
  draw_button(110, 60, 40, 40, "-", ACT_DIMMER);
  canvas->setFont(&FreeSansBold9pt7b);
  text_centered(150, 46, 86, String(brightness) + "%", 0xFFFFFF);
  draw_button(196, 60, 40, 40, "+", ACT_BRIGHTER);

  canvas->setFont(&FreeSans9pt7b);
  text(12, 144, "Status LED", 0xE5E7EB);
  draw_button(130, 120, 106, 40, led_enabled ? "On" : "Off", ACT_LED, led_enabled ? 0x15803D : 0x1F2937);

  canvas->setFont(&FreeSans9pt7b);
  text(12, 204, "Screen", 0xE5E7EB);
  draw_button(130, 180, 106, 40, "Flip", ACT_FLIP);

  draw_button(4, BAR_Y + 4, 96, 32, "Back", ACT_BACK);
  draw_button(W - 100, BAR_Y + 4, 96, 32, "Sleep", ACT_SLEEP);
}

void draw_view() {
  if (view == VIEW_SETTINGS) return draw_settings();
  if (view == VIEW_DETAIL && mode == MODE_STATUS && find_agent(detail_id) >= 0) return draw_detail();
  if (mode == MODE_FILL) {
    fill_rect(0, 0, W, H, fill_color);
    // The whole screen opens Settings
    add_button(0, 0, W, H, ACT_SETTINGS);
    return;
  }
  if (mode == MODE_STATUS && agent_count) return draw_list();
  draw_idle();
}

void render() {
  if (view == VIEW_DETAIL && (mode != MODE_STATUS || find_agent(detail_id) < 0)) view = VIEW_MAIN;
  page = constrain(page, 0, page_count() - 1);
  button_count = 0;
  for (oy = 0; oy < H; oy += BAND) {
    canvas->fillScreen(rgb565(BACKGROUND));
    draw_view();
    tft.drawRGBBitmap(0, oy, canvas->getBuffer(), W, BAND);
  }
  oy = 0;
  last_render_at = millis();
}

// --- touch -------------------------------------------------------------------

bool touch_down = false;
int last_raw_x = -1, last_raw_y = -1, last_x = -1, last_y = -1;

void screen_point(int raw_x, int raw_y, int &x, int &y) {
  // The point in landscape (rotation 1) coordinates, then turned to portrait
  int lx = constrain(map(raw_x, TOUCH_X_MIN, TOUCH_X_MAX, 0, LW - 1), 0, LW - 1);
  int ly = constrain(map(raw_y, TOUCH_Y_MIN, TOUCH_Y_MAX, 0, LH - 1), 0, LH - 1);
  if (rotation == 2) {
    x = ly;
    y = H - 1 - lx;
  } else {
    x = W - 1 - ly;
    y = lx;
  }
}

void wake() {
  asleep = false;
  set_backlight(brightness);
}

void act(const Button &button) {
  switch (button.action) {
    case ACT_PREV: page--; break;
    case ACT_NEXT: page++; break;
    case ACT_SETTINGS: view = VIEW_SETTINGS; break;
    case ACT_BACK: view = VIEW_MAIN; break;
    case ACT_OPEN:
      detail_id = agents[button.arg].id;
      jump_sent_at = 0;
      view = VIEW_DETAIL;
      break;
    case ACT_JUMP: {
      JsonDocument event;
      event["type"] = "jump";
      event["agent"] = detail_id;
      String text;
      serializeJson(event, text);
      queue_event(text);
      jump_sent_at = millis();
      break;
    }
    case ACT_DIMMER:
    case ACT_BRIGHTER:
      brightness = constrain(brightness + (button.action == ACT_BRIGHTER ? 10 : -10), 10, 100);
      set_backlight(brightness);
      prefs.putInt("bright", brightness);
      break;
    case ACT_LED:
      led_enabled = !led_enabled;
      prefs.putBool("led", led_enabled);
      led_written = 0xFFFFFFFF;
      break;
    case ACT_FLIP:
      rotation = rotation == 0 ? 2 : 0;
      prefs.putInt("rot", rotation);
      tft.setRotation(rotation);
      break;
    case ACT_SLEEP:
      asleep = true;
      set_backlight(0);
      view = VIEW_MAIN;
      break;
    default: return;
  }
  render();
}

void read_touch() {
  bool down = touch.touched();
  if (!down) {
    touch_down = false;
    return;
  }
  TS_Point point = touch.getPoint();
  if (point.z < TOUCH_MIN_PRESSURE || touch_down) return;
  // One action per press: wait for release before the next
  touch_down = true;
  last_touch_at = millis();
  last_raw_x = point.x;
  last_raw_y = point.y;
  screen_point(point.x, point.y, last_x, last_y);
  if (asleep) {
    wake();
    return;
  }
  // Later buttons are drawn on top (the bottom bar over a full-screen button)
  for (int i = button_count - 1; i >= 0; i--) {
    const Button &b = buttons[i];
    if (last_x >= b.x && last_x < b.x + b.w && last_y >= b.y && last_y < b.y + b.h) {
      act(b);
      return;
    }
  }
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

void write_led(uint32_t color) {
  // Active low: full duty is off
  ledcWrite(LED_RED, 255 - ((color >> 16) & 0xFF));
  ledcWrite(LED_GREEN, 255 - ((color >> 8) & 0xFF));
  ledcWrite(LED_BLUE, 255 - (color & 0xFF));
}

void update_led() {
  uint32_t color = 0;
  if (led_effect == EFFECT_SOLID) color = led_color;
  if (led_effect == EFFECT_PULSE) {
    // Triangle wave between the low and full color
    float phase = (millis() % PULSE_PERIOD_MS) / (float)PULSE_PERIOD_MS;
    color = mix(led_low, led_color, phase < 0.5f ? phase * 2 : 2 - phase * 2);
  }
  if (!led_enabled) color = 0;
  if (color == led_written) return;
  led_written = color;
  write_led(color);
}

// --- protocol ----------------------------------------------------------------

void reply_error(const char *message) {
  JsonDocument out;
  out["ok"] = false;
  out["error"] = message;
  serializeJson(out, Serial);
  Serial.println();
}

void load_status(const char *top, JsonArray rows) {
  bool was_attention = mode == MODE_STATUS && top_state == "attention";
  top_state = top;
  agent_count = 0;
  for (JsonArray row : rows) {
    if (agent_count == MAX_AGENTS) break;
    Agent &agent = agents[agent_count++];
    agent.label = row[0] | "";
    agent.state = row[1] | "";
    agent.detail = row[2] | "";
    agent.color = parse_hex(row[3] | "FFFFFF", 0xFFFFFF);
    // Older hosts send four fields: the label stands in for the ID
    agent.id = row[4] | agent.label.c_str();
    agent.age = row[5] | 0;
    agent.can_jump = row[6] | false;
  }
  status_at = millis();
  mode = MODE_STATUS;
  // A new request for attention wakes a sleeping screen
  if (asleep && top_state == "attention" && !was_attention) wake();
}

void handle(const char *input) {
  JsonDocument doc;
  if (deserializeJson(doc, input)) {
    reply_error("invalid JSON");
    return;
  }
  const char *cmd = doc["cmd"] | "";
  JsonDocument out;
  out["ok"] = true;

  if (strcmp(cmd, "hello") == 0) {
    out["device"] = "busytag-esp32";
    out["fw"] = FIRMWARE_VERSION;
    out["board"] = "esp32-2432s028";
    out["width"] = W;
    out["height"] = H;
    out["rotation"] = rotation;
    out["brightness"] = brightness;
    out["uptime_ms"] = millis();
    // Tells the host to poll `events`
    out["touch"] = true;
  } else if (strcmp(cmd, "status") == 0) {
    load_status(doc["top"] | "working", doc["rows"].as<JsonArray>());
    set_led(doc["led"]);
    last_screen = "{\"cmd\":\"status\"}";
    fresh = false;
    render();
  } else if (strcmp(cmd, "idle") == 0) {
    mode = MODE_IDLE;
    agent_count = 0;
    led_effect = EFFECT_OFF;
    last_screen = input;
    fresh = false;
    render();
  } else if (strcmp(cmd, "fill") == 0) {
    mode = MODE_FILL;
    fill_color = parse_hex(doc["color"] | "000000");
    last_screen = input;
    fresh = false;
    render();
  } else if (strcmp(cmd, "screen") == 0) {
    // The host saves this before showing agent status and replays it when they finish
    JsonDocument shown;
    deserializeJson(shown, last_screen);
    out["screen"] = shown;
    const char *effects[] = {"off", "solid", "pulse"};
    out["led"]["effect"] = effects[led_effect];
    out["led"]["color"] = hex_color(led_color);
    out["led"]["low"] = hex_color(led_low);
  } else if (strcmp(cmd, "led") == 0) {
    set_led(doc.as<JsonVariantConst>());
  } else if (strcmp(cmd, "brightness") == 0) {
    if (doc["value"].is<int>()) {
      brightness = constrain(doc["value"].as<int>(), 1, 100);
      if (!asleep) set_backlight(brightness);
      prefs.putInt("bright", brightness);
      if (view == VIEW_SETTINGS) render();
    }
    out["brightness"] = brightness;
  } else if (strcmp(cmd, "rotate") == 0) {
    if (doc["value"].is<int>()) {
      // Portrait only: 0 and 1 are one way up, 2 and 3 the other
      rotation = (doc["value"].as<int>() & 2) ? 2 : 0;
      prefs.putInt("rot", rotation);
      tft.setRotation(rotation);
      render();
    }
    out["rotation"] = rotation;
  } else if (strcmp(cmd, "events") == 0) {
    JsonArray list = out["events"].to<JsonArray>();
    for (int i = 0; i < event_count; i++) {
      JsonDocument event;
      deserializeJson(event, events[i]);
      list.add(event);
    }
    event_count = 0;
    // The host redraws a board that has reset since it last drew
    out["fresh"] = fresh;
  } else if (strcmp(cmd, "touch") == 0) {
    // For calibration: the last press, raw and mapped to the screen
    out["raw_x"] = last_raw_x;
    out["raw_y"] = last_raw_y;
    out["x"] = last_x;
    out["y"] = last_y;
    out["ms_ago"] = last_touch_at ? millis() - last_touch_at : -1;
  } else {
    reply_error("unknown command");
    return;
  }
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
  // The default 256-byte receive buffer would drop the tail of a status line
  Serial.setRxBufferSize(sizeof(line));
  Serial.begin(115200);
  prefs.begin("busytag", false);
  brightness = prefs.getInt("bright", brightness);
  // Saved landscape values (1, 3) from firmware 0.1 map to portrait the same way up
  rotation = (prefs.getInt("rot", rotation) & 2) ? 2 : 0;
  led_enabled = prefs.getBool("led", true);

  ledcAttach(TFT_BACKLIGHT, 20000, 10);
  set_backlight(0);
  for (int pin : {LED_RED, LED_GREEN, LED_BLUE}) {
    ledcAttach(pin, 5000, 8);
  }
  write_led(0);

  tft_spi.begin(TFT_SCLK, TFT_MISO, TFT_MOSI, TFT_CS);
  tft.begin(40000000);
  tft.setRotation(rotation);
  canvas = new GFXcanvas16(W, BAND);
  touch_spi.begin(TOUCH_CLK, TOUCH_MISO, TOUCH_MOSI, TOUCH_CS);
  touch.begin(touch_spi);
  touch.setRotation(1);

  render();
  set_backlight(brightness);
}

void loop() {
  read_serial();
  read_touch();
  update_led();
  uint32_t now = millis();
  // Back to the main screen after a minute without touches
  if (view != VIEW_MAIN && now - last_touch_at > VIEW_TIMEOUT_MS) {
    view = VIEW_MAIN;
    render();
  }
  // Keep the ages fresh, and clear "Sent" on the jump button
  else if (!asleep && mode == MODE_STATUS && now - last_render_at > 30000) render();
  else if (view == VIEW_DETAIL && jump_sent_at && now - jump_sent_at > 3000 && now - last_render_at > 3000) {
    jump_sent_at = 0;
    render();
  }
  delay(10);
}
