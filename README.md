# Sailplay

Wireless CarPlay phone/source implementation for SailfishOS, tested on Xiaomi Pad 5 (nabu) with a Toyota 2023 HSAE head unit.

## Current status

Version 0.1.0-53 includes Bluetooth RFCOMM/iAP2, accessory certificate pinning and challenge verification, ConnMan Wi-Fi handover, encrypted AirPlay control/video/audio, a virtual 1920x720 compositor and reverse touch input.

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

Version 53 scans again when a saved HU profile has no signal, instead of treating its cached presence as AP availability. WPA2 reselection allows a bounded 15-second grace period for the retired attempt's failure and waits for the new connection to become ready. Network sampling now starts before association, retaining supplicant state/status evidence for failed connections. October 10 logs showed repeated NoCarrier, then invalid-key immediately after intentional WPA2 reselection; successful in-car connection after this change remains unverified.

Version 52 treats dashboard app surfaces as previews: map taps open the full map, music title/artwork/background taps open the configured music app, and transport buttons and seeking retain their own input. MPRIS artwork URLs use a bounded local cache; local MP3 ID3 and FLAC embedded artwork provide a fallback when the player exports no artwork URL. Tracks without either source retain the text-only layout. Phone input injection verified map restoration and music launching; in-car verification remains pending.

Version 51 persists capture-helper diagnostics in the private, rotating audio-capture log. Ten-second snapshots include playback routing, cork/mute/channel volume, capture routing and cast sink/monitor state, excluding song titles and filenames. The latest silent session sent zero PCM throughout; an offline native Media playback test captured nonzero audio. The intermittent silence cause remains unverified.

Version 50 preserves playback stream volumes during casting and applies bounded, saturating gain only to outgoing PCM. Hardware channel volumes are saved for recovery and restored before unmuting; legacy records without volumes use a conservative 25 percent fallback. Multiple mixed streams use the loudest active media stream for compensation.

Version 47 adds elapsed time, duration and seeking below the dashboard lock-screen controls. Version 46 supplies a private Jolla media QML compatibility import for Sailplay-launched players, keeping MPRIS controls available when the player panel is hidden. System QML files remain unchanged.

Version 43 replaces the dashboard music application surface with the actual Sailfish.Media lock-screen MPRIS controls. The configured music application remains an explicit launch shortcut; only the map occupies a dashboard application surface.

Version 42 subscribes to PulseAudio sink-input events to route new playback without waiting for the one-second maintenance interval. The private cast sink becomes the session default and hardware Droid outputs are muted during casting to prevent startup leakage from policy-selected device streams. Original hardware mute/default states are saved before mutation, restored on teardown, and recovered through the service stop hook or next startup after an abnormal helper exit. This is local audio routing integration; complete CarPlay feature conformance is not claimed. All 68 tests passed; live validation follows.

Version 41 moves synchronous pactl routing/volume maintenance to a separate worker so it cannot block the PulseAudio capture loop. Commands have bounded timeouts and teardown joins the worker before restoring volume and routes. RTP diagnostics now report capture/send gaps, pacing resets and buffered frames. DiPlay reported receiver underruns and up to 447 ms gaps without decrypt failures; cause and improvement require live gap correlation. Live version 41 measured steady sender gaps about 15-21 ms with no pacing resets after startup, while DiPlay still showed roughly 400-487 ms receive gaps and playback underruns. Temporarily disabling sender Wi-Fi power save did not eliminate receiver gaps; the original power-save setting was restored. An OEM ownership diagnostic at 20:00:27 caused DiPlay to reset control and audio, and Sailplay automatically reconnected; that test did not isolate video bandwidth. Its feedback encoder also throws ArrayIndexOutOfBoundsException in BplistCodec.encodeUnsignedInt, producing feedback status 500. The 19:50:28 service restart coincided with the version 40 upgrade.

Version 40 saves each playback stream channel volume, normalizes routed playback to 0 dB while casting, and restores the original values on teardown. Live diagnosis found the Media stream at 23722/65536 (-26.48 dB), while the capture monitor and null sink were at unity. Setting the stream to unity restored normal audible volume, confirmed by the user. No extra PCM amplification is applied.

Version 39 disconnects the authenticated DiPlay peer A2DP source when starting CarPlay audio. The Android receiver otherwise routed decoded audio back to Jolla Phone (2026). Receiver logs confirmed successful decryption and Android A2DP routing; disconnecting only this profile switched output to the receiver speaker, and audible playback was confirmed by the user.

