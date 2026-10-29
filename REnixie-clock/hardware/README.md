# Hardware

Status: **planned** - nothing is built yet. Decisions so far:

* LED tubes designed from scratch (own board, own digit artwork, own tube build), modelled on the look of
  IN-18 Nixie tubes with edge-lit acrylic layers.
* Decimal point on a separate side LED; only one tube needs it.
* Controller: ESP32 (WiFi + Bluetooth), prototyped in Wokwi first.
* Acrylic: 1.5 mm, laser-cut at the TMU DME lab.
* Addressable LED strips (WS2812B-class) for the lighting.

Planned contents: `tube-pcb/`, `controller-pcb/`, `laser-cut/`, `enclosure/`, `bom.md`.

> Before committing anyone else's design files here, check their licence. Only add files you made or that are
> clearly open-licensed, and credit them.
