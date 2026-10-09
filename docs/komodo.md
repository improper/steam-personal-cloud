# Deploy with Komodo

Steam Personal Cloud is a **Git-backed Stack** in Komodo, not a separate Repo + Deployment. This assumes the Docker host (`family-server`, `192.168.1.27`) is connected to Komodo.

## 1. Private GitHub access

In **Settings → Providers**, add Git provider `github.com` with a GitHub username and fine-grained PAT granting **Contents: Read-only** to `improper/steam-personal-cloud`. The repository is private. The PAT owner must have repository access; some organizations require approval.

## 2. Create the Stack

Create a **Stack** (e.g. `steam-personal-cloud`) assigned to `family-server` with these properties:

| Property | Value |
| --- | --- |
| Source | Git repository |
| Repo | `improper/steam-personal-cloud` |
| Git Provider | `github.com` |
| Git Account | previously configured provider account |
| Branch | `feature/initial-prototype` during development; change to `main` after merge |
| Compose file | `docker-compose.yml` |
| Run Build | **On** (`build: ./server` is local) |
| Auto Pull | **Off** (it is for remotely published images) |
| Destroy Before Deploy | **Off** |
| Webhook Enabled | **On**, if using push webhooks |
| Webhook Force Deploy | **On**, so changes in `server/app.py` rebuild even if Compose is unchanged |

Do not set `files_on_host`; let Komodo clone the repository. Do not pin a commit if following branch updates.

## 3. Secrets and environment

In **Settings → Variables**, create `SPC_TRANSFER_TOKEN` and `SPC_IMMICH_API_KEY`, checking the **Secret** flag for both. Generate a transfer token, for example, with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` on a trusted machine. Copy the transfer token later to the Steam client's interactive installer.

Paste the following into the Stack **Environment** editor:

```dotenv
SPC_BIND=192.168.1.27
SPC_BIND_PORT=8787
SPC_HOST_STORAGE=/srv/steam-personal-cloud/storage
SPC_TOKEN=[[SPC_TRANSFER_TOKEN]]
IMMICH_URL=http://192.168.1.27:2283
IMMICH_API_KEY=[[SPC_IMMICH_API_KEY]]
IMMICH_ALBUM="Game Center"
SPC_IDLE_SECONDS=600
```

Before deployment, create the storage directory on the host and verify that Docker's container can write to it: `sudo mkdir -p /srv/steam-personal-cloud/storage`. Using an absolute host path keeps state outside Komodo's Git clone.

Komodo generates the Compose environment file; **do not run `scripts/setup-host.sh` for this deployment**, since that creates a separate `.env` and is intended for a manual Compose install.

Deploy once manually, then test `http://192.168.1.27:<SPC_BIND_PORT>/health` from the LAN (default `8787`). `SPC_BIND_PORT` sets only the Docker host port; the container still listens internally on `8787`. Keep this port internal; v0.1 uses a shared-token HTTP protocol. No Steam client's original recordings are removed.

## 4. Automatic updates

For true **Git push → rebuild → redeploy**, use a **Stack deploy webhook**:

1. Open the Stack's **Config → Webhooks** and copy the *Deploy* URL.
2. In GitHub go to `improper/steam-personal-cloud` → **Settings → Webhooks → Add webhook**.
3. Set **Payload URL** to Komodo's deploy listener URL, **Content type** to `application/json`, select **Just the push event**, and set the secret to Komodo's `KOMODO_WEBHOOK_SECRET` or a Stack-specific webhook secret if configured.
4. Push a commit to the configured Stack branch. Komodo filters pushes by branch. Test GitHub's webhook delivery log and the Stack deployment history.

**Important:** GitHub cannot call a private `192.168.1.27` URL directly. If Komodo is only on the LAN, expose *only the authenticated `/listener/` path* via a secure public HTTPS reverse proxy, or use a private polling-based deployment Action/Procedure. Do not publicly expose the entire Komodo admin interface just for GitHub webhooks.

Unlike `Auto Update` and `Poll for Updates`, the Git webhook responds to **source changes**. The former Komodo toggles are for **container image digest** updates and are not the right trigger for this source-built application.

## 5. Validation / safety

- Before trusting background recording archiving, test a screenshot and one complete Steam `.m4s`/`session.mpd` recording end-to-end. The prototype's fragment reconstruction is **not yet validated** with actual Steam recordings.
- Monitor storage growth: all background sessions can consume substantial disk space; the server intentionally retains original fragments.
- Keep the Immich API key only on the server and the Steam client token on clients.
- There is no need to install Node.js or FFmpeg on the Steam clients.

References: https://komo.do/docs/deploy/compose , https://komo.do/docs/automate/webhooks , https://komo.do/docs/configuration/providers , https://komo.do/docs/configuration/variables
