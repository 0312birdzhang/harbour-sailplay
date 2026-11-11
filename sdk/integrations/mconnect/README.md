# Native Mconnect lifecycle integration

This patch targets the existing native C++/Silica 1.6.0-51 migration tree in
`flutter-sailfishos/apps/mconnect`. `baseline.json` identifies each changed
source file before and after integration. The integration produces release 55.

The native migration tree contains earlier local work beyond the upstream
checkout at `82f09c4`. Use the native checkout matching the recorded hashes.
The patch and SDK overlay are published in Sailplay's repository so the
lifecycle change can be reviewed independently.

The complete native application includes the C++ core, Silica/QML interface,
regression tests, RPM inputs and bundled SDK source. Release 55 is published
in the application's standalone repository.
[Native Mconnect source](https://github.com/0312birdzhang/harbour-mconnect)

## Applying

Run the script from a complete Sailplay checkout. Supply the path to the native
`flutter-sailfishos` checkout.

```sh
python3 sdk/integrations/mconnect/apply.py /path/to/flutter-sailfishos --check
python3 sdk/integrations/mconnect/apply.py /path/to/flutter-sailfishos
```

The script validates the source and patch hashes and copies the Qt provider,
canonical App1/Session1/Navigation1/Content1 XML, content helpers and SDK license
into `elinux/sailplay-sdk`.
Repeating the command verifies the applied state. Differing source or overlay
files stop application. Git prepares the validated patch in an isolated tree
with explicit LF settings. The installer checks every prepared hash, rechecks
the source and writes the native files and eleven SDK records atomically.
Rollback after a failure restores this invocation's written files when their
bytes still match the integration output. Concurrently created or modified
files retain their contents.

The application CMake build uses this overlay by default. An external SDK tree
can be selected with `MCONNECT_SAILPLAY_SDK_DIR`, pointing at its `sdk/qt` folder.
The resulting package declares its MIT and GPLv3+ components and includes both
licenses.

## Runtime behavior

The existing application identity owns App1 and caller-owned Session1 objects.
SDK state contains a typed `media` dictionary with the native player snapshot.
The `content` capability projects the existing playback queue, queue search,
pagination and song selection. Catalog versions change with queue updates,
independently of playback progress. A selected item checks its current index
and song identity before calling the native player's selection operation.
Each host presentation retains its own browsing history and query results.
Playback commands use MPRIS. The SDK provider rejects unavailable actions with
the v1 `NotSupported` error.

The Sailjail profile permits directed SDK state, completion, guidance, content and
Session1 property-change members to the clients' temporary
`org.sailplay.Client.*` names. The Qt and Python clients acquire their name
before activating the backend. Sessions
retain the caller's unique bus owner for ownership checks and signal delivery.

Direct and D-Bus startup supply Wayland and Maliit defaults before Qt loads its
platform and input plugins.

Closing the phone window releases the phone QML tree and suspends its polling.
Show and MPRIS Raise attach a new phone presentation to the existing core.
Closing without a car session exits through normal runtime shutdown, including
during playback and other work. Hidden car sessions keep their lease after the
phone closes. Session owner loss removes those leases.

After serving a car, the core exits when its last lease ends if the phone view
is closed or has never been opened. A phone view still open at disconnect
retains the application. Initial background startup keeps its ten-second idle
grace and work check until its first session arrives. The exit callback checks
current activity again. Explicit pause retains paused playback while a car
lease exists.

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
