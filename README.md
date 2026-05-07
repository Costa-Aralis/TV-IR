# TV-IR

Custom web app to control 25+ TVs at a bar from a tablet, no physical
remotes. Despite the project name, almost every modern smart TV is
controlled over IP rather than IR.

## Topology

| Brand / OS              | Protocol                    | Port    | Pairing |
|-------------------------|-----------------------------|---------|---------|
| Vizio SmartCast         | HTTPS REST                  | 7345    | one-time PIN on screen |
| LG webOS                | WebSocket (SSAP)            | 3001    | one-time accept prompt |
| Roku TV (incl. TCL/Sharp)| Roku ECP                   | 8060    | none |
| Android TV / Google TV  | ADB over WiFi               | 5555    | one-time accept prompt |
| Fire TV                 | ADB over WiFi               | 5555    | one-time accept prompt |
| Anything else           | IR via ESP32 + Flipper-IRDB | —       | flash firmware |

The **server** runs in Docker on a Proxmox LXC at `172.31.250.31`. Hosts the
FastAPI backend + tablet web UI. **Channel changes** drive a Thor RF modulator:
each preset sends a digit key sequence (e.g. `3 0 . 2 ENTER` for channel 30.2)
corresponding to one of 8 DirecTV boxes.

## Layout

```
TV-IR/
├── docker-compose.yml
├── server/             FastAPI backend, drivers, pairing CLI, serves SPA
├── web/                Vite + React tablet UI
├── firmware/           PlatformIO ESP32 firmware (kept for any IR-only TVs)
└── flipper-irdb/       (gitignored) clone of Flipper-IRDB for IR codes
```

## First-time setup

```bash
# 1. (Optional) clone Flipper-IRDB next to this repo, only needed if any TV
#    ends up requiring IR.
git clone https://github.com/Lucaslhm/Flipper-IRDB.git flipper-irdb

# 2. Copy templates and fill in real values
cp server/config/tvs.example.yaml server/config/tvs.yaml
# edit tvs.yaml with your TV inventory

# 3. Bring up the server
docker compose up -d
# tablet UI: http://172.31.250.31/

# 4. Pair each TV that requires it
docker compose exec server python -m app.pair --all
# walks through Vizio PIN entry, LG accept-prompt, ADB accept-prompt per TV
```

For per-TV pairing only:

```bash
docker compose exec server python -m app.pair tv01 tv05
```

## Per-TV setup notes

- **Vizio SmartCast**: nothing on the TV. Run `python -m app.pair tvNN`,
  enter the 4-digit PIN that appears on screen.
- **LG webOS**: ensure "LG Connect Apps" is enabled in the TV's settings.
  Run pairing; accept the prompt with the magic remote.
- **Roku TVs**: enable "Network Access" in Settings → System → Advanced
  System Settings → Control by Mobile Apps. No pairing required.
- **Android TV / Google TV (Hisense)**: Settings → About → click Build
  number 7 times → Settings → Developer Options → enable "USB debugging"
  / "Network debugging".
- **Fire TV (Insignia)**: Settings → My Fire TV → About → click Build
  number 7 times → back to My Fire TV → Developer Options → ADB Debugging
  ON.

For ADB-based TVs, the first connection prompts an "Allow this computer?"
dialog on the TV — accept once and the controller's RSA fingerprint is
remembered forever.

## Adding a TV

1. Add an entry to `server/config/tvs.yaml` with the right `type` and `url`.
2. If the type requires pairing, run `docker compose exec server python -m
   app.pair <tv_id>`.
3. Restart the server (`docker compose restart server`).

## API

- `GET  /api/tvs`                          list TVs
- `POST /api/tvs/{id}/power`               body: `{"state":"toggle"|"on"|"off"}`
- `POST /api/tvs/{id}/preset/{n}`          channel preset 1–8
- `POST /api/tvs/{id}/key`                 body: `{"key":"Vol_up"}`
- `POST /api/scenes/all-off`
- `POST /api/scenes/all-on`
- `POST /api/scenes/all-to-preset/{n}`
