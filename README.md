# Steam Personal Cloud — prototype v0.1

A **self-hosted Steam capture backup and Immich ingest pipeline**. Steam clients only read completed-enough files and send them at a capped rate; the family server does FFmpeg processing and Immich uploads. Steam's original files are never modified or deleted.

> **Early prototype.** Steam's segmented video format varies by Steam version, recording type and session. DASH remuxing is implemented, but has **not yet been validated with the actual recordings from the Xubuntu gamecenter**. Rolling buffer preservation across overwritten chunks is not guaranteed; do not rely on this as your only copy. Keep Steam's recording storage and local backup until verified.

## Components

- `client/agent.py`: Python standard-library file sender. Scans screenshot/recording directories every minute with a systemd **user** timer, sends new/changed `.png/.jpg/.webp/.mpd/.m4s/.pb/.mp4` files with SHA-256 and 2 MiB/s default rate cap. Skips recently written files and symlinks; retries on failure. No FFmpeg, Node, or Immich credentials on game clients.
- `server/app.py`: one FastAPI receiver / worker with persistent SQLite state. Keeps uploaded originals; considers video sessions idle after 10 minutes, then attempts lossless DASH→MP4 remux on the server. Uploads media to Immich, adds it to a `Game Center` album and applies hierarchical tags for account, client, game ID, date, and screenshot/video.
- `server/dashboard.html`: dark 1080p-friendly status page supporting Steam Input keyboard mapping and the browser Gamepad API. Shows counts and per-media statuses, not yet native Godot.

## Requirements

- Family server (`192.168.1.27`): Linux, Docker and Docker Compose, network access to Immich.
- Steam client (Xubuntu): Python 3, systemd user session, outbound LAN access to `192.168.1.27:8787`.
- Immich API key with permission to upload assets, create/edit albums, and create/use tags.

## Set up the family server

```bash
git clone https://github.com/improper/steam-personal-cloud.git
cd steam-personal-cloud
bash scripts/setup-host.sh   # prompts for bind IP, Immich URL, hidden API key, album, storage
docker compose up -d --build
docker compose logs -f personal-cloud
```

Keep `.env` **on the host**: never commit or publish it. If the folder is not writable by the container, adjust ownership of the storage folder to the container user. `SPC_TOKEN` in `.env` is the secret needed for each client to connect. Use a dedicated Immich API key for a dedicated account if desired.

## Set up the Xubuntu gamecenter

From the same clone (or a downloaded source archive):

```bash
bash scripts/install-linux.sh    # prompts for server URL, hidden client token, account and paths
systemctl --user start steam-personal-cloud-sync.service
journalctl --user -u steam-personal-cloud-sync.service -n 50 --no-pager
```

Default media sources:

- `/home/gamecenter/Gameplay/Screenshots`
- `/home/gamecenter/Gameplay/Recordings`
- Steam local account directory `userdata/728364463` (used as a tag; this is *not* the Steam64 account ID).

The user timer runs approximately once per minute. A first backfill of an existing recording may take a while over Wi-Fi. The client uploads its original fragments, **not a new MP4**.

## Steam-friendly dashboard

Visit `http://192.168.1.27:8787` from a browser and supply the shared client token to inspect per-media states. Add a browser command opening that URL as a **non-Steam game** for controller navigation. Arrow keys / D-pad navigate, Enter / A activates focused buttons when supported. This v0.1 dashboard shows aggregate status, not a native standalone Linux app or frame-accurate transfer progress.

## Operational notes

- The upload protocol is a shared-token HTTP API **intended for trusted LANs only**. For remote clients, add HTTPS via a reverse proxy/VPN first; do not expose port 8787 publicly. Any client with the shared token can send media or read dashboard status. Future releases should use per-device credentials.
- The server never deletes originals and does not automatically prune archives. Monitor disk usage (`storage/inbox`, `storage/processing`, SQLite). Enabling all background sessions can grow storage rapidly.
- The receiver limits each individual file to 128 MiB by default, configurable via Compose. It does not currently support byte-range resume; a failed file resumes from the beginning on the next scan. Successfully uploaded files are skipped.
- If a recording's `session.mpd` does not reference the backed-up fragments correctly, processing will show `Retrying` with an FFmpeg error. The stored source chunks remain untouched for recovery.
- Status `In Immich` means Immich accepted the asset and tagging, **not** that Immich's own thumbnail or transcoding background jobs have finished.
- Date tags reflect metadata parsing of the Steam filename (where recognized) or file mtime. Verify date and game names during the initial test.

## Next

Validate a real Steam DASH recording end-to-end, then strengthen rolling-buffer snapshots, transfer resume, client-specific credentials, Immich deep links, and a Godot native gamepad interface.
