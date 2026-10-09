# Native Steam Gallery (v0.3 preview)

`Steam Personal Cloud Gallery` is the primary fullscreen-capable Linux Qt6 application. It is a real native application, not a browser tab or a WebView. The older read-only local HTTP dashboard remains available as **Steam Personal Cloud Diagnostics** for advanced users; its loopback media proxy is also used for ranged playback via Qt Multimedia. The upload agent and personal-cloud server are unchanged except for a narrow authenticated media proxy + Immich Trash API.

## Playing on Xubuntu / Steam

Install the `.deb` (released via GitHub Actions), then launch **Steam Personal Cloud Gallery** from the Xubuntu app menu, or add `/usr/bin/steam-personal-cloud-gallery --fullscreen` as a non-Steam game. Steam Input's keyboard template supports D-pad mapped to arrows, A mapped to Return, and B mapped to Escape. On Linux the app also reads a single available `/dev/input/js*` gamepad (prefers Steam/Xbox controllers) for directional navigation, A/select, B/back, and details. Controller mappings vary by model; keyboard is the reliable fallback. System joystick access is best-effort and never grabs devices.

## Status language

- **Waiting**: capture is still local or newer than the last successfully backed-up copy.
- **Backed up**: client's file-level transfer state says the server accepted the file.
- **Processing**: server has the recording but is working on assembly or Immich upload.
- **In Immich**: asset has a current server-recorded Immich ID; Immich may still be generating previews or transcodes.
- **Needs attention**: retryable server-side processing error.

Video groups represent Steam recording directories and may consist of many `.m4s` pieces. They are **not** directly playable until the family server assembles the recording and Immich accepts it. Native player requests the transcoded playback endpoint (`/api/assets/{id}/video/playback`) through the authenticated server and loopback proxies. No Immich API key is sent to the client.

## Deletion behavior

An expanded action asks users to select **Local copy**, **Immich copy**, or **Both**, then asks for confirmation. Local copies go to the desktop user's Trash (not `unlink`); recording folder deletion moves that folder as a unit. Immich copies go to **Immich Trash**, not irreversible purge. `Both` attempts Immich first and stops if it fails, to prevent silent partial removal. Local path validation restricts deletion to a known screenshot file or recording directory under the configured library. Delete is only available when that copy exists. Existing original server inbox backups are intentionally retained; deleting from Immich does not erase the server archive. Device credentials are limited to the client's own assets.

## Practical limitations

- The virtual playback implementation is **new and not yet tested on the user's MacBook Pro A1707 or live Immich deployment**. H.264/AAC QtMultimedia availability depends on the Xubuntu 26.04 codec installation.
- Remote gallery listing still follows the server's recent-media API limit; long-term large library pagination and Steam AppID/title artwork are tracked separately.
- No real-time byte-level transfer graph; status is refreshed periodically (12 seconds) with the most recent agent sync state.
- Steam overlay and controller button assignments vary by Steam Input layout; choose a keyboard mapping if the gamepad device is not visible.
- Do not expose port 8787 on the public Internet. HTTP media is only intended for trusted LANs; use VPN/HTTPS for access outside the home.
