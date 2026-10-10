# Native Steam Gallery (v0.3 preview)

`Steam Personal Cloud Gallery` is the primary fullscreen-capable Linux Qt6 application. It is a real native application, not a browser tab or a WebView. The older read-only local HTTP dashboard remains available as **Steam Personal Cloud Diagnostics** for advanced users; its loopback media proxy is also used for ranged playback via Qt Multimedia. The upload agent and personal-cloud server are unchanged except for a narrow authenticated media proxy + Immich Trash API.

## Playing on Xubuntu / Steam

Install the `.deb` (released via GitHub Actions), then launch **Steam Personal Cloud Gallery** from the Xubuntu app menu, or add `/usr/bin/steam-personal-cloud-gallery --fullscreen` as a non-Steam game. Steam Input's keyboard template supports D-pad mapped to arrows, A mapped to Return, and B mapped to Escape. On Linux the app also reads a single available `/dev/input/js*` gamepad (prefers Steam/Xbox controllers) for directional navigation, A/select, B/back, and details. Controller mappings vary by model; keyboard is the reliable fallback. System joystick access is best-effort and never grabs devices.

## Status language

- **Waiting**: capture is still local or newer than the last successfully backed-up copy.
- **Preparing for Immich**: the game center transferred source fragments to the family server; they are not yet available in Immich. Transfer details are only in the advanced panel.
- **Processing**: server has the recording but is working on assembly or Immich upload.
- **Available in Immich**: asset has a current server-recorded Immich ID; Immich may still be generating previews or transcodes.
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


## Streamlined playback, covers and metadata

Click a gallery tile to open an **inline** picture viewer or video player in the same native Steam window. A video in Immich starts automatically; play/pause, a seek slider and 10-second skip buttons are available. Qt's media probe now advertises the full stream length; Immich's preferred transcoded playback endpoint falls back to the original video if transcoding has not finished and the codec is supported.

Ready captures prefer Immich's canonical thumbnail, even if a local source exists. Steam's available \`thumbnail.*\`, \`thumb.*\`, \`preview.*\`, \`poster.*\`, or \`cover.*\` files provide a local fallback; not every Steam installation creates a separate thumbnail file, so a generic tile may remain until Immich generates its preview.

Folder IDs are no longer displayed as user-facing titles. We consult Steam \`appmanifest_<appid>.acf\` in installed library directories for a game title and parse the recording date in local time. If no matching game is installed, the gallery uses an accessible generic label and date rather than a raw ID. New uploads send game titles to the family server, which writes an Immich game-title tag. It also attempts an optional \`asset.update\` description containing game, date and media type; an API key without that permission will still archive, but description updates are skipped.

Saved Steam clip folders may embed the same \`fg_...\` video session already present in a temporary recordings folder. A ready saved clip takes precedence in the local gallery; **neither copy is erased** by deduplication. All database/media deletion actions remain explicit and separate. Existing duplicate Immich assets are not silently removed.

A saved clip's metadata may refer to multiple Steam DASH sessions; the video remuxer still needs real-recording validation. Use the error shown in Advanced details if playback remains unavailable.


## Console-style viewing and settings

The gallery uses explicit selected filter tabs, large focus outlines, and tiles that scroll without compressing their capture labels. The active filter determines the viewer's browsing order. **Previous / Next** and an **N of M** counter let you browse without returning to the grid. The order is held steady while viewing, and Back returns focus to the last viewed capture. Navigation stops at the first and last capture.

The viewer keeps the entire photo or video visible. Its header and controls collapse after four seconds of inactivity while a photo is available or video is playing. Move the pointer or use a navigation input to reveal them; the first navigation/activation input only reveals controls. Direct play/pause, previous/next, and Back shortcuts still act immediately. Controls stay visible while paused, loading, or showing an error. Remote photos load in the background, retaining the local image when available; a failed request offers Retry. Video playback offers replay, ±10-second seeking, mute, and volume. Playback never automatically advances to another capture.

| Action | Keyboard | Standard Xbox-style raw joystick |
| --- | --- | --- |
| Navigate | Arrows | D-pad / stick |
| Activate focused control | Enter | A |
| Back | Escape | B |
| Play / pause video | Space | X |
| Previous / next capture | Page Up / Page Down | LB / RB |
| Details | I | Y |
| Settings | S | Menu |
| Fullscreen | F11 | Settings button |

Steam Input can map the keyboard shortcuts above. Raw Linux joystick button numbering varies by controller, so these labels describe the standard Xbox-style layout rather than guaranteed Nintendo or PlayStation mappings. Tab navigation is also supported. On sliders, left/right adjusts playback by ten seconds or volume by five percent. Space controls playback in the viewer and does not activate a focused removal button.

**Settings** is an inline screen with video autoplay (default on), automatic control hiding (on), volume (80%), mute (off), and launch fullscreen (off). Preferences are saved with Qt QSettings, separately from pairing configuration; the `--fullscreen` launch argument overrides the saved launch preference. Changes apply immediately, Restore defaults resets preferences, and Toggle fullscreen now changes the current window. Exit gallery is an explicit Settings action; Back at the library does not leave fullscreen or exit the app.

**Details** shows capture type, date, copy availability, and any capture processing error. Opening Details, Settings, or removal pauses video; returning leaves it paused. Removal remains an explicit **Remove…** action and the final confirmation defaults to **No, go back**. Secondary screens block viewer playback, browsing, and removal shortcuts.

Offscreen tests exercise controller navigation, view sizing at 720p/1080p, photo loading failures, preference persistence, and playback controls. Actual Steam Input/raw controller operation, Qt video auto-hide behavior, and live Immich streaming still require validation on the Xubuntu game center.
