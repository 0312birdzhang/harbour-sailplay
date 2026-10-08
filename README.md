# Sailplay

Wireless CarPlay phone/source implementation for SailfishOS, tested on Xiaomi Pad 5 (nabu) with a Toyota 2023 HSAE head unit.

## Current status

Version 0.1.0-27 includes Bluetooth RFCOMM/iAP2, accessory certificate pinning and challenge verification, ConnMan Wi-Fi handover, encrypted AirPlay control/video/audio, a virtual 1920x720 compositor and reverse touch input.

- Continuous projection, application launching and touch have been confirmed on the head unit.
- A standalone Sailplay tablet app selects the applications shown on the car display; changes save automatically.
- The car launcher has network/battery indicators, a recent-app dock and horizontally paginated application grids. Devices with ofono Settings/EmptyConfig=true hide cellular indicators; battery readings prefer sysfs, with Statefs/UPower fallbacks.
- Bluetooth adapter selection follows BlueZ-exported adapters, including hci1 phones; advertising, monitoring and target-device paths use the selected controller.
- The management app shows live systemd state and offers start/stop plus Connect / reconnect to car with error reporting. Reconnect resets old Sailplay sessions and actively connects the configured Bluetooth head unit, triggering iAP2/Wi-Fi/AirPlay again. Its authorization is restricted to Sailplay units. Bluetooth power changes rebuild the phone profile and advertisement; silent iAP2 handshakes time out for retry.
- Old RFCOMM channels are retired on reconnection; failed profile connections retry while Bluetooth is connected. Active media sessions are protected from unnecessary reconnect attempts.
- The service is configured for boot startup. A full cold-boot connection cycle has not yet been verified.
- Audio packet transmission and capture are implemented. A dedicated nopolicy capture group prevents Sailfish audio policy from selecting microphone input; the helper also verifies its private monitor. Audible head-unit output remains unverified.
- Return to the original head-unit UI closes only the screen stream, keeping audio and control connected. Native UI switching was confirmed on the head unit; its requestUI event also re-established video. The packaged return tile, head-unit CarPlay re-entry and restored touch were confirmed on the tested head unit.

## Source layout

Version 27 fixes management-app startup on Sailfish Silica by handling resolution/fps selection on MenuItem clicks instead of the unsupported ComboBox activated signal. QML loading was verified on JollaPhone2026.

Version 26 adds management-app resolution presets (1920x720, 1600x600, 1280x480) and 30/60fps selection. Settings apply on reconnect to compositor output, capture, H.264 configuration and touch mapping. Default remains 1920x720 at 30fps; alternative modes require head-unit validation.

Version 25 uses the current Bluetooth adapter Alias (or Name) for both iAP2 and AirPlay device names instead of the fixed SailfishOS Sailplay label. A name change is picked up by the next connection.

Version 24 reads localized desktop-entry application names (for example Name[zh_CN] and Name[zh]) with language fallback. Only the Desktop Entry section is read; action labels cannot overwrite the application name. Sailfish translation catalogs remain supported.

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

The device uses system OpenSSL and PulseAudio; development tests use Python cryptography. The latest focused unittest run passed 53 tests. Version 22 adds bounded discovery and a single Wi-Fi power refresh when the HU is visible to supplicant but absent from ConnMan; this recovery still requires device validation.

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