Version 38 decodes repeated HID contact fields independently and selects an active contact for mouse injection, rather than allowing the second inactive contact to overwrite the first. DiPlay advertises two touch contacts. Bounded initial report/UUID diagnostics help verify actual input. The two-contact regression and 65 protocol tests passed; physical touch validation is pending.

Version 37 fixes receivers exposing public AirPlay /info with status 200: pairing and initial SETUP now run before media initialization instead of using uninitialized session variables. Paired receivers with a verified accessory pin can be selected even without an iAP2 SDP UUID; successful inbound authentication remembers their target. DiPlay logs identified both issues. All 64 protocol tests passed; live validation is in progress.

Version 36 adds startup adapter/device snapshots, BlueZ property transitions, periodic connection checkpoints and full profile errors. Wi-Fi/AirPlay and restoration output also persist across reboot, alongside Bluetooth logs. Each component retains six files of up to 4 MiB each under /var/lib/sailplay/logs (private directory 0700); credentials and packet bodies remain excluded. Startup records PID and boot ID. Existing journal and temporary Wi-Fi logs remain available.

Version 35 retains private, bounded Bluetooth advertisement/session and reconnect logs under /var/lib/sailplay/logs, independent of journal rotation. LEVIN investigation currently confirms correct phone EIR and target selection, but a fresh connection failed with br-connection-page-timeout before iAP2; its earlier missing-icon cause remains unverified.

Version 34 adds a dock dashboard button and configurable map/music application selectors in the management app. The compositor displays the selected native applications in independent 65/35 clipped viewports, requests panel-sized surfaces and routes touch to each panel. Home restores the app grid; opening a normal app restores the full content area. Application identity has a per-launch PID/start-time fallback when process environment cannot be read. Dashboard settings save under ~/.config/sailplay/dashboard.ini and update an open dashboard automatically.

On JollaPhone2026, a captured virtual-screen frame confirmed Pure Maps and Jolla Media simultaneously visible in the two panels (1126x640 and 606x640 at 1920x720). The management page loaded without QML errors, and all 61 existing protocol tests passed. Dashboard behavior on the head unit, playback and the complete home/dashboard touch cycle still require verification.

Version 33 uses Sailfish Silica SlideshowView for home-page drag and animated snapping. It removes the custom swipe handlers introduced in version 32; application tiles use normal MouseArea clicks and allow the slideshow to take over drag gestures. Page dots change the slideshow currentIndex. Version 33 was installed on JollaPhone2026; projection resumed, QML loaded without errors and capture remained about 29.5fps.

Version 32 removes home-page drag, inertia and snap animations. Horizontal swipes switch one page immediately on release; tapping page indicators also jumps immediately. Swipe gestures over application tiles do not launch the application.

Version 31 reads AirPlay display widthPixels, heightPixels and maxFPS. Resolution choices are native size, 5/6 and 2/3 encoder scaling, recalculated per head unit; they are hidden until display capabilities are known. Frame rate never exceeds the advertised maximum (HIGHLANDER reports 1920x720, 30fps). The software encoder and same-size RGBA-to-YUV conversion use AArch64 NEON, keep only the latest queued frame, avoid additional capture-interval delay after conversion and log measured encoding throughput. On-phone conversion checks matched the scalar implementation in 16 cases, including inverted frames, padded stride and I420/NV12 output.

The shm reader retries a writer-busy sequence after 1ms instead of skipping a complete frame interval. On JollaPhone2026 with HIGHLANDER at native 1920x720, final capture throughput was 29.3–29.5fps and transmitted video about 30fps, up from about 10fps before these changes. Management QML loaded on-device without QML errors. The user confirmed clearly smoother swiping on the head unit.

Version 30 re-selects the head-unit Wi-Fi network after applying WPA2-PSK. ConnMan had already started SAE association before the NetworkAdded callback could change its configuration, causing invalid-key on HIGHLANDER. The scoped re-selection connected JollaPhone2026 and sustained projection for more than six minutes; full cold-boot recovery remains to be verified.

Version 28 prefers a currently connected paired CarPlay accessory for automatic and manual reconnect. Accessory keys are pinned per Bluetooth device after a successful first challenge; a changed certificate is rejected. First-use pinning proves key possession, not Apple CA trust. Startup also restores Bluetooth connectability where supported.

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

The device uses system OpenSSL and PulseAudio; development tests use Python cryptography. The latest focused unittest run passed 61 tests. Version 22 adds bounded discovery and a single Wi-Fi power refresh when the HU is visible to supplicant but absent from ConnMan; this recovery still requires device validation.

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
