# Deploy the server with Komodo

Use a Git-backed **Stack** on the Linux host connected to Komodo. The stack builds the server from `docker-compose.yml`. Client installation is separate.

## Stack configuration

| Setting | Value |
| --- | --- |
| Repository | `improper/steam-personal-cloud` |
| Reference | Pin `v0.3.0-beta.1` or its commit |
| Compose file | `docker-compose.yml` |
| Run Build | On |
| Auto Pull | Off; this stack builds from source |
| Destroy Before Deploy | Off |

Configure Git access if your deployment requires authentication. Keep deployment credentials in Komodo rather than the source repository.

## Environment

Create secret variables for the administrator token and Immich API key. In the stack environment, provide:

```dotenv
# Replace these addresses with hosts reachable on your network.
SPC_BIND=10.0.0.10
SPC_BIND_PORT=8787
SPC_HOST_STORAGE=/srv/steam-personal-cloud/storage
SPC_TOKEN=[[SPC_TRANSFER_TOKEN]]
IMMICH_URL=http://immich-server:2283
IMMICH_API_KEY=[[SPC_IMMICH_API_KEY]]
IMMICH_ALBUM="Game Center"
SPC_IDLE_SECONDS=600
```

The example bind address is a placeholder. Set the actual server's LAN address, or use loopback behind a trusted reverse proxy. The Immich URL must resolve from inside the container. Port `8787` is internal to the container; `SPC_BIND_PORT` controls the host port.

Create a persistent storage directory and ensure the container can write to it. Keep captures, SQLite state and secrets outside the Git checkout. Komodo supplies the environment; do not run `scripts/setup-host.sh` for this deployment.

## Deploy and pair

Deploy the pinned beta reference and check `/health` on your chosen private server address. Confirm its version matches the client release. Open the dashboard, sign in with the administrator token and generate a one-time pairing code for each client.

Keep the administrator token and Immich API key on the server. Device tokens are scoped to one client/account. Do not expose this service directly to the public internet; use HTTPS or a VPN across untrusted networks.

## Updates

Review a new release and update the pinned reference deliberately. Back up server state and storage first. For development deployments following `main`, Komodo's Git deploy webhook can rebuild on pushes. GitHub cannot reach a private LAN listener directly; a reachable authenticated listener or private polling arrangement is required.

Test one screenshot and one saved recording through processing, Immich and gallery playback after an update. Monitor archive growth: server inbox copies are retained, including after gallery Trash actions.

References: [Komodo Compose deployment](https://komo.do/docs/deploy/compose), [webhooks](https://komo.do/docs/automate/webhooks), [providers](https://komo.do/docs/configuration/providers), [variables](https://komo.do/docs/configuration/variables).
