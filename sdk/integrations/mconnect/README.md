# Native Mconnect lifecycle integration

This patch targets the existing native C++/Silica 1.6.0-51 migration tree in
`flutter-sailfishos/apps/mconnect`. `baseline.json` identifies each changed
source file before and after integration. The integration produces release 52.

The native migration tree contains earlier local work beyond the upstream
checkout at `82f09c4`. Use the native checkout matching the recorded hashes.
The patch and SDK overlay are published in Sailplay's repository so the
lifecycle change can be reviewed independently.

## Applying

Run the script from a complete Sailplay checkout. Supply the path to the native
`flutter-sailfishos` checkout.

```sh
python3 sdk/integrations/mconnect/apply.py /path/to/flutter-sailfishos --check
python3 sdk/integrations/mconnect/apply.py /path/to/flutter-sailfishos
```

The script validates the source and patch hashes and copies the Qt provider,
canonical App1/Session1 XML and SDK license into `elinux/sailplay-sdk`. Repeating
the command verifies the applied state. Differing source or overlay files stop
application. Git applies the validated patch bytes from memory. Source checks
run again before application. Rollback after a failure restores files whose
bytes still match the integration output and preserves concurrently modified
files.

The application CMake build uses this overlay by default. An external SDK tree
can be selected with `MCONNECT_SAILPLAY_SDK_DIR`, pointing at its `sdk/qt` folder.
The resulting package declares its MIT and GPLv3+ components and includes both
licenses.

## Runtime behavior

The existing application identity owns App1 and caller-owned Session1 objects.
SDK state contains a typed `media` dictionary with the native player snapshot.
Playback commands use MPRIS. The SDK provider rejects unavailable actions with
the v1 `NotSupported` error.

Direct and D-Bus startup supply Wayland and Maliit defaults before Qt loads its
platform and input plugins.

Closing the phone window releases the phone QML tree and suspends its polling.
Show and MPRIS Raise attach a new phone presentation to the existing core.
Playback, download queues and retries, login calls, scans, lyric loading and
accepted core/bridge requests retain the core. Hidden car sessions keep their
lease. Session owner loss removes those leases.

The core exits after ten idle seconds once the phone presentation, leases and
work have ended. The exit callback checks current activity again. Explicit
pause retains paused playback while a car lease exists.

## Validation

Enable `MCONNECT_BUILD_TESTS` to build the native regression suites. The added
presentation and lifecycle suites exercise actual Qt close events, deferred
QML release, reopen races, hidden sessions, ongoing playback and accepted work,
and activity arriving before the idle callback. The existing QML validator
also closes and rebuilds the installed Silica application tree twice with the
same isolated core fixture.

Sailplay's Qt SDK fixture exercises canonical signatures, property ownership,
directed state/property signals, limits, owner loss, media activity and backend
replacement. Its source is `tests/sdk_provider_test.pro`. Device installation
and remaining phone/car acceptance are recorded in `todo.md`.
