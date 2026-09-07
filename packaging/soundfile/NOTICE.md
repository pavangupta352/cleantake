# SoundFile and native audio libraries

CleanTake uses SoundFile 0.14.0 (BSD 3-Clause) and dynamically loads the
unmodified libsndfile 1.2.2 library from its platform wheel. That library
contains statically linked codec libraries. The applicable copyright notices
and license texts are included in this directory; the matching source archives,
build recipes and patches are published with the same CleanTake release.

| Component | macOS / Linux | Windows | License text |
| --- | --- | --- | --- |
| SoundFile | 0.14.0 | 0.14.0 | soundfile-0.14.0/LICENSE |
| libsndfile | 1.2.2 | 1.2.2 | libsndfile-1.2.2/COPYING |
| libFLAC | 1.4.3 | 1.4.3 | flac-1.4.3/COPYING.Xiph |
| libogg | 1.3.5 | 1.3.5 | libogg-1.3.5/COPYING or ogg-v1.3.5/COPYING |
| libvorbis | 1.3.7 | 1.3.7 | libvorbis-1.3.7/COPYING or vorbis-1.3.7/COPYING |
| Opus | 1.4 | 1.5.2 | opus-VERSION/COPYING and additional notices |
| mpg123 | 1.32.3 | 1.32.9 | mpg123-VERSION/COPYING |
| LAME | 3.100 | 3.100 | lame-3.100/COPYING and LICENSE |

libsndfile and mpg123 use the GNU Lesser General Public License, version 2.1
or later. LAME's COPYING and LICENSE describe its LGPL terms. The linked
libFLAC, Ogg, Vorbis and Opus libraries use their included permissive licenses.
The complete FLAC source archive also contains separately licensed programs
and documentation; their license texts are preserved alongside COPYING.Xiph.
libsndfile's incorporated GSM 6.10 implementation retains its separate notice
in `libsndfile-1.2.2/src/GSM610/COPYRIGHT`.

These libraries are provided without warranty, as described in their licenses.
You may modify and rebuild them and replace the shared libsndfile library in
CleanTake. CleanTake imposes no restriction on reverse engineering for debugging
those modifications. Rebuild and replacement instructions are in the
corresponding source package's README.md, also available at
https://github.com/pavangupta352/cleantake/tree/main/packaging/soundfile.

The source manifest identifies the exact platform wheel and native library by
SHA-256, and lists every distributed source archive. It does not claim identical
compiler output across different toolchains.
