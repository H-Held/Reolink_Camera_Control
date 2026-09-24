# Third-party licenses

Reolink_Camera_Control is licensed under the GNU General Public License v3.0
or later (see `LICENSE`). All dependencies use licenses that are compatible
with GPL-3.0.

| Component | Use | License | GPL-3.0 compatible |
|-----------|-----|---------|--------------------|
| requests  | runtime dependency | Apache-2.0 | Yes (Apache-2.0 is compatible with GPLv3, not with GPLv2) |
| reolink-aio | runtime dependency (Baichuan login and transport for audio push) | MIT | Yes |
| urllib3   | installed with requests | MIT | Yes |
| aiohttp | installed with reolink-aio | Apache-2.0 and MIT | Yes |
| pycryptodomex | installed with reolink-aio | BSD-2-Clause / Public Domain | Yes |
| orjson | installed with reolink-aio | MPL-2.0 and (Apache-2.0 or MIT) | Yes (MPL-2.0 permits combination with GPL-3.0) |
| aiortsp | installed with reolink-aio | LGPL-3.0-or-later | Yes (LGPL-3.0 is compatible with GPL-3.0) |
| pytest    | development only | MIT | Yes |
| ffmpeg    | optional external program, called as a separate process for MP3/AAC/OGG/FLAC input | LGPL-2.1+ / GPL-2.0+ depending on build | Not linked or distributed; invoked through `subprocess` only |

This project is not affiliated with or endorsed by Reolink. "Reolink" is a
trademark of its respective owner.

The talk protocol message flow and ADPCM packet layout were taken from the
publicly readable source of [neolink](https://github.com/QuantumEntangledAndy/neolink)
(GPL-3.0) as a format reference. No neolink code is included or linked.
