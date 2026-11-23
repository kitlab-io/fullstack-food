// Helpers shared by every generated ESPHome node config. Copied next to the YAML by
// `fsf firmware build`; included through `esphome: includes:`.
//
// Not yet compiled or run on a board: treat as a first draft until a node has passed
// `fsf node test`.
#pragma once

#include "esphome.h"

#include <cmath>
#include <ctime>
#include <cstring>
#include <string>

// An on-command can never hold an actuator longer than this, whatever duration it asks for.
static const float FSF_MAX_LEASE_S = 3600.0f;

// ---------------------------------------------------------------------------- commands

// True for {"name": "on", "duration_s": > 0}. An on-command without a duration is refused.
inline bool fsf_is_on(JsonObjectConst x) {
  const char *name = x["name"] | "";
  return strcmp(name, "on") == 0 && (x["duration_s"] | 0.0f) > 0.0f;
}

inline bool fsf_is(JsonObjectConst x, const char *wanted) {
  const char *name = x["name"] | "";
  return strcmp(name, wanted) == 0;
}

inline int fsf_duration_ms(JsonObjectConst x) {
  float seconds = x["duration_s"] | 0.0f;
  if (seconds > FSF_MAX_LEASE_S) seconds = FSF_MAX_LEASE_S;
  if (seconds < 0.0f) seconds = 0.0f;
  return (int) (seconds * 1000.0f);
}

inline float fsf_level(JsonObjectConst x) {
  float level = x["level"] | 1.0f;
  if (level < 0.0f) level = 0.0f;
  if (level > 1.0f) level = 1.0f;
  return level;
}

// ---------------------------------------------------------------------------- state

// UTC time as ISO 8601, or "" until SNTP has set the clock.
inline std::string fsf_now() {
  time_t now = ::time(nullptr);
  if (now < 1600000000) return "";
  struct tm parts;
  gmtime_r(&now, &parts);
  char text[32];
  strftime(text, sizeof(text), "%Y-%m-%dT%H:%M:%S+00:00", &parts);
  return text;
}

inline float fsf_round2(float value) { return roundf(value * 100.0f) / 100.0f; }
inline float fsf_round3(float value) { return roundf(value * 1000.0f) / 1000.0f; }

// ---------------------------------------------------------------------------- status LEDs

struct FsfSegment {
  int first;
  int last;
  uint8_t r, g, b, w;
  uint8_t effect;   // 0 solid, 1 breathe, 2 blink, 3 blink_slow, 4 off
};

static const int FSF_MAX_SEGMENTS = 16;
static FsfSegment fsf_segments[FSF_MAX_SEGMENTS];
static int fsf_segment_count = 0;
static float fsf_brightness = 0.0f;

inline uint8_t fsf_effect(const char *name) {
  if (strcmp(name, "breathe") == 0) return 1;
  if (strcmp(name, "blink") == 0) return 2;
  if (strcmp(name, "blink_slow") == 0) return 3;
  if (strcmp(name, "off") == 0) return 4;
  return 0;
}

// Store a render command: {"brightness": 0.5, "segments": [{"leds": [0, 9], "color": [r, g, b, w], "effect": "blink"}]}
inline void fsf_render(JsonObjectConst x) {
  fsf_brightness = x["brightness"] | 0.0f;
  int count = 0;
  JsonArrayConst segments = x["segments"];
  for (JsonObjectConst item : segments) {
    if (count >= FSF_MAX_SEGMENTS) break;
    FsfSegment &seg = fsf_segments[count++];
    seg.first = item["leds"][0] | 0;
    seg.last = item["leds"][1] | 0;
    seg.r = item["color"][0] | 0;
    seg.g = item["color"][1] | 0;
    seg.b = item["color"][2] | 0;
    seg.w = item["color"][3] | 0;
    seg.effect = fsf_effect(item["effect"] | "solid");
  }
  fsf_segment_count = count;
}

// Called from the strip's addressable_lambda effect about 20 times a second.
inline void fsf_draw(esphome::light::AddressableLight &it) {
  const float t = esphome::millis() / 1000.0f;
  it.all() = esphome::Color::BLACK;
  for (int s = 0; s < fsf_segment_count; s++) {
    const FsfSegment &seg = fsf_segments[s];
    float k = 1.0f;
    switch (seg.effect) {
      case 1: k = 0.15f + 0.85f * (0.5f + 0.5f * sinf(t * 2.0f * 3.14159265f / 4.0f)); break;   // 4 s cycle
      case 2: k = fmodf(t, 1.0f) < 0.5f ? 1.0f : 0.0f; break;                                    // 1 s cycle
      case 3: k = fmodf(t, 3.0f) < 1.5f ? 1.0f : 0.0f; break;                                    // 3 s cycle
      case 4: k = 0.0f; break;
      default: break;
    }
    k *= fsf_brightness;
    for (int i = seg.first; i <= seg.last && i < it.size(); i++) {
      if (i < 0) continue;
      it[i] = esphome::Color((uint8_t) (seg.r * k), (uint8_t) (seg.g * k), (uint8_t) (seg.b * k), (uint8_t) (seg.w * k));
    }
  }
}
