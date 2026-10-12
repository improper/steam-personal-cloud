# Gallery guide

Steam Personal Cloud Gallery is the primary native Linux application. It uses Qt through PySide6 and runs in one window, including viewing, settings and removal. The browser-based Diagnostics screen is separate and intended for troubleshooting.

## Start through Steam

Install the compiled client package, complete `steam-personal-cloud-setup`, and add **Steam Personal Cloud Gallery** as a non-Steam game. Set launch options to `--fullscreen` for Big Picture use. Steam Input can map the keyboard shortcuts below. Raw Linux joystick support reads one available controller without grabbing the device; button numbering varies between controller models.

| Action | Keyboard | Standard Xbox-style controller |
| --- | --- | --- |
| Navigate | Arrows | D-pad or stick |
| Activate focused control | Enter | A |
| Back | Escape | B |
| Play or pause | Space | X |
| Previous/next capture, or library filter | Page Up/Page Down | LB/RB |
| Details | I | Y |
| Settings | S | Menu |
| Refresh library | R | Focus the Refresh button and select |
| Toggle fullscreen | F11 | Settings action |

On the seek slider, left/right skips ten seconds. On volume, it changes five percentage points. Back at the library keeps the app open; **Exit gallery** is in Settings. The active filter determines the viewer's capture sequence. Back returns focus to the last viewed capture.

## Captures and status

The gallery reads the configured screenshot export folder and the active account's native Steam screenshot library. It supports native and Flatpak Steam installations. Original JPEGs and exported PNGs with the same game ID, timestamp and capture number appear as one capture; thumbnail derivatives are excluded.

| Status | Meaning |
| --- | --- |
| Waiting to back up | A local capture has not been acknowledged by the server. |
| Preparing for Immich | Sources have transferred, but the capture is not ready in Immich. |
| Processing | The server is assembling or uploading the capture. |
| Available in Immich | The server has a current Immich asset ID. Previews or transcodes may still be processing. |
| Needs attention | A processing error needs retry or investigation. |
| Local only · Immich trashed | A local original remains after its Immich copy was removed. |

New local captures appear immediately in the gallery; the uploader still observes the configured settling period. Already archived exports prevent remaining native JPEGs from being uploaded as new captures after an Immich removal.

Saved clip directories may contain the same source session as a temporary recording directory. An Immich-ready saved clip takes precedence in the gallery. Deduplication does not erase either local recording.

## Viewing and settings

Photos use an available local original immediately. Remote-only photos load in the background and offer Retry on failure. WebP previews and covers also decode when Qt's optional WebP plugin is absent.

Videos stream through authenticated server and loopback proxies. The app prefers Immich's transcoded playback endpoint and can fall back to the original when conversion is incomplete. The Immich API key is never sent to the client. Recordings consisting of `.m4s` fragments are not directly playable before server processing.

The viewer fits the whole image. Controls hide after four seconds of inactivity while a photo is available or video is playing. The first navigation/selection input reveals hidden controls; Back, play/pause and previous/next shortcuts act immediately. Controls remain visible during loading, pause or error. Playback never automatically advances to another capture.

Settings remember autoplay, control hiding, volume, mute and launch-fullscreen preferences. `--fullscreen` overrides the saved launch preference. Changes apply immediately. Opening Settings, Details or removal pauses video; returning leaves it paused.

## Removal

**Remove…** asks you to choose local copies, Immich copies or both, then asks for confirmation with cancellation focused by default.

- Local screenshot removal includes matched exports, Steam originals and Steam thumbnails. Files go to your desktop Trash.
- Recording removal moves the selected recording directory as a unit.
- Remote removal moves matched assets to Immich Trash, without permanent purge.
- Both validates every local target first, then attempts Immich removal before local removal. A failed remote operation stops local removal.
- Removal runs in the background and disables further actions until completion. Partial failures are reported; refresh before retrying.

Server inbox archives are retained. Steam owns its live `screenshots.vdf` catalogue; the app removes files but does not rewrite that catalogue. Steam can retain a cached or missing-file entry in its native media browser.

## Troubleshooting

Open Diagnostics for transfer and server state, or read user service logs as described in the [README](../README.md). A valid local photo can be viewed without the server. Video availability depends on server processing, Immich and supported codecs. Keep another backup while testing recording formats.
