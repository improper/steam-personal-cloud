# Changelog

## 0.3.0-beta.1

First compiled Linux beta of Steam Personal Cloud.

### Gallery

- Native fullscreen photo and video viewing in the Steam-launched application.
- Larger capture cards, high contrast text, clear focus, and persistent controller/key prompts.
- Filter switching, previous/next browsing, inline details, and saved playback settings.
- WebP decoding for Immich covers and previews; available local photos open without a preview request.

### Capture discovery and removal

- Include Steam's native screenshot originals alongside exported screenshots.
- Group JPEG originals and PNG exports by Steam capture identity.
- Keep local originals visible when their Immich copies have been trashed.
- Avoid re-uploading an already archived capture merely because another local copy is discovered.
- Validate local targets before removal, then move all matched local screenshot copies and thumbnails to Trash. Remote removal uses Immich Trash, and errors report possible partial completion.

### Backup and delivery

- Scoped device pairing, periodic background backup, and authenticated Immich playback.
- Server-side assembly of Steam recording fragments and title/date metadata.
- Compiled x86-64 Debian client with replaceable PySide6/Qt shared libraries, checksums and third-party notices.
- Customer installation and administrator deployment documentation.

### Known limitations

See the beta limitations in [README.md](README.md). This release is marked as a prerelease and is not a promise of complete support for every Steam recording format or controller.
