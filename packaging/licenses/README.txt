Third-party notices for the model-free Triloa Windows portable build.

The Python packages listed in DEPENDENCIES.json keep their own licenses.
METADATA.txt and the available LICENSE/NOTICE files are retained in each
package's subdirectory. Python's license includes its bundled components.
qt-source-notices includes third-party copyright/license files from the
corresponding Qt 6.9.2 qtbase/qtsvg source trees; SOURCES.json records each
file's pinned upstream URL and SHA256. Additional notices may concern
components not used by this application's Qt build.

Qt and PySide6 are dynamically linked. Their DLLs are separate files in
_internal and can be replaced with compatible builds. Triloa does not
restrict reverse engineering for debugging modifications to LGPL libraries.
Triloa has not modified Qt, PySide6, Python, or the Python dependencies.

Corresponding upstream source for the included Qt/PySide6 6.9.2 binaries:
https://download.qt.io/archive/qt/6.9/6.9.2/single/
https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.9.2-src/
Source, build instructions and licensing:
https://doc.qt.io/qtforpython-6/licenses.html
https://doc.qt.io/qtforpython-6/building_from_source/index.html

Unmodified LGPL native dependencies supplied by the build environment:
libiconv 1.16 source: https://ftp.gnu.org/pub/gnu/libiconv/libiconv-1.16.tar.gz
GLib 2.84.4 source: https://download.gnome.org/sources/glib/2.84/glib-2.84.4.tar.xz
These DLLs are also separate replaceable files in _internal; the same
permission to debug modifications applies. Their license texts are in native/.

The optional CPU llama.cpp runtime uses the MIT license in llama.cpp-LICENSE.
Its source revision is b10964:
https://github.com/ggml-org/llama.cpp/tree/b10964
The included OpenMP runtime retains LICENSE-LLVM-OpenMP in runtime/llama.

No translation, OCR, sentence-boundary, VAD or speech-recognition model
weights are included. Downloaded models retain the upstream licenses
documented in THIRD_PARTY_NOTICES.md.
