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
7. [Updating the channel lineup](#updating-the-channel-lineup)
8. [Zones, events, and the schedule](#zones-events-and-the-schedule)
9. [DirecTV receiver control](#directv-receiver-control)
10. [Wake-on-LAN](#wake-on-lan)
11. [Status monitoring](#status-monitoring)
12. [PIN auth](#pin-auth)
13. [PWA / kiosk install](#pwa--kiosk-install)
14. [Backups](#backups)
15. [Maintenance](#maintenance)
16. [Adding a TV](#adding-a-tv)
17. [API reference](#api-reference)
18. [Files](#files)

---

## How it works at the bar

- A **Thor RF modulator** broadcasts 8 RF channels on the coax that runs
  to every TV — channels **30.2 → 37.2**. Inputs:
  - **30.2 – 34.2**: 5 × DirecTV H24 receivers (controllable from the tablet)
  - **35.2**: Loop TV player (continuous video; not controllable)
  - **36.2 – 37.2**: HDMI feeds from the DJ booth (DJ visuals)
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

| Box | Default label  | DirecTV ch | RF channel | Source                |
|-----|----------------|------------|------------|-----------------------|
| 1   | ESPN           | 206        | 30.2       | DirecTV H24           |
| 2   | FS1            | 219        | 31.2       | DirecTV H24           |
| 3   | TNT            | 245        | 32.2       | DirecTV H24           |
| 4   | NBC Sports CHI | 640        | 33.2       | DirecTV H24           |
| 5   | Marquee        | 648        | 34.2       | DirecTV H24           |
| 6   | Loop TV        | —          | 35.2       | Loop player (HDMI)    |
| 7   | DJ A           | —          | 36.2       | DJ booth HDMI run 1   |
| 8   | DJ B           | —          | 37.2       | DJ booth HDMI run 2   |

Edit `preset_labels` AND `preset_channels` in `server/config/tvs.yaml`
when a DirecTV box gets re-tuned. The full Chicago / 60070 channel
reference (sports, locals, news, entertainment) is at
[`server/config/directv_lineup.yaml`](server/config/directv_lineup.yaml)
— flip through it to find what to put on each box.

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
- **`preview.html`** — fully static rendering of the production UI with
  the 25 real TVs and the Chicago lineup baked in. Open it in any
  browser to review design changes without spinning up the server:
  ```bash
  python3 -m http.server 8765 --directory web
  # then visit http://localhost:8765/preview.html
  ```

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

## Zones, events, and the schedule

The 25 TVs are grouped into **zones** (Bar Front, Dining, Patio, Side
Room) — set in `tvs.yaml` per TV. The tablet UI shows zone tabs above
the grid; tapping a zone scopes the channel-bar buttons to just those
TVs (`All TVs to ESPN` becomes `Patio to ESPN`).

**Saved events** are multi-TV scenes you tap once to apply, defined under
`events:` in `tvs.yaml`:

```yaml
events:
  - id: "nfl_sunday"
    name: "NFL Sunday"
    description: "Patio to FS1, everything else ESPN"
    actions:
      - { target: "Patio",  preset: 2 }
      - { target: "all",    preset: 1 }
```

`target` accepts:
- `"all"` — every non-TBD TV
- a zone name (e.g. `"Patio"`)
- a single TV id (`"tv01"`)
- a list of TV ids

Each action can set `power: on|off`, `preset: 1..8`, or both.

**Auto-schedule** is a cron-style block that fires events automatically.
Rocky's bar hours are 3:00 PM → 4:30 AM the next morning, so the default
schedule looks like:

```yaml
schedule:
  - { when: "0 15 * * *",  action: open }    # 3:00 PM every day → all on
  - { when: "30 4 * * *",  action: close }   # 4:30 AM every day → all off
  # - { when: "0 12 * * 0", action: event, event_id: "nfl_sunday" }
```

Format is the standard 5-field cron (`minute hour dom month dow`); both
cron-style (Sun=0) and Python-style (Mon=0) day-of-week values are
accepted. Timezone follows the container's `TZ` env var (defaults to
`America/Chicago`). The scheduler runs in-process at minute granularity
— no external cron needed.

Actions:
- `open` — every TV on
- `close` — every TV off
- `all_to_preset` (with `preset: N`) — every TV to box N
- `event` (with `event_id: "..."`) — apply a saved event

---

## DirecTV receiver control

The 8 DirecTV receivers themselves can be controlled from the tablet via
the **Boxes** button in the header. Each receiver exposes an HTTP API on
port 8080 once **External Access** is enabled (Settings → Whole-Home →
External Device → **Allow**).

Configure receiver hosts under `receivers:` in `tvs.yaml`:

```yaml
receivers:
  - { num: 1, name: "DirecTV Box 1", host: "172.16.20.71", rf: "30.2" }
```

The Boxes panel lets the bartender:
- Type a DirecTV channel number (e.g. `206` or `206.1`) and tap **Tune**
  to retune that receiver in place — no walking to the rack.
- (Future: send remote keys, see what's tuned.)

The HTTP API exposes:

| Method | Path                              | Purpose                             |
|--------|-----------------------------------|-------------------------------------|
| GET    | `/api/boxes`                      | list configured receivers           |
| GET    | `/api/boxes/{n}/tuned`            | what box N is currently tuned to    |
| POST   | `/api/boxes/{n}/tune?channel=NNN` | tune box N to channel NNN[.MM]      |
| POST   | `/api/boxes/{n}/key/{key}`        | press a remote key (`POWER`, `GUIDE`, `MENU`, `UP`, `DOWN`, `ENTER`, `EXIT`, …) |

---

## Wake-on-LAN

LG webOS TVs (and many Samsungs) drop their WiFi in standby, so a normal
HTTPS / WebSocket call can't reach them. The server falls back to **WoL
magic packets** for the `power on` action when a TV has a `mac:` field
in `tvs.yaml`. Every TV in the bar is pre-populated with its MAC
(captured during the inventory walk).

This is what makes the **Open** shift button work: it sends `power:on`
to every TV, which for the LGs means a UDP broadcast, and they wake.

WoL prerequisites on the TV:
- LG webOS: General → Mobile TV On → **Turn on via Wi-Fi: ON**
- Samsung: General → Network → Expert Settings → **Power on with Mobile: ON**
- Most others (Vizio, Roku, Android, Fire TV) keep the network up in
  standby and don't need WoL — the dispatcher only uses it where the
  protocol says it's required.

---

## Status monitoring

The server runs a background **status monitor** that probes every TV
every ~15 seconds via its native protocol (HTTP for Roku/Vizio, TCP
connect for LG/ADB/IR). The result is exposed at:

- `GET /api/tvs/status` — JSON map keyed by TV id
- Embedded as `tv.status` on `/api/tvs` and `/api/tvs/{id}`

In the UI, every tile gets a coloured **status dot** in the header:
- green = reachable
- red = unreachable (either offline or pairing/auth issue)
- grey = no probe yet (warm-up)

The tablet repolls status every 10s.

---

## PIN auth

Set `TVIR_PIN=1234` (or any digit string) in `docker-compose.yml` to
require a PIN to use the tablet UI. Read endpoints (`GET /api/tvs`,
`/api/tvs/status`) remain open so the tablet can hydrate before login;
all mutating endpoints (POST) require an authenticated session.

```yaml
environment:
  - TVIR_PIN=1234
```

After `docker compose up -d --build`, the tablet shows a PIN gate on
first load. The session cookie lasts 12 hours. Leave `TVIR_PIN` unset
(or empty) to disable auth entirely.

This is a friction control to keep customers from hitting **Close**, not
a security boundary — anyone on the bar's WiFi can sniff the cookie.

---

## PWA / kiosk install

The web app ships with a `manifest.webmanifest` and a tiny service worker.
On the tablet:

- **iPad / iOS Safari**: open `http://172.31.250.31/`, tap the share
  sheet, **Add to Home Screen** → launches full-screen, no browser
  chrome.
- **Android / Chrome**: visit, tap the install prompt (or menu → **Add
  to Home screen** / **Install app**).

The service worker caches the app shell so the kiosk loads instantly and
keeps working briefly if the LXC reboots — API calls always go to the
network, so commands fail visibly when the server is down rather than
silently no-op.

---

## Backups

Pairings and the ADB key live in the `tv-ir-data` Docker volume. Losing
it means re-pairing every Vizio (4) and LG (4) and re-accepting ADB on
every Android/Fire TV (8) — tedious but recoverable.

Manual backup from inside the container:
```bash
docker compose exec server python -m app.backup
# writes /app/data/backups/tv-ir-data-YYYY-MM-DD.tgz
```

Cron on the LXC for daily off-volume backup:
```cron
0 4 * * *  docker run --rm \
    -v tv-ir-data:/data \
    -v /var/backups/tv-ir:/backup \
    alpine tar czf /backup/tv-ir-data-$(date +\%F).tgz -C /data .
```

To restore: stop the container, untar into the volume, start.

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

## Updating the channel lineup

Whenever someone re-tunes a DirecTV receiver at the rack, the labels and
channel numbers on the tablet will be wrong until the inventory is
updated. The fix is two YAML edits, no rebuild:

1. Edit `server/config/tvs.yaml` and update both fields in lockstep:
   ```yaml
   preset_labels:
     "1": "ESPN"             # ← what the bartender sees on the button
   preset_channels:
     "1": "206"              # ← DirecTV channel, shown beneath the label
   ```
2. Restart the server so the change is picked up:
   ```bash
   docker compose restart server
   ```

The full Chicago / 60070 channel reference lives at
[`server/config/directv_lineup.yaml`](server/config/directv_lineup.yaml).
It's organised by category (national sports, regional sports, locals,
news, entertainment) plus a `current_assignment` block that mirrors what's
in `tvs.yaml`. Use it to look up channel numbers when re-assigning a box;
keep it in sync with `tvs.yaml` so the doc stays trustworthy.

The RF channels (30.2 → 37.2) the Thor modulator broadcasts are wired
into hardware and don't change — only the DirecTV channel each *box* is
tuned to varies.

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

| Method | Path                                            | Purpose                              |
|--------|-------------------------------------------------|--------------------------------------|
| GET    | `/api/health`                                   | liveness probe                       |
| GET    | `/api/tvs`                                      | `{ presets, zones, tvs }`            |
| GET    | `/api/tvs/{id}`                                 | single TV with status                |
| GET    | `/api/tvs/status`                               | reachability map                     |
| POST   | `/api/tvs/{id}/power`                           | body `{state: on \| off \| toggle}`  |
| POST   | `/api/tvs/{id}/preset/{n}`                      | switch one TV to box N (1..8)        |
| POST   | `/api/tvs/{id}/key`                             | body `{key: "Vol_up"}` etc.          |
| POST   | `/api/scenes/open`                              | every TV on                          |
| POST   | `/api/scenes/close`                             | every TV off                         |
| POST   | `/api/scenes/all-on` / `all-off`                | aliases                              |
| POST   | `/api/scenes/all-to-preset/{n}`                 | every TV to box N                    |
| POST   | `/api/scenes/zone/{zone}/power?state=on\|off`   | power for one zone                   |
| POST   | `/api/scenes/zone/{zone}/preset/{n}`            | one zone to box N                    |
| GET    | `/api/scenes/events`                            | list saved events                    |
| POST   | `/api/scenes/events/{id}/apply`                 | apply a saved event                  |
| GET    | `/api/boxes`                                    | list DirecTV receivers               |
| GET    | `/api/boxes/{n}/tuned`                          | what's tuned on box N                |
| POST   | `/api/boxes/{n}/tune?channel=NNN`               | tune box N                           |
| POST   | `/api/boxes/{n}/key/{key}`                      | remote keypress on box N             |
| GET    | `/api/auth/status`                              | `{pin_required, authed}`             |
| POST   | `/api/auth/login`                               | body `{pin}` → sets cookie           |
| POST   | `/api/auth/logout`                              | clears cookie                        |

Each preset returned by `/api/tvs` looks like:
```json
{ "num": 1, "label": "ESPN", "rf": "30.2", "channel": "206" }
```
- `num` — preset slot, 1..8
- `label` — bartender-facing channel name (from `preset_labels`)
- `rf` — RF channel the Thor modulator broadcasts (derived from `preset_template`)
- `channel` — DirecTV channel the box is tuned to (from `preset_channels`)

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
│   │   ├── tvs.yaml                gitignored — your real inventory
│   │   └── directv_lineup.yaml     Chicago/60070 DirecTV channel reference
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
│   ├── preview.html                static UI preview, no build needed
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
