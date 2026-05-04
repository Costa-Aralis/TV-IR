# TV-IR

Custom web app to control 30 TVs at a bar via IR (ESP32 nodes) and Roku ECP, no
physical remotes.

## Topology

- **One ESP32 per TV** on WiFi, powered by a dedicated USB wall-wart (not the
  TV's USB port — that cuts power when the TV is off).
- **Stick-on IR emitter** mounted on each TV's IR window, wired to the ESP32.
- **Roku TVs** are controlled over IP (Roku ECP, port 8060) — no IR node
  needed for those.
- **Server** runs in Docker on a Proxmox LXC at `172.31.250.31`. Hosts the
  FastAPI backend + tablet web UI.
- **Channel changes** drive a Thor RF modulator: each "preset" sends a key
  sequence (e.g. `7 . 1 ENTER`) corresponding to one of 8 DirecTV boxes.

## Layout

```
TV-IR/
├── docker-compose.yml
├── server/             FastAPI backend + serves SPA
├── web/                Vite + React tablet UI
├── firmware/           PlatformIO ESP32 firmware (one image, all 30 boards)
└── flipper-irdb/       (gitignored) clone of Flipper-IRDB for IR codes
```

## First-time setup

```bash
# 1. Clone Flipper-IRDB next to this repo (provides per-brand .ir files)
git clone https://github.com/Lucaslhm/Flipper-IRDB.git flipper-irdb

# 2. Copy templates and fill in real values
cp firmware/src/secrets.h.example firmware/src/secrets.h
cp server/config/tvs.example.yaml server/config/tvs.yaml
# edit both with your WiFi creds and TV inventory

# 3. Flash one ESP32 (PlatformIO required)
cd firmware && pio run -t upload

# 4. Bring up the server
docker compose up -d
# tablet UI: http://172.31.250.31/
```

## Adding a TV

1. Find the brand/model in `flipper-irdb/TVs/<Brand>/<Model>.ir`.
2. Flash an ESP32 with the firmware; note its hostname (`tvir-XXXXXX.local`).
3. Add an entry to `server/config/tvs.yaml` (see the example file).
4. Restart the server container (`docker compose restart server`).

## API

- `GET /api/tvs` — list TVs
- `POST /api/tvs/{id}/power` — body: `{"state":"toggle"|"on"|"off"}`
- `POST /api/tvs/{id}/preset/{n}` — channel preset 1–8
- `POST /api/tvs/{id}/key` — body: `{"key":"Vol_up"}`
- `POST /api/scenes/all-off`
- `POST /api/scenes/all-to-preset/{n}`
