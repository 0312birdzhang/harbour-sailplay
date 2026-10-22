# Sailplay

Wireless CarPlay phone/source implementation for SailfishOS, tested on Xiaomi Pad 5 (nabu) and JollaPhone2026 with Toyota HSAE head units.

Sailplay connects over Bluetooth and Wi-Fi to project a dedicated car interface,
with application launching, reverse touch input, music playback controls and a
map/weather/music dashboard. The Sailplay phone app manages the service, car
connection, visible applications and display settings.

## Documentation

- [Development status and source layout](DEVELOPMENT.md): implementation status, repository structure and historical version notes.
- [Wireless implementation notes](WIRELESS.md): connection, media and display lifecycle details.
- [Instrument navigation](NAVIGATION.md): receiver fields, implementation stages and validation limits.
- [ConnMan fix](connman-patches/README.md): the separate, version-restricted ConnMan patch.
- [USB history](USB_HISTORY.md): earlier USB transport work.

## Build and device configuration

The RPM scripts require the SailfishOS aarch64 SDK, x264 source/static library and Qt build dependencies. SDK paths in `rpm/build-arm.sh` and the WSL wrappers must be adapted to your checkout.

Accessory certificate pins are local, device-specific inputs and are not published. Save an observed accessory certificate locally and generate the verification pin:

```sh
python3 scripts/export-accessory-pin.py accessory.der diagnostics/corolla-accessory-key.json
```

The current RPM recipe expects that local pin filename. Configure the target BlueZ device path in `rpm/sailplay.service` for your own paired head unit. Do not reuse another vehicle's certificate pin.

Run the SDK build/package wrapper, then install the resulting RPM. The service starts at boot after installation; configure the device path before starting it on a different head unit.

```sh
export SAILPLAY_HOST=your-tablet-address
export SSHPASS=your-device-password
sh scripts/install-package-from-wsl.sh
```

Root installation uses an interactive `devel-su` password prompt. Device credentials, pairing identities, logs, captures and build outputs are excluded from Git.

### Local-only vehicle Wi-Fi

Wireless CarPlay does not require Internet access, DNS resolution or a SIM card. ConnMan `ready` is sufficient; `online` is not required. If Connect reports an error (including `NoCarrier`), Sailplay checks the actual supplicant association and probes the iAP2-provided CarPlay endpoint bound to that Wi-Fi interface. A verified local connection continues into AirPlay; stale IPs, association to another SSID and unreachable endpoints retain the normal retry path.

## Tests

Run the protocol tests on Linux:

```sh
python3 -m pip install pytest cryptography
python3 -m pytest
python3 -m unittest discover -s tests -p '*unittest.py'
```

The device uses system OpenSSL and PulseAudio; development tests use Python
cryptography. Live display integration checks and device-specific requirements
are described in [WIRELESS.md](WIRELESS.md).

## Acknowledgements

Sailplay builds on and learns from the following projects:

- [Sailife](https://github.com/0312birdzhang/harbour-sailife): the original car launcher, virtual-display and capture pipeline.
- [Imira](https://github.com/JimKnopfIoT/harbour-imira): virtual compositor, screen capture and convergence implementation; also a reference for PulseAudio latency handling.
- [sailfish-weather](https://github.com/sailfishos/sailfish-weather): weather components and the Events view weather integration reference.
- [zzmusic](https://github.com/ZeroX-S/zzmusic): a reference for music artwork handling.
- [DiPlay](https://github.com/shihabal3amri/DiPlay): a CarPlay receiver used for interoperability testing and audio/input investigation.
- [Qt](https://www.qt.io/) and Sailfish Silica / Amber.Mpris: the application UI, Wayland compositor and music controls.
- [x264](https://www.videolan.org/developers/x264.html): software H.264 video encoding.
- [FFmpeg](https://ffmpeg.org/): AAC audio encoding.
- [PulseAudio](https://www.freedesktop.org/wiki/Software/PulseAudio/): playback routing and monitor capture.
- [BlueZ](https://www.bluez.org/) and [ConnMan](https://git.kernel.org/pub/scm/network/connman/connman.git/): Bluetooth and Wi-Fi integration.
- [OpenSSL](https://www.openssl.org/) and [cryptography](https://cryptography.io/): runtime cryptographic operations and development tests.

## License

GPL-3.0-or-later; see [LICENSE](LICENSE). Upstream components retain their respective licenses and copyright notices.
