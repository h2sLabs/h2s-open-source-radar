# Third-party notices

H2S Open Source Radar source code is licensed under **Apache-2.0**. Dependencies
remain under their own licenses.

The versions below are the versions reviewed for the v0.1.0 Apple Silicon build.
The exact frozen set is recorded in `requirements-lock.txt`.

## Runtime

| Component | Reviewed version | License |
| --- | ---: | --- |
| PySide6 | 6.8.1 | LGPL-3.0 / GPL-3.0 / Qt Commercial |
| PySide6 Essentials | 6.8.1 | LGPL-3.0 / GPL-3.0 / Qt Commercial |
| PySide6 Addons | 6.8.1 | LGPL-3.0 / GPL-3.0 / Qt Commercial |
| Shiboken6 | 6.8.1 | LGPL-3.0 / GPL-3.0 / Qt Commercial |
| PyObjC Core | 12.1 | MIT |
| PyObjC Cocoa framework | 12.1 | MIT |
| Requests | 2.32.5 | Apache-2.0 |
| urllib3 | 2.8.0 | MIT |
| charset-normalizer | 3.5.2 | MIT |
| idna | 3.20 | BSD-3-Clause |
| certifi | 2026.7.22 | MPL-2.0 |

## Build tooling

| Component | Reviewed version | License |
| --- | ---: | --- |
| PyInstaller | 6.18.0 | GPL-2.0-or-later with PyInstaller's special application-distribution exception |
| PyInstaller hooks contrib | 2026.8 | Apache-2.0 / GPL-2.0 (see upstream package license) |
| Pillow | 12.3.0 | MIT-CMU |
| altgraph | 0.17.5 | MIT |
| macholib | 1.16.4 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |

## Qt / PySide6 note

Qt for Python (PySide6/Shiboken6) is available under LGPLv3/GPLv3 and commercial
licensing. This project uses the community package and does not modify Qt.

The repository's first public release is **source-first**. Before publishing a
prebuilt macOS binary, maintainers should re-check the exact packaged Qt modules,
include the applicable Qt/PySide6 and third-party license texts/notices, and
verify that the chosen packaging method continues to satisfy LGPL-3.0
requirements, including the user's ability to replace/relink LGPL-covered
libraries where required.

## Release rule

Whenever dependency versions change:

1. rebuild in a clean virtual environment;
2. run `pip check`;
3. regenerate `requirements-lock.txt`;
4. update this file;
5. repeat the binary-license review before attaching a packaged app to a public release.

No third-party dependency is relicensed by H2S Labs.
