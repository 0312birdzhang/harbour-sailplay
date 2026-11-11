# Organic Maps shared navigation backend

Organic Maps owns one framework, routing session, location source, voice queue
and writable application state. The full Silica phone presentation attaches to
that backend through a viewport. Sailplay presents the same route through its
compact and expanded navigation templates.
The templates also display the backend's map pixels through the optional
`navigation-map` capability. Carui paints the canvas inside its existing Imira
window and forwards map input through the caller-owned SDK session.

## Source baseline

The patch targets the Sailfish source at
`abcdd8c3d518973d74d1d967c1f6d6ba34e500bf`. `baseline.json` records the patch
digest, source commit and before/after hashes of every changed file. The
downstream repository also contains the integrated source.
The current integrated source is `8056adcc1a457dd980699b8332437e19b6d45da5`.
[Organic Maps Sailfish source](https://github.com/0312birdzhang/organicmaps-sailfish/tree/sailfish)

Apply `lifecycle.patch` from a clean checkout at that baseline. Use a native Git
installation to check the complete source and submodules.

```sh
cd /path/to/organicmaps-sailfish
test "$(git rev-parse HEAD)" = abcdd8c3d518973d74d1d967c1f6d6ba34e500bf
test -z "$(git status --porcelain)"
git -c core.autocrlf=false apply --check /path/to/harbour-sailplay/sdk/integrations/organicmaps/lifecycle.patch
git -c core.autocrlf=false apply /path/to/harbour-sailplay/sdk/integrations/organicmaps/lifecycle.patch
```

## Building

Enable the SDK integration inside the Sailfish SDK target. The SDK directory
must be visible within that build environment.

```sh
cmake -S . -B build \
  -DSAILFISH=ON -DSAILFISH_HARBOUR=OFF -DBUILD_TESTING=OFF \
  -DSAILPLAY=ON \
  -DSAILPLAY_SDK_QT_DIR=/path/to/harbour-sailplay/sdk/qt
cmake --build build --target organicmaps_sailfish
```

The RPM spec accepts `--with sailplay` and a `sailplay_sdk_qt_dir` macro for an
external source SDK. Its installed SDK default requires Sailplay 0.1.1-64 or
newer. The SDK v1 Qt provider and Navigation1 XML are embedded in the map
library.
The integrated RPM declares its Apache-2.0 and GPL-3.0-or-later components and
installs the SDK notice alongside the map application's existing notices.

## Runtime behavior

The existing `app.organicmaps.organicmaps` identity exports App1 at
`/org/sailplay/v1/App`. Caller-owned sessions export Session1 and Navigation1.
The desktop entry declares a template presentation and the `navigation` and
`navigation-map` capabilities. Sailjail background activation launches
`organicmaps --background`.
The application profile permits the four directed SDK signal members to
temporary `org.sailplay.Client.*` names owned by the Qt and Python clients.
These include the standard `PropertiesChanged` member for Session1 `Active`.
Each session retains its caller's unique bus owner for ownership checks and
signal delivery.

The existing inbox at `/app/organicmaps` accepts `Show`, `Close` and `openUrl`.
Show and launcher activation rebuild or raise the phone window over the
existing core. A window Close event releases its QML tree and view. Active car
canvas requests retain offscreen map rendering. The configured phone QQmlEngine stays with the backend across view
reloads so asynchronous Silica component callbacks retain their execution
engine.
The renderer serializes the first current-context binding of its two offscreen
surfaces and waits for both before continuing, covering EGL bridges whose
fallback-window mapping table needs serialized surface creation.
Location fixes, routing, recording statistics, notifications and accepted
SDK actions continue in the backend.

Hidden car sessions retain their lease. Caller loss releases those sessions.
The backend exits after ten idle seconds once its phone presentation, leases
and work have ended. The deadline checks current activity again. Outstanding
saved-route loads retain the backend and reject restoration after a newer
route edit or explicit stop.

`navigation.stop` closes the authoritative route and completes asynchronously.
The guidance adapter converts native driving and walking maneuver values,
distance units and Unicode text to the typed Navigation1 model. Driving side
uses the existing legacy inference, defaulting to `right` and selecting `left`
for the native `UTurnRight` maneuver. Complete country-specific left-driving
coverage remains open.

## Map canvas actions

The extension uses Session1 `Invoke` and its directed `RequestFinished`
completion. Existing providers with only `navigation` continue to use guidance
cards. A map frame result stays outside the revisioned navigation state.

| Action | Parameters | Result |
|---|---|---|
| `navigation.map.frame` | `width` and `height`, signed or unsigned 32-bit integers from 64 to 1920 | JPEG `image` as a byte array, integer `width` and `height`, and a `state` map |
| `navigation.map.touch` | `phase` of `press`, `move`, `release` or `cancel`, plus double `x` and `y` from 0 to 1 | Empty completion |
| `navigation.map.control` | String `command` of `zoom-in`, `zoom-out`, `position`, `route-to-place` or `start` | Empty completion |

Frames have a maximum dimension of 1920 pixels and an encoded limit of 4 MiB.
Carui requests at most one frame at a time, every 200 milliseconds while its
map presentation is active. It requests a maximum dimension of 1280 pixels,
preserves the delivered aspect ratio and excludes letterbox margins from
input. Move events are coalesced while an input request is pending. Hiding the
presentation cancels its gesture and pauses frame requests while retaining the
navigation lease. Backend loss clears the displayed image.

Organic Maps captures its existing Drape texture with a shared OpenGL context.
When the phone window is closed, an unshown Qt window hosts that same map item.
After 2.5 seconds without frame requests, the backend releases the car rendering
resources. The session and active route retain their existing lifecycle rules.
Phone reopening attaches the phone map to the same framework and viewport.
With the phone map open, the car receives that map viewport. Panning and zooming
affect the shared map view on both presentations.

Selecting a place supports route planning from the car. Starting a route uses
the existing native readiness checks and requires the navigation disclaimer
to have been accepted on the phone. Route stop uses `navigation.stop`.
The map backend keeps its current Sailjail service permissions. The canvas
uses carui's compositor and input access. A separately sandboxed custom renderer
remains an optional milestone in `todo.md`.

## Validation

The public viewport/model probe covers persistent QObject ownership, repeated
page destruction/recreation, geometry, all native maneuver values, four
distance units and Unicode bounds. The core map tests cover headless location,
headless route-follow callbacks and cancelled saved-route restoration.

The test-only CMake hook also builds `sailplay_map_lifecycle` from the production
Sailfish bridge. Transfer its thin launcher together with
`libsailplay_map_lifecycle.so` in the same directory. Run it with an isolated profile under
`/tmp/sailplay-map-device.*`, a copied offline map, installed resources and the
installed or candidate QML directory. It builds a real offline route and
injects simulated fixes through the backend's location path.

```sh
cmake -S . -B build \
  -DSAILFISH=ON -DSAILFISH_HARBOUR=OFF -DBUILD_TESTING=OFF \
  -DSAILPLAY=ON -DSAILPLAY_SDK_QT_DIR=/path/to/harbour-sailplay/sdk/qt \
  -DCMAKE_PROJECT_INCLUDE=/path/to/harbour-sailplay/tests/map_core_test_hook.cmake
cmake --build build --target sailplay_core_position sailplay_core_routes \
  sailplay_core_location sailplay_map_lifecycle
```

The fixture verifies full phone QML, Close handling, released phone views,
retained engine identity, repeated renderer release/recreation, route progress
and recording statistics while the phone is closed, saved recordings and
explicit stop. Use separate temporary
configuration, data and cache directories for each run and clean its exact
created files under identity and content guards. Device lifecycle and
physical phone/vehicle acceptance are recorded separately in `todo.md`.

The lifecycle fixture also decodes backend map pixels, checks image diversity,
reopens and closes the phone while retaining the canvas, sends a car gesture
and verifies idle rendering-resource release.
`tests/navigation_map_canvas_probe.pro` builds the host-side fixture for
JPEG validation, nested state, aspect-fit painting, normalized input, hidden
leases, retry and owner loss. Passing the carui QML directory as its optional
argument also constructs the production navigation card at 1920x720,
1280x720, 720x1280 and 960x1920 and verifies compact canvas binding.
