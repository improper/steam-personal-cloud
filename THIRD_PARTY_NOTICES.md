# Third-party software

Steam Personal Cloud's application code and original documentation are proprietary. The licenses below apply only to the named third-party components; they do not license the application.

The compiled Linux client uses PySide6 and Shiboken, and Qt Core, GUI, Widgets, Network, DBus, OpenGL, QML/Quick, Multimedia, SVG, image formats, shader tools and desktop platform plugins. These Qt components are distributed under the GNU Lesser General Public License, version 3. Qt's FFmpeg libraries use LGPL version 2.1 or later. The release contains the applicable license texts, copyright notices, build configuration and a manifest of corresponding source archives. Qt components available only under GPL are excluded from the client.

The shared libraries are separate files in `/usr/lib/steam-personal-cloud`, including the PySide6 and Qt subdirectories. You may replace or modify these libraries with compatible builds. Reverse engineering for debugging modifications to these LGPL components is permitted. Nothing in the application's proprietary terms restricts rights granted by their licenses. Keep a backup before replacing libraries; a compatible ABI is required.

Download `steam-personal-cloud-third-party-sources.tar` from the same release as the binary. It contains the unmodified upstream Qt, PySide6/Shiboken and FFmpeg sources and SHA-256 manifest. Build instructions and configurations are included in those archives. PySide6 wheel builds are described in the PySide source repository's `coin` configuration. The packaged FFmpeg configuration is also recorded in `ffmpeg-build.txt`. The application loads the resulting shared libraries dynamically; replacing them does not require application source code.

Python uses the Python Software Foundation license and its included third-party notices. Pillow uses the MIT-CMU license and includes notices for bundled image codecs. Nuitka's generated runtime uses its Apache-2.0 license and runtime exception. ICU uses the Unicode license; its source and notices are included. Compiler-only dependencies are not application code. Complete notices are installed in `/usr/share/doc/steam-personal-cloud-client/`, including `licenses/` and `source-manifest.json`.

Operating-system libraries are supplied by Ubuntu and retain their respective licenses. Steam and Immich are separate products and are not bundled with this client. Steam is a trademark of Valve Corporation. This product is not affiliated with Valve or the Immich project.
