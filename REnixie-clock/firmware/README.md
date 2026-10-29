# Firmware

* `worldline_online/worldline_online.ino` - helper for Online mode: polls the worldline value every
  10 minutes, validates it (exactly 8 characters), and keeps the last good value on any failure.
  **Untested on hardware** - run it in Wokwi first.
* The multi-mode sketch (Clock / Random / Game / Online) goes here once it is cleaned up.

Remember to replace `YOUR_USER` in the URL.
