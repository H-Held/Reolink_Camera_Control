# Third-party licenses

Reolink_Camera_Control is licensed under the GNU General Public License v3.0
or later (see `LICENSE`). All dependencies use licenses that are compatible
with GPL-3.0.

| Component | Use | License | GPL-3.0 compatible |
|-----------|-----|---------|--------------------|
| requests  | runtime dependency | Apache-2.0 | Yes (Apache-2.0 is compatible with GPLv3, not with GPLv2) |
| urllib3   | installed with requests | MIT | Yes |
| pytest    | development only | MIT | Yes |
| ffmpeg    | optional external program, called as a separate process for MP3/AAC/OGG/FLAC input | LGPL-2.1+ / GPL-2.0+ depending on build | Not linked or distributed; invoked through `subprocess` only |

This project is not affiliated with or endorsed by Reolink. "Reolink" is a
trademark of its respective owner.
