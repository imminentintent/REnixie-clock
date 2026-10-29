# REnixie;clock

![worldline](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2FYOUR_USER%2FREnixie-clock%2Fworldline-data%2Fbadge.json)

An 8-tube LED "Nixie-style" clock that reads the world. Part electronics build, part software.
*If you know, you know.*

> Status: **in progress.** Software side works in simulation; hardware is at the design stage.

## Parts

| Folder | What it is | Status |
|---|---|---|
| [`worldline/`](worldline/) | News-driven worldline estimator. Reads RSS feeds, publishes an 8-character value every 30 min | built, tested offline, awaiting first live run |
| [`firmware/`](firmware/) | ESP32 code: Clock, Random, Game and Online modes | Online-mode helper drafted; multi-mode sketch runs in Wokwi |
| [`hardware/`](hardware/) | Tube PCBs, controller board, acrylic parts, enclosure | planned |
| [`docs/`](docs/) | Build log, notes, method write-ups | started |

## How it fits together

```
 RSS news feeds ──> worldline/ (GitHub Action, every 30 min) ──> branch `worldline-data`
                                                                       │ divergence.txt  ("1.048596")
                                                                       ▼
                               ESP32 firmware (Online mode, polls every 10 min) ──> 8 LED tubes
```

The estimator's output lives on its own branch, `worldline-data`, so the 48 automatic commits a day
never clutter this branch's history.

## Modes

* **Clock** - shows the time
* **Random** - hops between random worldlines
* **Online** - shows the live news-driven value from `worldline/`
* **Game** - follows a game's events (separate workstream)

## Get the live value

`https://raw.githubusercontent.com/YOUR_USER/REnixie-clock/worldline-data/divergence.txt`

Full details of the latest reading (field, z-score, top stories) are in `divergence.json` on the same branch.

## Setup

See [`docs/setup.md`](docs/setup.md).
