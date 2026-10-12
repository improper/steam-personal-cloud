# Steam Personal Cloud

Steam Personal Cloud brings Steam screenshots and saved recordings into a native, controller-friendly library and backs them up to a self-hosted server with Immich integration.

**First beta: v0.3.0-beta.1.** The Linux client is distributed as a compiled Debian package for Ubuntu 24.04 or later on x86-64. This is proprietary software; no open-source license is granted. Third-party libraries retain their own licenses. See [COPYRIGHT](COPYRIGHT) and [third-party notices](THIRD_PARTY_NOTICES.md).

## What the beta includes

- A fullscreen Qt gallery designed for Steam Big Picture, with large previews, readable text, visible focus and controller/key prompts.
- Screenshots from Steam's native library and your export folder, grouped as one capture when both copies exist.
- Local photo viewing, Immich previews, and streamed video playback with pause, seek, volume and capture browsing.
- Background backup, one-time device pairing, and a local diagnostics screen.
- Explicit, recoverable removal of local copies, Immich copies, or both. Local screenshot removal includes matched Steam originals, exports and thumbnails. Server inbox backups are retained.

## Install the Linux client

Download `steam-personal-cloud-client_0.3.0~beta.1_amd64.deb` and its checksum from [the beta release](https://github.com/improper/steam-personal-cloud/releases/tag/v0.3.0-beta.1).

```bash
sha256sum -c steam-personal-cloud-client_0.3.0~beta.1_amd64.deb.sha256
sudo apt install ./steam-personal-cloud-client_0.3.0~beta.1_amd64.deb
steam-personal-cloud-setup
```

Setup asks for your backup server URL, a one-time pairing code, Steam userdata account ID, capture folders and an optional upload speed limit. If there is one Steam userdata account, setup suggests it. This ID is the local directory name under Steam's `userdata`, not your Steam64 ID. Existing pairing and sync history are preserved when upgrading.

Add **Steam Personal Cloud Gallery** as a non-Steam game. Alternatively, select `/usr/bin/steam-personal-cloud-gallery` and set its launch options to `--fullscreen`. Launch it through Steam to use your Steam Input layout. Map arrows, Enter and Escape for navigation, select and back; the remaining shortcuts are in the [gallery guide](docs/native-gallery.md).

The package includes its runtime; customers do not need to install Python packages. The gallery can display local photos while the server is unavailable. Recordings become playable once the server assembles them and Immich accepts them.

## Set up the backup server

The beta server uses Docker Compose and an existing Immich installation. Deploy the server from the matching release tag; server setup is an administrator task, separate from installing the client.

```bash
git clone https://github.com/improper/steam-personal-cloud.git
cd steam-personal-cloud
git checkout v0.3.0-beta.1
bash scripts/setup-host.sh
docker compose up -d --build
docker compose logs -f personal-cloud
```

Choose a bind address accessible to your clients and enter an Immich URL that the container can reach. The default bind address is loopback. Keep the service on a trusted private network; use HTTPS or a VPN for connections across untrusted networks. The default host port is `8787`, configurable with `SPC_BIND_PORT`.

Keep `.env` and API keys outside version control. Open the server dashboard, sign in with the administrator token from `.env`, and select **Pair device**. Codes expire after five minutes and can be redeemed once. Clients receive scoped device tokens; the Immich API key remains on the server.

For a Git-backed Komodo deployment, see [the deployment guide](docs/komodo.md). Pin the beta tag for a repeatable deployment rather than following a development branch.

## Operation and support

The client scans approximately once a minute and waits for recently changed files to settle before uploading. A speed limit of `0` means unlimited. Successfully acknowledged files are skipped, and failures retry on later scans.

```bash
# Request a scan
systemctl --user start steam-personal-cloud-sync.service

# Read recent upload results
journalctl --user -u steam-personal-cloud-sync.service -n 50 --no-pager

# Open local diagnostics
steam-personal-cloud-dashboard
```

Run `steam-personal-cloud-setup` again to repair pairing or change capture folders and bandwidth. Back up the client configuration before changing it. Include the client/server version and relevant error text when reporting a problem; remove credentials and personal paths from logs shared publicly.

## Beta limitations

- Steam recording formats vary. Saved clips are supported, but rolling-buffer preservation and recordings spanning multiple DASH sessions still need broader validation. Keep local originals and another backup for important captures.
- Deletion moves files and Immich assets to Trash. It does not purge server inbox archives. Steam owns its media catalogue and may retain entries after original and thumbnail files have been removed.
- Controller numbering varies. Steam Input keyboard mappings are the reliable fallback. Steam Link client video has not been fully validated.
- Immich may still be generating previews or transcodes after an asset is accepted.
- Long-term library pagination and resumable file transfers are not included in this beta.

See [the changelog](CHANGELOG.md), [gallery guide](docs/native-gallery.md), and [release build notes](docs/releasing.md). The source repository is published for visibility; that publication does not grant an open-source license.
