// worldline_online.ino - drop-in "Online mode" helper for an ESP32 (Arduino core 2.x / 3.x)
// UNTESTED on hardware: I could not compile or flash it here. Test it in Wokwi / on the bench first.
//
// What it does: every 10 minutes it downloads data/divergence.txt (exactly 8 characters, like
// "1.048596") from your GitHub repo and hands it to your own display routine.
// Paste fetchWorldline() + onlineModeTick() into your sketch and implement showWorldline().

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>

// TODO: replace YOUR_USER (and the repo name if you chose a different one)
const char* WORLDLINE_URL =
    "https://raw.githubusercontent.com/YOUR_USER/REnixie-clock/worldline-data/divergence.txt";
const unsigned long POLL_MS = 10UL * 60UL * 1000UL;   // GitHub's raw cache is ~5 min, so 10 is plenty

String lastWorldline = "1.048596";    // shown until the first successful download
unsigned long lastPoll = 0;

// Your existing routine that drives the 8 tubes (digit characters + the decimal point on tube 2).
void showWorldline(const String& v);

bool validWorldline(const String& s) {
  if (s.length() != 8 || s[1] != '.') return false;
  for (int i = 0; i < 8; i++) {
    if (i != 1 && !isDigit(s[i])) return false;
  }
  return true;
}

// Returns true and fills `out` only when a fresh, valid value arrived. Never blanks the display.
bool fetchWorldline(String& out) {
  if (WiFi.status() != WL_CONNECTED) return false;
  WiFiClientSecure client;
  client.setInsecure();                 // hobby project: skips certificate pinning
  HTTPClient http;
  http.setTimeout(8000);
  http.setFollowRedirects(HTTPC_FORCE_FOLLOW_REDIRECTS);
  if (!http.begin(client, WORLDLINE_URL)) return false;
  bool ok = false;
  if (http.GET() == HTTP_CODE_OK) {
    String body = http.getString();
    body.trim();
    if (validWorldline(body)) {
      out = body;
      ok = true;
    }
  }
  http.end();
  return ok;
}

// Call this from loop() while the meter is in Online mode.
void onlineModeTick() {
  if (lastPoll != 0 && millis() - lastPoll < POLL_MS) return;
  lastPoll = millis();
  String v;
  if (fetchWorldline(v) && v != lastWorldline) {
    lastWorldline = v;
    showWorldline(v);                   // trigger your tube "slot machine" animation here
  }
}
