# TV-IR — Rocky's American Grill TV Control

A custom web app for controlling 25 (eventually ~28) TVs across the bar from
a single tablet, replacing the pile of physical remotes. Despite the project
name, almost every TV at Rocky's is a smart TV controlled over IP — IR
support is retained as a fallback for any TV without network control.

```
┌─────────────────────────┐
│  Tablet (browser)       │
│  http://172.31.250.31/  │
└────────────┬────────────┘
             │ HTTP/JSON
             ▼
┌──────────────────────────────────────────┐
│  Server (Docker on Proxmox LXC)          │
│  • FastAPI + Pydantic                    │
│  • TV inventory in YAML                  │
│  • Per-TV pairing tokens in JSON         │
│  • Vite/React SPA served from /static    │
└────┬─────────┬─────────┬────────┬────────┘
     │         │         │        │
   Vizio      LG       Roku    ADB (Android/Fire/Google)
   :7345    :3001    :8060    :5555
```

---

## Table of contents

1. [How it works at the bar](#how-it-works-at-the-bar)
2. [TV inventory and protocols](#tv-inventory-and-protocols)
3. [Architecture](#architecture)
4. [Setup from scratch](#setup-from-scratch)
5. [Per-TV pairing](#per-tv-pairing)
6. [Daily operation (bartender)](#daily-operation-bartender)
7. [Maintenance](#maintenance)
8. [Adding a TV](#adding-a-tv)
9. [API reference](#api-reference)
10. [Files](#files)

---

## How it works at the bar

- 8 DirecTV receivers feed a **Thor RF modulator** that broadcasts each
  receiver as a different over-the-air channel on the coax that runs to
  every TV. The 8 boxes show up as channels **30.2 → 37.2**.
- Each TV is on its **TV / Antenna input**. Switching a TV from "Box 1" to
  "Box 3" means tuning that TV from `30.2` to `32.2` — i.e. sending the key
  sequence `3 2 . 2 ENTER`.
- The tablet UI has tiles for every TV, plus shift-level buttons (**Open** /
  **Close**) and a **"All TVs to ___"** channel bar so a bartender can
  switch every TV to the same game with one tap.
- The DirecTV channel each box is *tuned to* doesn't change automatically;
  it's a once-or-twice-a-day thing that someone does at the rack. Update
  `preset_labels` in `tvs.yaml` whenever a box gets re-tuned so the buttons
  on the tablet show the right channel name.

The Chicago / 60070 starting lineup baked into the example config is:

| Box | Default label  | Notes |
|-----|----------------|-------|
| 1   | ESPN           | DirecTV 206 |
| 2   | FS1            | DirecTV 219 |
| 3   | TNT            | DirecTV 245 |
| 4   | NBC Sports CHI | regional, varies by package |
| 5   | Marquee        | Cubs network |
| 6   | ESPN2          | DirecTV 209 |
| 7   | NFL Network    | DirecTV 212 |
| 8   | Big Ten        | DirecTV 220 |

Edit `preset_labels` in `server/config/tvs.yaml` to whatever each box is
actually tuned to.

---

## TV inventory and protocols

Every TV in the bar is a smart TV on the LAN, so each one is controlled
natively over its own protocol — no IR emitters required.

| Protocol            | Port  | Pairing                              | TVs at Rocky's |
|---------------------|-------|--------------------------------------|----------------|
| Vizio SmartCast     | 7345  | one-time 4-digit PIN on screen       | 4 (Vizio J03) |
| LG webOS / SSAP     | 3001  | one-time accept on the magic remote  | 4 (LG UQ/UP)  |
| Roku ECP            | 8060  | none                                 | 8 (TCL S455 + Sharp Roku) |
| Android TV / ADB    | 5555  | one-time accept on the TV            | 2 (Hisense H6570G) |
| Google TV / ADB     | 5555  | one-time accept on the TV            | 1 (Hisense U6H) |
| Fire TV / ADB       | 5555  | one-time accept on the TV            | 5 (Insignia F501/F301) |
| IR (ESP32, fallback)| —     | flash firmware, stick-on emitter     | 0 today        |
| TBD                 | —     | —                                    | 1 (TV09)       |

**Total: 24 controllable + 1 TBD + 0 IR = 25 TVs.**

---

## Architecture

### Server

`server/` is a FastAPI app in Python 3.12.

- **`app/main.py`** — boots the app, reads config, builds the dispatcher,
  serves the SPA from `/static`.
- **`app/registry.py`** — `Registry` (TV inventory loaded from YAML) and
  `Pairings` (per-TV auth, JSON-backed in the data volume).
- **`app/dispatcher.py`** — `Dispatcher.power()`, `.preset()`, `.key()`.
  Routes by `tv.type` to the right driver and translates logical keys
  (e.g. `Dot`, `Enter`) into protocol-specific keypresses.
- **`app/drivers/`** — one file per protocol. Each exposes
  `send_logical(key)` plus protocol-specific helpers.
  - `vizio.py` — HTTPS REST, PIN pairing, includes Dash/Subchannel mapping.
  - `lg_webos.py` — WebSocket via `aiowebostv`.
  - `roku.py` — HTTP ECP, no pairing.
  - `android_tv.py` — pure-Python ADB (`adb_shell`), supports both Android
    TV and Fire TV (same protocol).
  - `ir_node.py` — HTTP client for the ESP32 firmware, retained as fallback.
- **`app/codes/`** — Flipper-IRDB parser (only used by the IR path).
- **`app/api/`** — route modules:
  - `tvs.py`: list, power, preset, key.
  - `scenes.py`: `open`, `close`, `all-on`, `all-off`, `all-to-preset/{n}`.
  - `health.py`: `/api/health`.
- **`app/pair.py`** — interactive CLI that walks through pairing each TV.

### Web

`web/` is a Vite + React 18 + TypeScript SPA. No UI framework — plain CSS
keeps the deploy small and the touch targets predictable.

- **`App.tsx`** — header, shift bar, channel bar, grid of TV tiles, toast.
- **`components/ShiftBar.tsx`** — `Open` / `Close` buttons (Close confirms).
- **`components/ChannelBar.tsx`** — "All TVs to ___" buttons, one per box.
- **`components/TvTile.tsx`** — per-TV power + 8 channel buttons.
- **`styles.css`** — dark theme, sports-bar amber/red accents.

The Vite build output is copied into the Python image during the Docker
build, so production is a single container.

### Firmware (kept for IR fallback)

`firmware/` is a PlatformIO project for ESP32 / ESP32-S3 nodes that expose
a generic `POST /ir` endpoint. Currently unused since 0 TVs require IR,
but the code stays in case a future replacement TV has no IP control.

---

## Setup from scratch

Prerequisites on the Proxmox LXC:

- Docker + Docker Compose v2
- LXC has IP `172.31.250.31` reachable from the bar's WiFi
- Outbound DNS / WAN access for the initial image build (then it can run offline)

```bash
# 1. Clone
git clone <repo-url> tv-ir
cd tv-ir

# 2. Inventory
cp server/config/tvs.example.yaml server/config/tvs.yaml
# Edit tvs.yaml with the real TV list (already pre-filled for Rocky's 25 TVs).

# 3. Build & start
docker compose up -d --build

# 4. Pair every TV that needs pairing
docker compose exec server python -m app.pair --all
# Walks through Vizio PIN entry, LG accept, ADB accept per TV.
# Re-runnable any time; existing pairings are preserved.

# 5. Open the tablet UI
# In the tablet's browser: http://172.31.250.31/
# Add to home screen for full-screen kiosk mode.
```

Container exposes port 80 on the LXC, mapped to FastAPI on container port
8000 internally. Logs:

```bash
docker compose logs -f server
```

---

## Per-TV pairing

Run once per TV (or `--all` to walk through every one in order).

### Vizio SmartCast (TV01, 02, 05, 06)

1. `docker compose exec server python -m app.pair tv01`
2. The TV will display a 4-digit PIN.
3. Type the PIN at the prompt. The CLI stores the auth token in
   `pairings.json` (gitignored).
4. Repeat for tv02, tv05, tv06.

### LG webOS (TV10, 11, 12, 23)

Pre-req: in TV settings → **General → External Devices → Connect Mobile
Device** (path varies by webOS version), enable "**LG Connect Apps**".

1. `docker compose exec server python -m app.pair tv10`
2. The TV pops up an "Allow this device?" dialog. Accept with the magic
   remote.
3. The CLI saves the persistent client-key.
4. Repeat for the other LGs.

### Roku TVs (TV07, 08, 13–18)

No pairing required. Just confirm "Network Access" is enabled in the TV's
Settings → System → Advanced System Settings → **Control by mobile apps**
(set to "Permissive"). Run `--all` and they'll be skipped automatically.

### Android TV / Google TV (TV03, 04, 24)

Pre-req on each TV:

1. Settings → System → About → click **Build** seven times to enable
   Developer Options.
2. Settings → System → Developer Options → enable **USB debugging** AND
   **Network debugging** (sometimes labelled "ADB over network").

Then:

1. `docker compose exec server python -m app.pair tv03`
2. The TV shows "Allow USB debugging?" — pick **Always allow from this
   computer** and tap OK.
3. The CLI saves the ADB key fingerprint.

### Fire TV (TV19–22, 25)

Pre-req on each Fire TV:

1. Settings → My Fire TV → About → click **Build** seven times to enable
   Developer Options.
2. Settings → My Fire TV → Developer Options → **ADB Debugging: ON**.
3. Same screen → **Apps from Unknown Sources: ON** is *not* required.

Then:

1. `docker compose exec server python -m app.pair tv19`
2. The TV shows the same accept-fingerprint dialog. Accept.
3. The CLI saves the key.

> The same ADB key file is used for every Android-family TV — it lives at
> `/app/data/adb_key` inside the container. Backup the data volume to keep
> all pairings intact across rebuilds.

---

## Daily operation (bartender)

Open the tablet UI and use the kiosk app. The interface has three regions:

1. **Header** — `Rocky's American Grill / TV CONTROL`. To the right are the
   shift buttons:
   - **Open** (green): turns every TV on.
   - **Close** (red, confirms): turns every TV off.
2. **Channel bar** — `All TVs to [ESPN] [FS1] [TNT] [NBC Sports CHI]
   [Marquee] [ESPN2] [NFL Network] [Big Ten]`. Tap one and every TV
   tunes to that box.
3. **TV grid** — one tile per TV. Each tile has a slot number, the TV's
   name, a TV-OS badge (Vizio / LG / Roku / Android / Fire TV), a red
   power-toggle button, and 8 channel buttons. Tap any channel to switch
   only that TV.

A toast at the bottom confirms each action. If any TV fails (e.g. its
pairing expired) it's highlighted with a red `!` and the toast names it.

### Common patterns

- **Game day, all on the main game**: tap the channel bar, e.g. "ESPN".
- **Different game on the patio**: tap the patio TV's channel button.
- **Mute everything for an announcement**: not exposed today (audio at
  Rocky's is fed by TOSLINK from one TV → extractor → jukebox; TVs are
  muted by default).

---

## Maintenance

- **Restart server**: `docker compose restart server`
- **Update + restart**: `git pull && docker compose up -d --build`
- **Re-pair a TV** (e.g. after firmware update wiped the pairing):
  `docker compose exec server python -m app.pair tv10`
- **Logs**: `docker compose logs --tail 200 server`
- **Health**: `curl http://172.31.250.31/api/health` → `{"ok": true}`
- **Backup**: the `tv-ir-data` Docker volume holds `pairings.json` and the
  ADB key. Back it up if you don't want to re-pair after a wipe:
  ```bash
  docker run --rm -v tv-ir-data:/data -v "$PWD":/backup alpine \
    tar czf /backup/tv-ir-data.tgz -C /data .
  ```

---

## Adding a TV

1. Find a free slot number in `server/config/tvs.yaml` (or just append).
2. Add a stanza:
   ```yaml
   - { id: tv26, slot: 26, name: "TV26 …", type: vizio, url: "https://172.16.20.65:7345" }
   ```
3. `docker compose restart server` to pick up the inventory change.
4. If the type requires pairing, run `python -m app.pair tv26`.

If the new TV isn't a smart TV, add it as `type: ir` and:
1. Flash the firmware in `firmware/` onto an ESP32 (`pio run -t upload`).
2. Stick the IR emitter on the TV's IR window.
3. Set `url: "http://tvir-XXXXXX.local"` and `codes:
   "TVs/<Brand>/<File>.ir"` (path under your `flipper-irdb/` checkout).

---

## API reference

All endpoints live under `/api`. Bodies are JSON.

| Method | Path                              | Purpose                                  |
|--------|-----------------------------------|------------------------------------------|
| GET    | `/api/health`                     | liveness probe                           |
| GET    | `/api/tvs`                        | `{ presets:[…], tvs:[…] }`               |
| GET    | `/api/tvs/{id}`                   | single TV (with presets)                 |
| POST   | `/api/tvs/{id}/power`             | body `{state: on \| off \| toggle}`      |
| POST   | `/api/tvs/{id}/preset/{n}`        | switch one TV to box N (1..8)            |
| POST   | `/api/tvs/{id}/key`               | body `{key: "Vol_up"}` etc.              |
| POST   | `/api/scenes/open`                | every TV on                              |
| POST   | `/api/scenes/close`               | every TV off                             |
| POST   | `/api/scenes/all-on`              | alias for `open`                         |
| POST   | `/api/scenes/all-off`             | alias for `close`                        |
| POST   | `/api/scenes/all-to-preset/{n}`   | every TV to box N                        |

Scene endpoints return `{ok: bool, failed: { tv_id: error_message }}` so
the UI can surface partial failures.

Logical key names accepted by `/key`: `0`–`9`, `Dot` / `Dash`, `Enter`,
`Vol_up`, `Vol_dn`, `Mute`, `Ch_next`, `Ch_prev`, `Power`, `Up`, `Down`,
`Left`, `Right`, `Back`, `Home`, `Menu`. Each driver translates these to
its protocol's native codes.

---

## Files

```
TV-IR/
├── README.md                       this file
├── docker-compose.yml              one service, host 80 → container 8000
├── .gitignore
├── .dockerignore
│
├── server/                         FastAPI backend + SPA host
│   ├── Dockerfile                  multi-stage: node build → python runtime
│   ├── requirements.txt            fastapi, httpx, aiowebostv, adb-shell, …
│   ├── config/
│   │   ├── tvs.example.yaml        committed schema example
│   │   └── tvs.yaml                gitignored — your real inventory
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── registry.py             TV inventory + Pairings store
│       ├── dispatcher.py
│       ├── pair.py                 interactive pairing CLI
│       ├── api/{health,tvs,scenes}.py
│       ├── codes/{flipper,library}.py     Flipper-IRDB parser (IR fallback)
│       └── drivers/
│           ├── vizio.py
│           ├── lg_webos.py
│           ├── roku.py
│           ├── android_tv.py       handles Android TV, Google TV, Fire TV
│           └── ir_node.py          ESP32 fallback
│
├── web/                            Vite + React SPA
│   ├── package.json
│   ├── index.html
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       ├── types.ts
│       ├── styles.css
│       ├── main.tsx
│       └── components/
│           ├── ShiftBar.tsx
│           ├── ChannelBar.tsx
│           └── TvTile.tsx
│
├── firmware/                       ESP32 IR fallback (PlatformIO)
│   ├── platformio.ini
│   └── src/{main.cpp,secrets.h.example}
│
└── flipper-irdb/                   gitignored — clone of Flipper-IRDB
```

---

## Troubleshooting

| Symptom                                    | Likely cause                              | Fix |
|--------------------------------------------|-------------------------------------------|-----|
| Channel bar buttons say "Box 1" "Box 2"…   | `preset_labels` not set in `tvs.yaml`     | edit YAML, restart server |
| One TV's `!` icon appears red              | pairing expired / TV rebooted             | `python -m app.pair tvNN` |
| Vizio pair: "no auth token returned"       | wrong PIN, or PIN already expired         | retry; PIN is regenerated each `pair_start` |
| LG pair hangs forever                      | "LG Connect Apps" disabled in TV settings | enable, retry |
| Android/Fire TV: connect fails             | Developer Options / ADB debugging off     | enable on the TV, retry |
| Tablet shows blank page                    | static files missing in image             | `docker compose up -d --build` |
| Channel change works but TV is on HDMI     | TV switched away from antenna input       | press TV's Input button to "TV / Antenna" once |

---

## Why no IR for any TV currently

Every TV in the bar's inventory is a smart TV with native IP control, which
is faster, more reliable, and gives confirmed state ("the TV actually
acknowledged the command"). The original IR plan with one ESP32 per TV
($240 of hardware + a weekend of mounting) was scrapped in favour of the
LAN-only architecture once we read the inventory list. The IR firmware and
driver code remain in the repo so a future non-smart TV can be added in
~10 minutes.
