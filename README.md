# Sailplay

Wireless CarPlay phone/source implementation for SailfishOS, tested on Xiaomi Pad 5 (nabu) with a Toyota 2023 HSAE head unit.

## Current status

Version 0.1.0-17 includes Bluetooth RFCOMM/iAP2, accessory certificate pinning and challenge verification, ConnMan Wi-Fi handover, encrypted AirPlay control/video/audio, a virtual 1920x720 compositor and reverse touch input.

- Continuous projection, application launching and touch have been confirmed on the head unit.
- A standalone Sailplay tablet app selects the applications shown on the car display; changes save automatically.
- The car launcher has network/battery indicators, a recent-app dock and horizontally paginated application grids.
- Old RFCOMM channels are retired on reconnection; failed profile connections retry while Bluetooth is connected. Active media sessions are protected from unnecessary reconnect attempts.
- The service is configured for boot startup. A full cold-boot connection cycle has not yet been verified.
- Audio packet transmission and capture are implemented; audible head-unit output remains unverified.
- Return to the original head-unit UI closes only the screen stream, keeping audio and control connected. Native UI switching was confirmed on the head unit; its requestUI event also re-established video. The packaged return tile, head-unit CarPlay re-entry and restored touch were confirmed on the tested head unit.

## Source layout

- `carplay_proto/`: protocol codecs, authentication, AirPlay transport, video, audio and HID input.
- `scripts/`: runtime Bluetooth/Wi-Fi services, capture and build/deployment helpers.
- `display-source/`: Qt Quick car launcher, tablet settings app, compositor and x264 capture source, derived from Sailife/Imira.
- `rpm/`: standalone RPM packaging and systemd service.
- `tests/`: protocol and connection-lifecycle tests.

## Tests

```sh
python3 -m pip install pytest cryptography
python3 -m pytest
python3 -m unittest discover -s tests -p '*unittest.py'
```

The device uses system OpenSSL and PulseAudio; development tests use Python cryptography. The latest focused unittest run passed 32 tests.

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

Earlier USB transport work is retained in [USB_HISTORY.md](USB_HISTORY.md). It does not describe the current wireless transport.

License: GPL-3.0-or-later; see [LICENSE](LICENSE).
