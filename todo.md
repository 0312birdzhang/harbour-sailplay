# Sailplay SDK Architecture and TODO

Reviewed against the working tree on 2026-11-12. Section 6 describes the current
implementation, section 9 retains dated implementation and verification
checkpoints, and section 10 lists the remaining work. Device results below are
retained verification records. The current device state requires a fresh read
before the next installation or acceptance run.

## 1. Recommended Architecture

Recommend **one authoritative app backend, two independent presentations, and a small D-Bus SDK**.

This addresses the missing Sailfish multi-display support without making that limitation every app developer's problem.

```text
                 App backend service
          state / route / playback / database
                   ↙             ↘
       Phone presentation       Car presentation
          Lipstick             Sailplay templates
                               or optional renderer
                                      ↓
                                    Imira
```

The backend is one logical owner. Phone and car can each navigate their UI independently while operating on the same playback queue or route.

- **Template-based applications:** Sailplay itself is the car presentation; no second app GUI process is required.
- **Custom-rendered applications:** Applications needing their own map or custom visual scene start a separate car renderer connected to Imira.
- **Shared state:** The renderer shares backend state through IPC and does not start another route engine or writable application database.

## 2. Public SDK Requirements

The public SDK should contain:

1. **Canonical D-Bus introspection XML**, installed with the SDK and used for bindings.
2. **Versioned lifecycle and capability contracts**, such as:
   - `org.sailplay.App1`
   - `org.sailplay.Session1`
   - `org.sailplay.Content1`
   - `org.sailplay.Navigation1`
3. **Language bindings:** Small Qt5/C++/QML and Python helpers first. Dart/Rust wrappers can follow without changing the wire protocol.
4. **Development tools:** A desktop/manifest declaration, reference backend, fake providers, and simulator.
5. **Contract validation:** A test suite validating behavior against the contract, including malformed and unsupported requests.

## 3. Content and Rendering Model

Keep **MPRIS for media**.

Add a small, fixed set of content models for:

- Browsing
- Lists
- Search
- Actions
- Messages
- Guidance

Do not begin with:

- An extensible UI language.
- Arbitrary QML plugins loaded into the host.
- A compulsory custom renderer for every integration.

### Optional Map Canvas

The map canvas is an optional extension:

- The application provides pixels.
- Sailplay owns common controls and layout.

Google's official Car App Library documents the host-template approach, and
its release notes describe map canvas plus host content.
[Car App Library](https://developer.android.com/training/cars/apps/library)
[Release notes](https://developer.android.com/jetpack/androidx/releases/car-app)

## 4. D-Bus Service Ownership and Sailjail Integration

App developers should expose the Sailplay interfaces on the **D-Bus service already owned by their app identity**, such as:

`org.example.MyApp`

Sailplay discovers that service from installed metadata and acts as a client.

This is a useful fit for Sailjail:

- `OrganizationName` and `ApplicationName` define the name the app may own.
- `ExecDBus` supports background activation without showing a window.

The launcher contract documents these identity and activation fields.
[Official Sailfish Launcher Documentation](https://docs.sailfishos.org/Reference/Core_Areas_and_APIs/Apps_and_MW/Lipstick/Launchers/)

This avoids assuming every sandboxed app can call a newly invented central Sailplay bus name.

The dedicated counter renderer has passed installed-device Sailjail activation,
private Wayland access, directed D-Bus calls and compositor input checks.
Its profile grants the renderer's Wayland socket and backend access. The host's
raw input endpoint remained inaccessible. Each adopting application's profile
and physical phone/vehicle behavior still require integration acceptance.
[Renderer binding and permissions](sdk/README.md#dedicated-car-renderers)

### API Versioning Principles

- Version interfaces and object paths from v1.
- Keep the app's existing service identity so it retains its Sailjail ownership grant.
- Allow multiple interface versions to coexist.
- Ship the XML as the source of truth.
- Avoid opaque JSON strings as the entire API.

The versioning rules follow the D-Bus API design guidance.
[D-Bus API Design Guidance](https://dbus.freedesktop.org/doc/dbus-api-design.html)

## 5. Ownership and Lifecycle Contract

Ownership and lifecycle must be explicit before declaring SDK v1 stable.

| Event | Required behavior |
|---|---|
| Car opens an app while phone UI is closed | Activate backend and car session; no phone window |
| User opens the phone app | Attach to existing backend |
| User closes phone window | Remove phone presentation; keep active car session and work |
| User changes app on car | Hide/suspend presentation; route or playback may continue |
| Car disconnects | Close car session and renderer; backend policy decides ongoing playback/navigation |
| Backend crashes | Clear stale UI and actions; reconnect to a new owner with a fresh snapshot |
| User explicitly stops playback/navigation | Honor stop; leases must not secretly restart activity |
| All views close and no active work remains | Permit backend to exit |

Mconnect's explicit-close policy also exits during playback when the phone
window closes with no car lease. A hidden car lease retains its backend.
When the final car lease ends, a closed or never-opened phone presentation
allows immediate shutdown. Other applications retain their own work/exit
policy. The release-55 checkpoint below records this Mconnect behavior.

### Lifecycle Implementation Requirements

**Session management**

Use bus-owner tracking and session ownership so a shell crash releases its sessions.

**State synchronization**

Initial snapshots plus revisioned updates make reconnects deterministic.

**Asynchronous operations**

Slow work should be asynchronous. Both UIs submit commands to the backend instead of mutating shared files.

**Responsibility boundaries**

- **App backend:** Owns business state, including playback, navigation routes, and application data.
- **Sailplay:** Owns its screen navigation, focus, connection, and projection state.

## 6. Current Codebase Assessment

App1, Session1, Navigation1, Content1, the host templates and the dedicated
renderer path are implemented. Remaining integration and physical acceptance
work is listed in section 10.

### 6.1 Mconnect Lifecycle

The native C++/Silica runtime owns playback, storage and MPRIS independently
of the phone QML tree. Closing the phone presentation releases its QML and
polling. Car leases retain the core, including while hidden. Explicit phone
close with no car lease exits the application, and the final car lease allows
exit when the phone presentation is closed. Show rebuilds the phone
presentation over the retained core. The integration also exposes the existing
playback queue through Content1. Release 56 fixes playback-position binding
after slider release and cancellation. Installed finger-drag acceptance remains
open. [Native Mconnect integration](sdk/integrations/mconnect/README.md)

### 6.2 Navigation Provider Abstraction

`NavigationFeed` retains the Organic Maps legacy snapshot reader.
`ProviderNavigationFeed` selects validated SDK or legacy guidance, and
`NavigationSender` consumes the common provider model. New applications declare
their service and capabilities and export Navigation1 on caller-owned sessions.
The Qt navigation host supplies compact/expanded guidance, optional map pixels,
gestures and destination controls. A second fake provider has passed integration
checks. Acceptance with a second real navigation application remains open.
[Provider selection](carplay_proto/navigationproviders.py)
[Navigation host](display-source/carui/navigationhost.cpp)

Organic Maps retains one framework, route, location source and writable state.
Phone and car presentations have separate lifetimes and host UI state. While
the phone map is open, the car canvas receives that map viewport, so panning
and zooming are shared. Independent phone/car map cameras remain unfinished.
[Organic Maps integration](sdk/integrations/organicmaps/README.md)

### 6.3 Dedicated Car Renderer Activation

Python and Qt desktop readers validate `X-Sailplay-RendererDesktop`, the
companion executable and its enabled Sailjail identity. Carui launches declared
renderers through `sailjail -p`, supervises their processes and publishes the
actual Wayland client's PID/start-time identity. Legacy projected native apps
retain their existing launch path. [Carui launch implementation](display-source/carui/main.cpp)

The qmake SDK includes `SailplayRenderer`, which attaches to the shared backend,
retains hidden leases, follows backend replacement and closes its session on
host-input EOF. Imira adopts late renderer identities and routes dashboard
input within their viewport. The installed counter fixture passed three cold
runs at 1280x720, 1920x720 and 720x1280. Physical touch and vehicle visual
acceptance remain open. [Renderer binding](sdk/qt/sailplayrenderer.cpp)
[Compositor identity and input handling](display-source/imira-patches/imira-comp.cpp)

## 7. Recommended Acceptance Milestone

The first meaningful SDK acceptance milestone should demonstrate that:

1. **Mconnect and one map application** remain usable simultaneously on phone and car.
2. Closing either presentation does not terminate shared work.
3. A second navigation provider integrates without modifications to Sailplay core.

Installed reference fixtures and isolated application checks are recorded
below. Real phone/car acceptance and the second real provider remain the
acceptance milestone.

## 8. Summary

The proposed architecture establishes a clear separation of responsibilities:

| Component | Responsibility |
|---|---|
| App backend | Authoritative application state, playback, navigation, and database |
| Phone presentation | Independent phone UI through Lipstick |
| Sailplay templates | Host-managed car UI |
| Optional car renderer | Custom map or visual scenes |
| Imira | Car display composition |
| D-Bus SDK | Versioned IPC contracts, lifecycle, capabilities, and state synchronization |
| Sailjail | Application identity and permission enforcement |

**Core recommendation:** Stabilize backend ownership, lifecycle behavior, and provider-neutral interfaces before expanding the SDK's content model or rendering capabilities.

## 9. Implementation Progress

The checklist reflects the reviewed working tree. The dated subsections retain
their release-specific verification scope and limitations.

- [x] App1 and Session1 canonical XML, Python provider/client helpers and Qt/QML client bindings.
- [x] Caller-owned sessions, asynchronous requests, revisioned snapshots and backend-owner reconnect handling.
- [x] Backend lifecycle notifications including accepted work whose presentation has closed.
- [x] Navigation1 model and XML, Python navigation helpers and installed desktop declaration readers.
- [x] Compact and expanded car guidance templates through the existing app, dock and dashboard entry points.
- [x] Provider-neutral instrument sender with the Organic Maps v1 adapter and a second fake provider integration test.
- [x] Install and verify the navigation SDK RPM and Qt/Python calls on Sailfish.
- [x] Mconnect window/core lifecycle separation using its current native runtime.
- [x] One authoritative map backend with separate phone/car presentation lifetimes and host navigation UI.
- [x] Optional map canvas, map gestures and route controls inside the car navigation template.
- [x] Sandboxed dedicated renderer activation and Imira/input permission validation.
- [x] Content1 browsing, lists, search, actions and messages, with their host templates.
- [ ] Independent phone/car map cameras and gestures over the shared map backend.
- [ ] Real Mconnect and Organic Maps phone/car acceptance.
- [ ] A second real navigation provider integrated through the published SDK.

### Navigation SDK verification (2026-11-10)

- Sailplay 0.1.1-61 was built and installed on JollaPhone2026. RPM verification, installed runtime imports and XML, AArch64 binary hashes and dependency resolution passed.
- The complete documented unittest suite passed 329 tests. Pytest passed 936 tests and 491 subtests, including the regression for new activity arriving before the example backend's idle-exit callback.
- Installed Python and Qt calls verified caller-owned guidance, backend replacement, a second fake provider, phone session closure, hidden car sessions, accepted stop completion and explicit navigation stop.
- The installed carui dock entry and guidance card passed geometry checks at 1920x720, 1280x720 and 720x1280 with hidden windows on the minimal platform. The live snapshot reader and subscribed iAP2 codec passed, and graceful carui exit preserved the backend and removed its export.
- Final device checks restored the saved recent-app history and compositor command bytes and removed their test files and directories. An earlier AAC timeout passed its isolated seven-test retry and subsequent complete runs.
- An earlier timed-out GUI check lacked a saved original history backup. Recovery removed its confirmed test entry under an exact-content guard. Byte-for-byte restoration of that earlier history remains unverified.
- At this navigation checkpoint, Mconnect lifecycle separation, shared map presentations, Sailjail renderer permissions, Content1 and real phone/car acceptance remained subsequent milestones.

### Mconnect lifecycle verification (2026-11-10)

- Mconnect 1.6.0-52 and Sailplay 0.1.1-62 were built and installed on JollaPhone2026. Root RPM verification, installed binary hashes, dependency resolution and the installed Python runtime/XML checks passed.
- The native source integration targets the existing C++/Silica 1.6.0-51 migration tree, including its preceding local migration work beyond upstream `82f09c4`. Sailplay publishes the guarded lifecycle patch and seven SDK overlay files. Baseline application, idempotence, mismatch rejection, rollback and preservation of a concurrent edit passed. [Native integration](sdk/integrations/mconnect/README.md)
- Host native suites passed 31/31 and device native suites passed 32/32, including the installed GStreamer audio library with `fakesink`. The existing UI responsiveness assertion now uses its bounded condition-wait helper. Python verification passed 329 unittest tests, 936 pytest tests and 491 subtests.
- Host and Qt 5.6 device SDK fixtures passed typed nested maps/hashes, invalid nested-value rejection, caller-owned properties and directed signals, hidden leases, session limits, vanished callers, music-host reuse and backend replacement. Nested values are validated before querying their D-Bus signature to handle Qt 5.6 marshalling safely.
- Normal Sailjail cold activation opened an SDK car session on the user bus, exported the core and MPRIS identities, retained paused playback through a hidden lease for fourteen seconds and exited after caller loss and the last lease closed. Direct and D-Bus startup supply Wayland and Maliit defaults before Qt loads its plugins. The core uses a ten-second idle grace period with an activity recheck at the deadline.
- The complete installed QML validator passed and released/rebuilt the phone tree twice over its isolated core fixture. An initial minimal-platform run exposed the platform's 240x320 screen size. The complete retry used a hidden Wayland window with the device's screen dimensions.
- An isolated installed-core probe restored a two-item legacy Hive queue with its second item selected at twelve seconds, preserved paused state and Unicode MPRIS metadata, and exercised the production carui compatibility ID, dock entry, existing-player reuse and hidden media lease. Graceful carui exit released its final lease and allowed the same core to exit. The compositor command bytes were restored and the test directory, including isolated data and history, was removed under identity/hash guards.
- Final checks matched the original recent-app history, carui configuration, UI/dashboard state and compositor command bytes. Normal activation had updated only the playback memory's `savedAt` field. Its original bytes were restored under the native file lock and exact hash guards, and all 28 original Mconnect data files matched their saved hashes. Sailplay remained active and enabled, with both installed packages passing root RPM verification.
- At the release-62 checkpoint, real phone gesture closure and vehicle visual acceptance, shared map integration, dedicated renderer sandbox permissions and Content1 templates remained open.

### Shared map backend verification (2026-11-11)

- Organic Maps owns one framework, route, location source, recording session and writable state. Its full Silica phone window can close and rebuild while Sailplay retains the car navigation template. The complete integration covers 33 source files and applies to the recorded original baseline. The final map source commit is `b40a00d89a665b06374371b9b5e8914139174231`. [Shared map integration](sdk/integrations/organicmaps/README.md)
- Retaining the configured phone QML engine across rebuilt windows preserves asynchronous Silica callbacks. Initial offscreen surface bindings are serialized for the device's EGL bridge. Ten consecutive production-bridge lifecycle runs passed after these fixes, including offline route progress and recording while the phone view was closed. All seven device fixture groups passed and cleaned their temporary resources.
- Python verification passed 341 unittest tests, 948 pytest tests and 493 subtests. An AAC timeout in the first full run passed its isolated seven-test retry and the subsequent complete runs. The native source integration passed baseline application, source hashes and reverse application. The Mconnect overlay's applied state passed its content checks.
- JollaPhone2026 received Organic Maps `2026.11.10-3`, Sailplay `0.1.1-64` and Mconnect `1.6.0-53`. Root RPM verification, installed binary hashes, dynamic library resolution, 106 installed QML files, three Sailjail profiles and three SDK license notices passed. Build and installation helpers now select the version declared by the RPM spec.
- Normal Sailjail activation passed the installed map's typed Navigation1 interface, three phone Show/Close cycles over the same backend, directed state/guidance/action/property signals, invalid stop rejection, accepted stop completion, hidden car leases, caller loss and idle exit. Installed Python clients also received completion signals when acquiring their temporary client name after backend activation.
- Installed Mconnect clients passed directed media updates, Active notifications, paused-state preservation, hidden leases and idle exit. A concurrent device check observed both real application backends and their existing D-Bus identities while their lifecycle suites ran.
- The installed carui desktop/dock entry and navigation template passed at 1920x720, 1280x720 and 720x1280 with a hidden window. Hiding the template retained its car lease. Graceful carui exit removed its guidance export and the final lease, allowing the map backend to exit. A cleanup check initially matched its own command text. Matching actual process arguments fixed the check, and the verified fixture files and directories were removed on recovery and the complete retry.
- Guarded restoration matched all saved application data and shell-state bytes. The playback memory differed only in its save timestamp and was restored under its native lock. The exact test-created bookmark backup was removed under its saved hash. The restoration cleanup helper's allowed prefix was corrected for its dedicated temporary directory, and both verified restoration sources were removed. All installed packages passed root RPM verification and Sailplay remained active and enabled.
- At the release-64 checkpoint, map canvas rendering, sandboxed renderer/compositor/input validation, Content1 host templates, physical phone/vehicle acceptance and a second real navigation provider remained unchecked.

### Mconnect source publication (2026-11-11)

- The complete native Mconnect application was published to `0312birdzhang/harbour-mconnect` on `main` at `0785280`, including the preceding native migration, Silica/QML presentation, release 53 lifecycle integration, bundled SDK and RPM inputs. The standalone checkout passed all 31 native host tests and verified the release 53 RPM. Its 649 source files were checked against the application snapshot and staged Git blobs. [Mconnect source commit](https://github.com/0312birdzhang/harbour-mconnect/commit/0785280)

### Content SDK and Mconnect queue verification (2026-11-11)

- Content1 now has canonical XML, bounded page and query models, Python provider/client helpers, Qt provider support and a car host template. Browsing history, search results and pagination belong to each presentation. Catalog versions remain independent of media progress, and caller-owned asynchronous operations handle page queries and selection. [Content SDK](sdk/README.md)
- Mconnect release 54 exposes its existing playback queue and queue-local song/artist search through its existing service and player. Queue selection validates both the index and platform/song identity before calling the native player. Its visible `harbour-mconnect-silica` desktop entry declares the canonical `harbour-mconnect` backend identity. The guarded integration covers 29 native files and 11 SDK overlay files and passed baseline application, idempotence, mismatch rejection, rollback and concurrent-edit preservation. [Native integration](sdk/integrations/mconnect/README.md)
- Host verification passed 350 unittest tests, 957 pytest tests and 550 subtests. The nine Content Python tests and all 32 Mconnect native suites passed. The production Qt ContentHost passed ownership, bounds, pagination, superseded-search handling, actions, messages, stable lists during media progress and hidden leases. Early AAC timeouts passed the isolated seven-test retry and subsequent complete suites.
- Sailplay `0.1.1-65` and Mconnect `1.6.0-54` were built and installed on JollaPhone2026. Package checks verified 37 Sailplay SDK source files, four canonical XML contracts, the installed templates and AArch64 payloads. The installed native ContentHost and Mconnect queue fixtures passed. Installed Python clients and the Qt 5.6 host also passed typed dictionary-array transport, independent pages, pagination, search, selection and messages on a private bus.
- Normal Sailjail activation exposed the real 32-song Mconnect queue. Queue search, rejection of a 51-row request, directed completions and Active notifications passed. An eleven-second hidden lease retained the same backend and preserved the song, playback state and position. The installed carui compatibility music identity, visible desktop/dock entry, Browse flow, queue search and Back passed at 1920x720, 1280x720 and 720x1280 with a hidden minimal-platform window. Hiding retained the lease for fourteen seconds, and graceful carui exit released its final leases before the same backend exited.
- Device verification exposed an unavailable `GLib.unix_signal_add` API in the reference service and a stale source-directory `main.moc` that masked the new carui properties and methods. The service now uses the established signal handler pattern. The stale generated file was preserved privately, carui was rebuilt in a clean directory, and the installed retry passed without QML binding errors. Browse availability now has a change-notified property, and the content template handles its initial provider state.
- Final checks matched the saved shell configuration, recent-app history and compositor command bytes. Playback memory differed only in `savedAt` and was restored under the native file lock and exact hash guards. All 28 saved Mconnect data files matched the baseline, all fixture directories were removed, and root RPM verification passed for Sailplay, Mconnect and Organic Maps. Sailplay remained active and enabled.
- The complete release 54 Mconnect source was pushed to `0312birdzhang/harbour-mconnect` on `main` at `64b67c1`, with all 655 tracked source files. The remote branch matched the local commit. [Mconnect source commit](https://github.com/0312birdzhang/harbour-mconnect/commit/64b67c10049b6c1ffb4cc5c3ef22e768d6cc7b7e)

The final AArch64 RPM SHA256 values are recorded below.

- `harbour-sailplay-0.1.1-65.aarch64.rpm` has SHA256 `92afd8923368b0ff356f07e3f999dd6727e55c1f4b4358352895baa93d2f4f1e`.
- `harbour-mconnect-1.6.0-54.aarch64.rpm` has SHA256 `b1d6fcc0effb60b22734f99de8d0780a042dea8f0165c539f9cdebe89ed4584f`.

At the release-65 checkpoint, map canvas rendering, sandboxed
renderer/compositor/input validation, physical phone/vehicle acceptance and a
second real navigation provider remained open. The real Mconnect browsing
integration covers its playback queue and search within that queue.

### Wireless receiver selection and DAuto recovery verification (2026-11-11)

- [x] Remove the packaged vehicle address and use live receiver discovery for the service and reconnect command. Saved MAC identities resolve across BlueZ adapter renumbering. A connected, paired Android Auto receiver takes precedence over a disconnected historical vehicle. Bounded SDP discovers dynamic RFCOMM channels and can establish the Bluetooth link to a verified, paired historical receiver, including one with a cached Android Auto UUID.
- [x] Complete the DAuto wireless compatibility fixes. RFCOMM uses authenticated Bluetooth security. TLS accepts the receiver's empty closing type-3 envelope and still requires successful type-4 authentication. TCP writes allow wireless retransmission, media ACK timeouts follow valid ACK progress, and video focus arriving before the channel-open response is retained for subsequent media setup. A confirmed receiver can recover Bluetooth after Wi-Fi handover or projection failure.
- [x] Repair network restoration and power coverage. An idle, failed or disconnecting temporary ConnMan service can clear its recovery journal without an unsupported disconnect or removal. A disconnect race requires current-state confirmation. An in-progress return to the original network waits for readiness. TCP endpoint retries stay on the associated interface and have a thirty-second deadline. The session CPU lease covers setup and network teardown. Standalone recovery initializes its D-Bus main loop and uses the existing bounded connection lease. The reconnect command allows ten seconds for Bluetooth SDP establishment.
- [x] Build and install Sailplay `0.1.1-75` on JollaPhone2026. Root RPM verification passed, eleven installed connection/recovery source hashes matched, the service command contained no fixed vehicle address, and the existing phone management UI process remained alive. This package reuses the validated release-65 AArch64 compositor, capture and carui payloads. The connection fixes change Python and service code. RPM SHA256 is `4d5e841b08a8160e1bddcb098dc58930bb5e6118d3a70aeee1e61979b3fd24d3`.
- [x] Pass the complete Linux suites with 385 unittest tests, 992 pytest tests and 659 subtests. Regressions cover saved adapter identities, live SDP and continuation parsing, cached UUIDs on disconnected receivers, TLS completion, ACK progress, early video focus, recovery journals, power ordering and standalone D-Bus restoration.
- [x] Verify real Native Wireless projection to the installed DAuto `0.3.12` APK on Pixel 3. The final package completed WPP, ConnMan association, TCP, TLS and hardware video decoding. Two reconnect requests began at 13:45:24 and 13:47:24 CST and completed their Bluetooth recovery. New hardware-decoded first frames arrived at 13:46:02 and 13:47:52. The six-minute observation window covered initial projection and both reconnects. Decoding generally ran at 29–30 fps, with a final 25 fps sample and no reported dropped frames. The texture presentation logs generally showed 19–22 fps. The final device status was `android-auto/projecting`.
- [x] Clean the five installation payload/result directories under exact file hashes, stop the created validation timers/services, and remove diagnostic ADB forwards and nc listeners. The final installed RPM passed verification after the cleanup.
- DAuto uses its restored Native Wireless mode `3` and P2P transport `0`. This run retained its existing `debug-force-p2p-band-24=true` compatibility option and granted overlay permission. A stale receiver group caused Wi-Fi association failures during diagnosis and required a DAuto application restart. The final two reconnects recovered without another application restart.
- A complementary DAuto `v0.3.12` patch handles transport-setting changes and reopens a closed listener after wireless failure. It is supplied as source with its application instructions. Building and installing an APK with the existing application's signing key is pending. [DAuto recovery patch](receiver-patches/README.md)
- At the release-75 checkpoint, physical vehicle UI/audio acceptance, map canvas rendering, sandboxed renderer permissions and a second real navigation provider were subsequent milestones.

### Organic Maps canvas implementation (2026-11-11)

- Organic Maps now exports `navigation-map` through its caller-owned SDK sessions. Carui renders the backend's map pixels in both compact dashboard and expanded navigation cards. Expanded controls support dragging, zooming, locating the phone, planning a route to a selected place and starting or stopping navigation. Starting uses the existing phone disclaimer and route-readiness checks.
- The backend retains one framework, location source, route and writable state. An unshown Qt window hosts the same map item while the phone presentation is closed. The car receives the phone viewport while the phone map is open, so both presentations share panning and zooming. Carui polls at most one frame every 200 milliseconds, with aspect-fit input mapping and bounded JPEG decoding.
- The Qt host fixture passed on Linux and Sailfish Qt 5.6, covering JPEG delivery, nested map state, aspect-fit painting, letterbox input rejection, gesture ordering, hidden leases, malformed frames, retry and owner loss. The production map bridge passed real offline-route progress, recording, explicit stop, map pixels, three phone/car viewport cycles and rendering-resource expiry. The first extended device run exceeded its 180-second limit during repeated isolated Geoclue provider timeouts. The complete retry passed with a 420-second fixture deadline and removed all 247 owned temporary files.
- The Linux host also constructed the production navigation card at 1920x720, 1280x720, 720x1280 and 960x1920 and checked compact canvas binding. Its initial QML run exposed missing host QtQuick modules. After installing the two required host modules, the complete probe passed. Final Python verification passed 385 unittest tests, 992 pytest tests and 679 subtests.
- Sailplay `0.1.1-76` and Organic Maps `2026.11.11-2` were built. Package contents, AArch64 binaries, licenses, source hashes, desktop capabilities and the 37-file baseline patch's application and reversal passed. The final map source is `8056adcc1a457dd980699b8332437e19b6d45da5`. Its input validation uses Qt's exported finite-number check under the bridge's fast-math compiler flags.
- The interrupted release-76 upgrade was retrieved after device access returned. Organic Maps `2026.11.11-2` is installed and its `8056adcc1a457dd980699b8332437e19b6d45da5` source is pushed to `downstream/sailfish`. Root RPM verification passed. The installed SDK rejected four invalid frame requests and ten invalid touch requests, including non-finite and out-of-range values. It returned JPEG frames at 640x360, 360x640 and 1280x720. Complete projected expanded-map and portrait-dashboard entry fixtures also received map pixels.

### Projection cleanup and DAuto touch correction (2026-11-11)

- Sailplay `0.1.1-83` is installed with Organic Maps `2026.11.11-2` and Mconnect `1.6.0-54`. Its package SHA256 is `acbf89ec6ead379219b96661848ca8142bb2c755f47bf0b7bca75e74acee2ed6`. Package verification checked 86 runtime source files, AArch64 binaries, SDK files, translations and LF line endings. Linux verification passed 394 unittest tests, 1001 pytest tests and 692 subtests.
- Display workers now use `su --session-command` and carry their pipeline marker. Cleanup checks executable arguments, projection ownership and PID start time for detached shells, compositor, capture and keyboard workers. Startup clears owned abandoned workers while holding the display lock. Device reconnect checks confirmed that old projection workers exited while the phone management UI PID 39901 retained its original start time.
- Failed WPP negotiation now enters the existing Bluetooth recovery path for the saved, paired receiver. The installed original DAuto `0.3.12` APK completed two release-81 reconnects without another receiver restart. During the release-82 installation, SSH disconnected as projection Wi-Fi was restored. The persisted installation result was retrieved and confirmed success. Its first reconnection then hit the original receiver's TLS read timeout and stopped Native discovery. One DAuto restart restored projection. The complementary receiver source patch still requires a build and installation with the installed APK's signing key.
- The user-reported unresponsive split-view/application-list button was reproduced through Android's input service on the real Pixel 3 projection activity. Video was 1920x1080 with 120 pixels of vertical margins, while the UI canvas was 1920x960. DiAuto reports content-relative coordinates despite advertising the full video touch dimensions. Sailplay now restores the negotiated margin origin for DiAuto before applying its canvas transform. Other receiver identities retain their full-video coordinate mapping. Pointer release uses the final primary-pointer coordinates and clears the press even if those coordinates are invalid.
- At the same physical screen point `(79,1006)`, release 81 delivered `(70,834)` and left the dashboard unchanged. Release 82 delivered `(70,894)` and passed eight consecutive single-tap dashboard/application-list switches, ending on the original dashboard. Regression cases cover horizontal and vertical margins, zero margins, a custom canvas, full-video coordinates from another receiver, final pointer release and malformed release coordinates.
- The second release-82 reconnection exposed a further session-ordering failure after TLS. A receiver notification reached an unnegotiated channel and Sailplay aborted. Release 83 defers at most sixteen pre-discovery sensor/focus notifications, each limited to 16 KiB, and validates their channel identities after service discovery. Advertised sensor batches are parsed and ignored because navigation already uses the phone's providers. Unknown channels, wrong message types, malformed batches and oversized or excessive notifications remain rejected. The installed release 83 resumed projection automatically after its upgrade.
- Release 83 completed two further scheduled reconnects without restarting the receiver APK. Both recreated the projection workers and decoded new Organic Maps frames. After the second reconnect, eight consecutive Android-input-service taps each switched between dashboard and application list, ending back on dashboard. Final root verification passed for all three RPMs, confirmed the original phone UI PID/start time and removal of the previous workers, and reported `android-auto/projecting`. Receiver hardware decoding was 28–29 fps with zero reported dropped frames, while texture presentation was 17–21 fps. The exact-hash installation directories were removed, all twelve manifested reconnect units had unloaded, and no ADB forwards or task nc listeners remained.
- Real carui decoded Organic Maps map frames through the normal dashboard entry. Map requests remain limited to one in flight and a 200-millisecond interval. Phone and car still share the map viewport while the phone map is open, including panning and zooming. Physical hand-touch and vehicle visual/audio acceptance, a sandboxed dedicated renderer and a second real navigation provider remain open.
- Mconnect `main` on GitHub was checked live at `64b67c10049b6c1ffb4cc5c3ef22e768d6cc7b7e`.

### Organic Maps destination controls (2026-11-11)

- [x] Restore destination controls using Organic Maps' iOS CarPlay flow for the projected map. The expanded card offers recent searches, text search, offline categories, bookmark groups and saved places. Map-side controls locate and zoom. The selected-place preview supports saving a bookmark, planning a route and closing the selection or route preview. Settings offer driving, walking, cycling and guidance voice. Navigation hides destination browsing and offers voice and stop controls.
- [x] Reuse the existing SearchModel, BookmarkCategoriesModel, BookmarksModel, PlacePage and Routing objects. The browser uses the existing map framework and writable state. It limits pages to 40 rows, rejects stale row IDs and hides results belonging to an earlier query. Carui recursively decodes nested browser data and permits one browsing request at a time. Browser changes use a dedicated notification so map frames do not continually reset list scrolling.
- [x] Connect the projection shell to its private Maliit peer. The installed production entry fixture sent compositor touch events to the destination button and search input, confirmed input focus and keyboard visibility, received a Chinese offline coordinate result, opened bookmark groups and closed browsing. It preserved the phone keyboard's bus owner and the existing map backend. Its temporary profile and compositor commands were cleaned. The release-84 entry exposed a Qt 5.6 text-height binding loop and null-provider accesses during shutdown. Release 85 fixes both and passed the repeated entry fixture.
- [x] Verify the browser through the real ARM map bridge in an isolated device profile. Offline search, selection, bookmark creation, bookmark selection, 40/5-row pagination, route construction, settings and stale-ID rejection passed. The fixture resets its simulated position before the second route and passed the full phone/car lifecycle regression. All 247 owned temporary files were removed. Host checks constructed the production panel in four landscape and portrait sizes and verified its bounds. Final Python verification passed 397 unittest tests, 1004 pytest tests and 790 subtests.
- [x] Build and install Sailplay `0.1.1-86` with Organic Maps `2026.11.11-3`. Package checks covered runtime sources, QML, translations, AArch64 binaries, licenses, dependencies and exact source hashes. The 41-file integration patch passed application and reversal against its recorded baseline. Organic Maps source `74014dcf5467d4d3a5e99a4099dfd7f77e5cc16e` is pushed to `downstream/sailfish`. All three installed packages passed root RPM verification, including Mconnect `1.6.0-54`, and phone management UI PID 39901 retained its original start time.
- Release 85 restored projection after both scheduled reconnects and passed eight consecutive Android-input-service dashboard/application-list switches. Its first reconnect command returned `EALREADY` from the Bluetooth SDP socket, then the existing projection service recovered automatically. The second command succeeded. The reconnect script now retries a busy SDP connection on a fresh socket up to three times, with ten-second timeouts and half-second pauses. Tests cover recovery, the attempt bound and immediate propagation of terminal errors.
- [x] Repeat the installed map-entry and reconnect regressions on release 86. Both scheduled reconnect commands exited successfully and delivered new Organic Maps frames. Old projection workers exited, the phone management UI remained alive, root RPM verification passed and the final state was `android-auto/projecting`. Eight further Android-input-service taps each switched dashboard/application-list state, ending on the dashboard.
- At the release-86 checkpoint, physical hand-touch and visual/audio acceptance, the same-signature DAuto receiver patch installation, a sandboxed dedicated renderer and a second real navigation provider remained open. Phone and car share the map viewport, and map requests retain their one-in-flight, 200-millisecond limit.

### Mconnect close policy and map location recovery (2026-11-11)

- [x] Make an explicit Mconnect phone-window close exit the complete application when there is no car session, including during playback or other native work. A car session retains the backend after the phone window closes. When the final car session ends, a closed or never-opened phone presentation allows immediate normal shutdown. An open phone presentation retains the application. Show cancels deferred presentation release, and session changes immediately reevaluate ownership. Initial background activation retains its existing idle grace and work check until its first lease.
- [x] Publish Mconnect `1.6.0-55` on `origin/main` at `51d7dc9e7ea879f09b766738c15fbdb1a5eb253d`. The guarded integration includes 29 native files and 11 SDK records. Baseline application, idempotence, mismatch rejection, rollback and concurrent-edit preservation passed. All 32 native host suites passed. The ARM presentation and lifecycle fixtures passed explicit close with ongoing work, deferred reopen, hidden leases, last-lease exit and pending activity at the idle deadline. Their two task-owned fixture files and directories were removed.
- [x] Validate the installed Mconnect binary through its background entry on an isolated device profile and private bus. Two hidden car sessions retained the same backend for eleven seconds. Closing one retained it, and closing the final session exited normally in approximately 0.12 seconds, removed the SDK and MPRIS owners and logged `MCONNECT_NATIVE_IDLE_EXIT`. The fixture's eleven generated files and its directory were removed. The first attempt completed the process-exit checks but looked for the exit message only in redirected output. The complete retry also checked the process journal and passed.
- [x] Distinguish missing GPS position from disabled location in Organic Maps. Missing position displays the existing localized current-position-unknown message, retains the requested navigation start and keeps location/background work active. A valid fix rebuilds the route and starts the requested navigation. Location remains subscribed for an active car canvas independently of phone visibility and follow mode. Qt 5 starts subscriptions on a deferred single-shot timer and cancels pending or reentrant startup when stopped.
- [x] Publish Organic Maps `2026.11.11-4` at `c3ede46460911d4431ed8616ced8e8e287c172db` on `downstream/sailfish`. Its 43-file integration passed application and reversal. The full ARM map lifecycle and location-cancellation fixtures passed missing position, injected valid position, automatic route recovery, phone/car lifecycle, nonblank frames and stopped callbacks. A private no-fix GeoClue provider isolated the fixture from systemd-managed Hybris activation. The fixture injects its coordinates separately. Its 253 generated files and its directory were removed.
- [x] Build and install Sailplay `0.1.1-87`, Organic Maps `2026.11.11-4` and Mconnect `1.6.0-55`. Package verification covered exact source hashes, integrated SDK inputs, QML, AArch64 binaries, profiles, licenses and dependencies. Root RPM verification passed for all three installed packages. Installation preserved phone management UI PID 39901 and its recorded start time. The final scheduled reconnect began after that phone management window had closed and verified all phone management processes present at scheduling time.
- [x] Repeat the installed production destination entry, private keyboard, Chinese offline search and bookmark-group fixture. It retained the existing map backend and phone keyboard owner, restored compositor command bytes and removed its four generated files and directory. Repeat the scheduled release-87 reconnect without restarting DAuto. The command succeeded, old projection workers and the old map backend exited, a replacement map delivered new frames and the final state was `android-auto/projecting`. Eight further Android-input-service taps each switched dashboard/application-list state and returned to the dashboard. Python verification passed 397 unittest tests, 1004 pytest tests and 790 subtests.
- [x] Remove the five manifested release-87 installation files and their device directory under exact content and directory-ownership checks. The installation unit and reconnect timer/service unloaded. Final access cleanup left no ADB forwards or task nc listeners. Live GitHub checks matched the published Mconnect and Organic Maps source commits.
- Release-87 device checks confirmed that location and GPS were enabled and the normal Hybris provider was running. It was in acquiring state with no current fix and zero satellites used. The isolated recovery fixture validates injected-position behavior. At this checkpoint, physical GPS acquisition, real-road navigation, hand-touch and visual/audio acceptance, the same-signature DAuto receiver patch installation, a sandboxed dedicated renderer and a second real navigation provider remained open.

### Map preview input, layout and bookmark icons (2026-11-11)

- [x] Consume input across the complete place-preview card, including its text, padding and gaps between actions. The destination panel, guidance card and toolbar also consume their covered input areas. Disabled settings and bookmark buttons retain input interception while a browsing request is pending. Uncovered map gestures continue through the existing map canvas.
- [x] Adjust the projected controls using Organic Maps' iOS CarPlay map-template layout as a reference. The top-left destination/bookmark controls occupy at most 328 QML units, with settings or navigation stop on the top right. The place preview becomes a bottom-left card capped at 560 units, with a separate green route action and bookmark/close buttons. Navigation keeps a smaller 280-unit arrival summary. Guidance cards also use a bounded width. Geometry checks passed at 1920x720, 1280x720, 720x1280 and 960x1920.
- [x] Add a directly accessible bookmark icon on the map, a star in the bookmark browser tab and a place-bookmark icon that switches between outlined and filled states. The shared Canvas component draws the star independently of installed symbol fonts and is included explicitly in RPM staging and installation.
- [x] Extend the map-canvas fixture with real Qt mouse events over preview text, padding, toolbar gaps, the destination-panel bottom and disabled controls. Bookmark entry and toggle actions passed, including filled-state updates, and an uncovered map tap completed normally. The complete host and Qt 5.6 ARM fixtures passed. A copied variant with the preview input shield removed failed at the expected map-input assertion. Explicit layout polishing handles Row geometry on the minimal platform. The guarded host runner removed its 51 generated files and temporary directory, and the device runner removed its five uploaded files and directory. Final Python verification passed 397 unittest tests, 1004 pytest tests and 790 subtests.
- [x] Repeat the installed production carui entry using the normal map backend and compositor/input path. A temporary UI selection model supplied the preview card while the backend's actual selection remained unchanged after text, padding and toolbar-gap taps. The visible bookmark icon opened the real bookmark groups, followed by the existing Chinese offline search and private-keyboard checks. Both entry runs preserved the backend and phone keyboard owner, restored compositor command bytes and removed their four generated files and directory.
- [x] Build and install Sailplay `0.1.1-88`. Final RPM SHA256 is `03d0c4af503470adadaa15507e44972f64477f9706284d9f4b7d8e55b3fd192d`. The final payload includes the additional interception for disabled settings controls. Package checks covered all QML, 86 runtime source files, five translation catalogs, SDK inputs, AArch64 binaries, licenses and dependencies. Installed QML hashes matched the final source and root RPM verification passed for Sailplay, Organic Maps `2026.11.11-4` and Mconnect `1.6.0-55`. Projection recovered to `android-auto/projecting` after both installations.
- [x] Remove the six manifested installation files and both device directories under content and ownership guards. Both transient installation units unloaded, with no ADB forwards or task nc listeners remaining. The two temporary exports from the earlier failed host checks were removed after checking their exact paths and fixture identities.
- Physical finger-touch and visual acceptance of the revised controls remain open. The automated entry checks use injected touch events and a temporary preview model.

### Mconnect playback slider progress (2026-11-12)

- [x] Restore the playback-position binding after slider release and cancellation. Silica's SliderBase assigns `value` while dragging, releasing and cancelling, which removes the original binding. The page submits the displayed position once on release and then reinstates `Qt.binding`. Cancellation reinstates the binding without a seek request. Backend updates continue driving the slider and elapsed time after interaction.
- [x] Reproduce the reported freeze with actual Qt mouse events on the ARM Qt 5.6/Silica player page. The old QML sought to 108000 ms, then retained both 108000 ms and `1:48` when the isolated core advanced to 109000 ms. The fixed QML passed repeated forward/backward drags, both ends of the slider, playing and paused states, progress updates during a held drag, cancellation, one request per release and continued time updates. The final built binary passed the same regression. All 32 native host suites passed and `git diff --check` passed.
- [x] Add the progress regression to the existing full QML validator and provide `--player-progress-only` for an isolated 720x1280 page. The SDK minimal platform's default 240x320 viewport failed the existing full-validator search-layout assertion before reaching the player test. The focused ARM check passed with the usable phone viewport. A later offscreen attempt found that this SDK provides minimal and Wayland plugins. The final checks used minimal, disabled core dumps and removed their generated runtime file and three directories under path, ownership, content and identity checks.
- [x] Build Mconnect `1.6.0-56` and verify its 64-file RPM payload, two AArch64 ELF files, native runtime, dependencies, Sailjail profiles and progress-regression markers. The package is `harbour-mconnect-1.6.0-56.aarch64.rpm` with SHA256 `9fa22894aa232ba0b4059f760123c451adfc331c69b66fb4c1832f050861c818`. The 655-input source manifest and staged archive were checked against the canonical checkout. Publish source commit `df777967021d27700ceea6b886697cf063768b8e` to Mconnect `origin/main` and verify the live remote commit.
- [x] Confirm the user's manual installation of Mconnect `1.6.0-56` after SSH access recovered on the home network. Root RPM verification passed and the existing Mconnect core remained running. The installed isolated QML validator reached the progress check on the device's minimal platform but failed with a 240x182 page and `drag-not-held`. An invisible Wayland retry exited before the validator. Both private profiles were removed and the original player owner was preserved. The earlier ARM progress regression passed, while installed finger-drag and audio acceptance remain open.

### Projection audio recovery and silent music after installation (2026-11-12)

- [x] Diagnose the user's home-network state with Sailplay inactive. Mconnect was playing and its position advanced, but the deep-buffer and primary hardware outputs were muted. A guarded repair unmuted only the deep-buffer music output and retained its volume and original Mconnect owner. Later reads showed media step 0 and a zero-volume music stream. Menu feedback uses the separate `x-feedback-sound-level` restore entry, which also read zero after the user's settings changed during investigation.
- [x] Reproduce the persistent short-stream volume defect on the real phone using digital-zero audio and a unique restore entry. Before projection its saved volume was 16384 and its device was empty. The old capture code left volume 65536 and a deleted private sink after the short stream and capture had exited. The fixture restored hardware state and removed its exact owned files and entry.
- [x] Save the original persistent stream-restore entries before moving or normalizing playback. Recover entries after live-stream and system-volume restoration, including streams that have already ended. Preserve changed user volume, mute and unrelated device selections. Remove originally absent entries only when they retain the owned private device and temporary boost. Serialize capture and recovery with the same Unix file lock. Legacy recovery records retain their existing handling.
- [x] Handle empty original volume arrays through entry recreation. The first device compatibility probe exposed a PulseAudio Nemo assertion when AddEntry updated an existing entry with an empty volume. The audio server restarted automatically and briefly interrupted music. The original Mconnect process survived and resumed advancing. Recovery now records the recreation gap before removal so an interrupted operation can retry. The final source and installed empty-volume probes restored empty device and volume values successfully, and their exact entries were removed.
- [x] Reproduce a second silent-music path during the intermediate release-89 installation. Reloading module-policy-enforcement moved the existing music stream to sink.null. Restoring matching live streams passed initially on release 90, but subsequent new music streams again used sink.null. Source inspection traced the shared system-bus connection and duplicate OHM enforcement-point registration. RPM now records the previous policy digest before installation and skips activation when the installed policy is identical. A changed RPM policy uses a fresh audio-server registration. Explicit standalone reload retains its earlier module/argument path with live-stream recovery.
- [x] Recover the policy state affected by the investigation with one controlled PulseAudio service restart. The original Mconnect owner/PID/start time and media step 0 remained intact. The first replacement music stream used deep_buffer. A further replacement stream also used deep_buffer before the final installation. The release-91 upgrade preserved that stream and the same PulseAudio PID 35861. The post-install longer automatic-track observation lost its SSH connection, so that later observation remains incomplete.
- [x] Build and install Sailplay `0.1.1-91`. Its RPM SHA256 is `5c54f34ae2db5fe26d96dcc6011139e629d519dcd6dee6e3e59df0e1ae4b0264`. Verification checked all 86 runtime source files, QML, five translation catalogs, SDK files, AArch64 binaries, dependencies and LF line endings. Final host verification passed 417 unittest tests, 1024 pytest tests and 790 subtests. Root RPM verification passed for Sailplay, Mconnect `1.6.0-56` and Organic Maps `2026.11.11-4`.
- [x] Preserve the inactive/dead Sailplay service and its original enable state during installation. Before/after checks matched the home Wi-Fi service, Mconnect owner/PID/start time, active music-stream output, hardware mute/volume states, default sink and media volume step. Release 91 also preserved the running audio server and removed its previous-policy digest. The three task-owned uploaded RPMs and installation directories were removed under exact hash and ownership guards. The two initial compatibility-test packages were removed after verifying their exact hashes.
- [x] Repeat the transient-stream regression against the installed release-91 capture script. Its volume changed from 25% to the temporary 100% during capture, then returned to 25% with an empty device after the stream had ended. Capture exited successfully, hardware sink state and the default output matched their original values, and all four generated files, the directory and the unique entry were removed. Installed empty-volume recovery also passed and removed its unique entry. The release-91 RPM transaction confirmed that identical policy activation was skipped.
- Physical speaker output and the exact pull-down feedback sound remain unconfirmed. At the last connected installation check, media was step 0 of 12 and the normal music stream retained zero volume. Finger-drag acceptance for Mconnect release 56 and the interrupted post-install automatic-track observation remain open. SSH to the home-network phone later timed out, and the Android receiver was disconnected from ADB.

### Dedicated renderer SDK and sandbox verification (2026-11-12)

- [x] Accept installed renderer declarations through the normal carui app and dock entry points. `X-Sailplay-RendererDesktop` selects a companion desktop with a single `/usr/bin` executable and an enabled Sailjail identity. Python and Qt readers reject missing companions, invalid identities and disabled sandboxing. Carui launches the companion through Sailjail.
- [x] Add the Qt `SailplayRenderer` binding and counter renderer example. The binding shares state and actions through a caller-owned car session, retains an inactive lease while hidden, reconnects after backend replacement and closes on host-input EOF. The host controls presentation activity and supervises its renderer process.
- [x] Register the actual Wayland client's PID and start time through the existing compositor identity records. The host follows `/proc/<pid>/stat` parent IDs through both Firejail processes and checks the launch supervisor's saved start time. Identity permissions and renderer ancestry passed on the device. The host removes its exact identity record when the renderer exits.
- [x] Fix dashboard input routing that selected the shell before checking content windows. Dedicated renderers publish an optional third `renderer` line in the existing PID/start-time identity record. Imira checks the start time and agreement with any available environment key, adopts late identity and role information, and refreshes the dashboard layout. Existing two-line records remain accepted. Dashboard input inside the renderer viewport reaches its Wayland surface, while legacy preview taps follow the shell path.
- [x] Complete three installed-device cold runs at 1280x720, 1920x720 and 720x1280. Each run created new Imira, carui, sandboxed renderer and D-Bus backend processes. The 1280x720 run deliberately deferred identity publication until after surface mapping, verified rejection of stale start ticks and acceptance of a legacy two-line record, then confirmed automatic renderer-role adoption.
- [x] Verify the SDK counter reference renderer with a real Wayland shell and automated input through the existing private compositor path. Dashboard center and edge taps, press-move-release, one counter increment per release, input exclusion outside the renderer card, fullscreen input and dashboard restoration passed at all three sizes. The phone SDK session and renderer received the same counter updates.
- [x] Verify the reference renderer in the device's real Sailjail sandbox and Imira. Zero effective capabilities and `NoNewPrivs` passed, and the host's raw touch-injection endpoint was inaccessible inside the sandbox. Closing the phone session retained the renderer. Hidden leases, hidden backend replacement, presentation restoration, renderer exit and backend preservation passed.
- [x] Pass 418 unittest tests, 1025 pytest tests and 794 subtests. The extended Qt provider fixture passed on Linux and Sailfish Qt 5.6, covering renderer declarations, disabled sandbox rejection, inactive startup, activation and host-input EOF. SDK files, 86 runtime source files, five translations, AArch64 binaries, dependencies and LF line endings passed package verification.
- [x] Build and install Sailplay `0.1.1-95`. The final 1,926,848-byte RPM has SHA256 `019016fe44ca98aebb88cc3abce8934f51d20e3030602764a3e5bbf1ece67189`. Root RPM verification passed for Sailplay, Mconnect `1.6.0-56` and Organic Maps `2026.11.11-4`. The upgrade retained the audio server, audio routing, application owners, saved shell configuration and active/running/enabled service state. The installation payload and directory were removed after content checks.
- [x] Compare the final release-95 device snapshot with the pre-fixture snapshot. Installed packages, service PID/state, binary hashes, configuration, audio routing, application owners and endpoints matched. Sailplay MainPID was 28300 and PulseAudio PID was 3807. The complete fixture removed its exact temporary payloads, profiles, processes, identity records, sockets and framebuffer resources, and restored the original compositor command bytes.
- An early failed fixture reached its dashboard timer after the renderer had exited and appended `D - -` to `/tmp/imira-touch`. Recovery removed those exact command bytes under a content and owner guard, retaining the empty file. The original file's existence before that early fixture remains unverified. Subsequent complete runs captured and restored the command bytes, removed their temporary payloads and profiles, and released their compositor/input resources.
- Earlier fixture failures exposed QML logging to the system log, JSON key-order assumptions, an incorrect root-owner assumption for Firejail's `/proc` directory, hidden-shell configuration and input injection before hide processing completed. The final fixture parses JSON, uses console logging and a real Wayland shell, checks ancestry and start ticks, and waits for a stable hidden framebuffer state before testing input. The complete installed-device run passed.
- Physical finger-touch and vehicle visual acceptance of the dedicated renderer remain open. Real Mconnect and map phone/vehicle acceptance, a second real navigation provider, physical GPS acquisition and speaker output remain open. The dedicated renderer reference uses the counter backend, and the current Organic Maps canvas still shares the phone viewport while the phone map is open.

### SDK application selection (2026-11-13)

- [x] Move car-display application selection to a secondary management page. Its default list contains SDK-integrated applications. The pull-down menu exposes all installed applications and marks entries that require SDK integration.
- [x] Discover SDK navigation providers automatically and restore the last used map application. Installed-device entry tests cover the secondary page, list filtering and saved selection.
- [ ] Accept application selection and remembered map restoration through physical touch and the vehicle display.

### System phone and messages SDK adapters (2026-11-13)

- [x] Verify installed system interfaces and shared models. The device exposes `org.nemomobile.voicecall`, `org.sailfishos.Messages` and the Contacts/CommHistory QML modules. A privileged read-only probe loaded contacts, call history and message conversations.
- [x] Implement caller-owned SDK services for phone and messages using the system data models and existing call/message services. Shared Contacts, CommHistory and VoiceCall modules provide access to the installed native components. Dialing keeps the system phone service's SIM-selection flow. SMS submission uses the native message service and replies retain their conversation account.
- [x] Add SDK renderers with contacts, recent calls, a dial pad, call controls, conversation reading and message composition. Message text wraps and paginates with Unicode code-point boundaries. The composer accounts for the private keyboard and supports scrolling.
- [x] Package backend activation, Sailjail permissions and SDK desktop declarations. Discover the adapters automatically and migrate the old phone/messages launcher mappings. The secondary page includes a phone/messages permission prompt. The installed device granted the two backends their declared Contacts, CommunicationHistory, Phone and Messages permissions and allowed both renderer identities to launch. A fixed setgid-privileged launcher enters Sailjail for background database access.
- [x] Verify pagination, stale selections, concurrent queries, backend replacement, hidden sessions and renderer shutdown. Linux and Sailfish ARM communication fixtures cover initial deferred loading, ordered message pages, emoji boundaries, concurrent queries and mutations, stale history/account selections, inactive callers and native rejection/failure. Installed adapters pass cold activation, hidden reads, backend replacement, restored reads and final-session idle exit. Normal renderer entries pass sandbox, hidden/restored PID reuse, host EOF and private keyboard startup.
- [x] Build and install Sailplay `0.1.1-109` on `192.168.3.240`. Verify 27 communication, SDK, QML, translation and permission files against the RPM digests, both AArch64 executables and the launcher's root/privileged ownership and 2755 mode. The 2,026,676-byte RPM has SHA256 `9d1e6db5ce8eb8518de9a9ff14844c31dee6d02ddb9fea51a38303b235dd6897`. Pass 419 unittest tests, 1026 pytest tests and 1004 subtests, the Qt provider/content-host fixtures and the latest ARM communication fixtures. Final normal renderer and secondary-page checks pass. Root RPM verification succeeds for Sailplay, Mconnect and Organic Maps, the audio/configuration installation comparison passes and PulseAudio remains PID 3807. Remove the exact uploaded payloads, temporary directories, renderer identity records, sockets and task framebuffer resources. Remove the empty directory left by the ConnMan service harness after ownership/content checks. The final audit finds no communication backend processes, service owners, projection endpoints, task directories or Sailplay core files.
- [ ] Accept real calls, SMS delivery, head-unit call audio, physical touch and vehicle display.
- [ ] Render and open MMS attachments. The current reader displays an attachment placeholder when an event has no text.
- Successful native dial/message actions report request submission. Device validation read 294 available contacts, two call-history entries and all three existing conversation bodies and reply targets. Mutating native actions were exercised against isolated mocks.

### Communication adapter validation on 192.168.3.234 (2026-11-13)

- [x] Connect using the previous device credentials and the user's requested host-key verification bypass. Verify SailfishOS `5.2.0.22`, AArch64, UID 100000 and privileged GID 996. Upgrade Sailplay from `0.1.1-57` to `0.1.1-109` and verify its installed ELF payload, launcher ownership/mode and all five application/networking packages with root RPM verification.
- [x] Grant the declared permissions and launch allowance for the two communication backends and two renderers. Pass installed SDK cold activation, hidden queries, backend replacement, restored queries and final-session idle exit. Pass the latest ARM isolated communication tests for initial loading, ordered pages, emoji boundaries, stale selections, concurrent requests, inactive callers and native action rejection/failure.
- [x] Validate the real shared models' empty state. Both the privileged model probe and the sandboxed SDK services expose zero available contacts, zero call-history entries and zero conversations. A read-only query of the real CommHistory database confirms zero Events and Groups. The native SMS account is available. The earlier nonempty conversation validation above belongs to `192.168.3.240`.
- [x] Pass normal phone/messages renderer launches, sandbox checks, hidden/restored PID reuse, host EOF and private keyboard startup. Pass the normal mobile settings entry, secondary SDK-only list, all-app pull-down toggle and authorization menu. Installed discovery identifies Mconnect, phone and messages as three SDK applications. The installed Organic Maps `2026.10.25-2` provides no Navigation1 declaration, so this device has zero SDK navigation providers.
- [x] Complete the final cleanup and state comparison. Remove the uploaded RPM and every task directory, renderer identity record, socket and task framebuffer resource. Both communication backends and D-Bus owners exit. PulseAudio remains PID 3533, native phone/messages owners retain `:1.10` and `:1.58`, and the audio routing comparison passes. Main ConnMan retains PID 34589 and owner `:1.149831`, and vpnd retains PID 57947 and owner `:1.156243`. Sailplay is active, running and enabled with MainPID 42873. The release-57 upgrade creates an empty `audio-route-recovery.json.lock` as the new audio recovery initializes. Existing saved configuration checks pass. Kernel core handling is `|/bin/false`. Evidence is retained under `.private/communication-234-20261113/`.
- [ ] Accept nonempty real contact/conversation browsing, real calls and SMS delivery, physical touch, vehicle presentation and remembered navigation-provider restoration on this device. The completed nonempty action/pagination checks use isolated mocks, and its current installed map has no SDK declaration.

## 10. Remaining Work and Session Recovery (2026-11-12)

### Reviewed checkout and retained verification

- [x] Trace the current desktop readers, carui renderer launch/supervision, Qt renderer binding, compositor identity/input routing, provider-neutral navigation and application integration code against the progress checklist.
- [x] Confirm the local release-95 RPM matches SHA256 `019016fe44ca98aebb88cc3abce8934f51d20e3030602764a3e5bbf1ece67189`. The retained package record covers 86 runtime source files, five translations, SDK sources, AArch64 binaries and the Sailjail dependency.
- [x] Read the successful retained renderer result in `.private/sdk-renderer-20261112/device-result.json`. It records all three cold runs, stale-start rejection, legacy identity acceptance, late renderer-role adoption, dashboard/fullscreen input, hidden reconnect, backend preservation and guarded cleanup. Earlier files named `installed-final.log` and `installation-final.json` describe preceding attempts and releases. The successful result and `cold-touch-before95.log` / `cold-touch-after95.log` identify the release-95 checkpoint.
- [x] Rerun the current Linux suites during this review. All 418 unittest tests, 1025 pytest tests and 794 subtests passed. The current qmake Qt provider fixture passed renderer declaration, sandbox rejection, hidden/active sessions and host-input EOF checks. `git diff --check` passed.
- [x] Review and publish the dedicated-renderer source batch with the release-109 application-management and communication-adapter work. Include renderer sources, examples, discovery/host/compositor changes, translations, packaging inputs and tests. The qdbusxml2cpp interfaces, qmake resource sources and communication executable are generated build outputs. The normal qmake projects regenerate the required interfaces and resources from the tracked SDK XML inputs.

### SDK application acceptance

- [ ] Give phone and car map cameras independent panning/zooming while retaining one authoritative map backend, route, location source and writable state. Verify both open presentations and phone close/reopen through the normal application entry points.
- [ ] Accept real Mconnect and Organic Maps simultaneously on phone and car, including explicit phone close, hidden car views, final-lease closure, backend replacement and disconnect/reconnect. Use the release-55 Mconnect close policy described above.
- [ ] Verify Mconnect release-56 playback progress with physical slider drags, release/cancellation and subsequent elapsed-time updates on the installed phone UI.
- [ ] Verify the projected destination controls, preview input interception, bookmark state, private keyboard and map gestures with physical touch and vehicle display observation.
- [ ] Integrate a second real navigation provider through installed metadata and Navigation1 without Sailplay core changes. Cover guidance, stop, owner replacement and phone/car lifecycle.
- [ ] Accept the dedicated renderer's physical touch and vehicle presentation. Application-specific renderer adoption must verify its own Sailjail profile and shared backend.

### Device and receiver acceptance

- [ ] Verify physical GPS acquisition and real-road route start/recovery. The completed no-fix/recovery regression uses injected coordinates.
- [ ] Verify speaker output, pull-down feedback sound and playback routing after projection teardown. The release-91 short-stream and empty-volume recovery regressions passed, while audible output remains open.
- [ ] Complete the interrupted longer post-install automatic-track/routing observation with live music. The later release-95 fixture snapshot contains no active music stream.
- [ ] Build/install the complementary DAuto recovery patch with the existing application's signing key and verify transport-setting changes and failed-listener recovery. The retained wireless runs use the original installed DAuto `0.3.12`. [Receiver patch](receiver-patches/README.md)

### ConnMan VPN regression reported on 2026-11-13

- [x] Refresh the public source to ConnMan `1.40+git39`, commit `9339f68fac76155d68b9671120cea1bacd3df505`, dated 2026-11-12. The new commits cover route-monitor cleanup and retry, RTNL synchronization, DNS handling and WireGuard resolver error accounting. Service removal still retains its old public interface until final destruction. Apply the existing lifecycle fix to the refreshed base, cross-build the real service harness and pass all 14 tests as the device session user. Publish commit `d705143d93ca0b576c603787236e6f4cbf6fdb5d` to `my/fix-service-registry-lifetime-git39` and verify the remote ref. The installed release-3 daemon below retains its tested `1.40+git26.6` package baseline.
- The lifecycle fix follows the shared ConnMan service registry. New VPN protocols use the existing generic vpnd bridge. ConnMan releases require compatibility checks of the patch and build configuration, including preservation of that bridge in the replacement main daemon.
- [x] Trace the retained release-1 VPN discovery regression against the report of SailfishOS `5.2.0.22` and ConnMan `1.40+git26.6`. Disabling every VPN protocol removes the main daemon's built-in `plugins/vpn.c` bridge. Release 2 already enables that bridge through the OpenVPN build option. The affected user's installed fix-package release is still unknown.
- [x] Add release-3 RPM payload checks for the AArch64 executable and built-in VPN symbol. Keep build outputs in each build's own RPM directory, derive the executable version from the spec release and use a temporary protected Git configuration for the older WSL Git.
- [x] Build and inspect `sailplay-connman-fix-1.0.0-3.aarch64.rpm` (557,789 bytes, SHA256 `7bebcf6bf824ddc45476b46f8edadbe9662251bfa817f58f3629edcbd8691e48`). Both the bridge-free AArch64 daemon and an x86-64 executable were rejected by the RPM checks. All 14 service tests passed. The extracted daemon passed private-bus/network-namespace checks for nine VPN types, listed/direct properties, missing-transport disconnect propagation, failure/idle states, removal, same-path recreation and replacement of vpnd while retaining the main ConnMan owner. The earlier daemon reproduced zero VPN services against the same fixture.
- [x] Compare release-3 runtime dependencies with release 2. All 755 external dynamic symbols and GLIBC symbol version requirements match. The available SDK target has `5.1.0.11` OS metadata, glibc `2.41+git5` and libgsupplicant `1.0.30`; the source build uses pinned `1.0.31` headers.
- [x] Install and verify release 3 on the authorized `192.168.3.234` device running SailfishOS `5.2.0.22` and ConnMan `1.40+git26.6-1.43.1.jolla`. The stock daemon matched its hash gate. An independent rollback timer was tested after `daemon-reload` before installation and cancelled after installed-binary, Wi-Fi and VPN discovery checks passed. The running replacement reports `1.40+git26.6.sailplay3`, both daemons list 31 VPN configurations, and all 14 service tests passed as the session user.
- [x] Verify real release-3 VPN traffic on that device. Three successful Xray VMess/WebSocket runs returned HTTP 200 both normally and with `curl --interface utun50`, with matching tunnel route lookups and increasing RX/TX counters. They returned to idle on disconnect and preserved configuration keys. Main ConnMan kept PID `34589` and the same D-Bus owner throughout the resumed tests. The second and third successes kept the same vpnd process and owner. The original test configuration had been replaced between sessions, so the resumed runs selected a current existing configuration with reachable server ports. The earlier stock-daemon run also passed real tunnel traffic.
- [ ] Resolve and accept consecutive VPN reconnects. The successful runs were interspersed with `NoReply` and `OperationAborted` failures. Early retained logs reported an unreachable proxy server. Resumed failure logs also locate a failure at the VPN plugin's `utun50` startup wait with error `-110`. Current Xray plugin source uses a 5000 ms wait, and one failed startup reached Xray's started log after about 5.6 seconds. The cause of startup-duration variation and its production fix remain open. A subsequent main-service connect cleared failure through `OperationAborted`, and a further retry succeeded without daemon restarts. The successful traffic checks establish release-3 VPN bridge functionality while this reconnect acceptance remains incomplete.
- [x] Complete guarded cleanup and final live verification. All 15 test VPN guard units, temporary logging overrides and both remaining task directories were removed, including the uploaded RPM, service-test binary, rollback/install scripts and result files. Restoring logging restarted vpnd and returned all 31 connections to idle. Main ConnMan retained PID `34589` and owner `:1.149831`. Wi-Fi was online and ordinary HTTPS returned 200. Root RPM verification passed, installed/running replacement hashes matched, and the stock daemon and Xray plugin retained their original hashes. Routes, rules, interfaces and reverse-path filter values matched the resumed pre-test snapshot. The release-3 local RPM hash and shell syntax checks passed, as did `git diff --check`. Evidence is retained in `.private/connman-vpn-20261113/device-234-resume-final.json`, `device-234-resume-final-checks.json` and the three successful `release3-resume-1`, `release3-resume-logged-1` and `release3-resume-retry-1` result files.

### ConnMan upstream review on 2026-11-13

- [x] Read the complete discussion of closed PR #166 and refresh origin to `1.40+git40`, commit `dde68eca`. The maintainer identifies service retention as intentional Wi-Fi architecture. Saved-network disappearance retains the service in `service_hash` and reuses it on reappearance. Forgetting a still-visible network retains its public service and marks it unsaved. The current patch preserves both paths. [Review](https://github.com/sailfishos/connman/pull/166#issuecomment-6849323905)
- [x] Extend the source review with normal network-entry regression fixtures. Both stock retention cases pass. An unsaved network removed with an outstanding service reference and recreated with the same identifier produces an available fresh service in the identifier table, while the duplicate-rejecting interface registry still resolves to the detached old service. Its actual D-Bus Connect handler returns `net.connman.Error.NoCarrier`. The stock fixture fails at the old/new interface identity check. The patched source passes all 17 tests, including the two retention cases.
- [x] Cross-build the stock and patched git40 service fixtures and repeat the comparison on `192.168.3.234` as the session user. Stock saved-network and visible-network-forget tests pass. Stock unsaved-network replacement fails with the expected SIGABRT. The patched fixture passes all 17 tests. Remove the uploaded executables and all fixture temporary files after ownership, path and content checks. Evidence is retained under `.private/connman-review-20261113/`.
- [x] Publish the refreshed lifecycle patch and the three normal-network-entry regressions in the formal ConnMan service test suite. The git40-based branch is `my/fix-service-registry-lifetime-git40`, commit `b8b10a6b3efacaf4a6cc67a0c5f5af5d95213988`. Verify the live remote ref after pushing. [Published source](https://github.com/0312birdzhang/connman/tree/fix-service-registry-lifetime-git40)
- [x] Refresh the installed-device read-only evidence. The first read finds 11 Wi-Fi services and 31 VPN services. The final read finds 23 Wi-Fi services and the same 31 VPN services, with matching listed/direct properties and an unavailable saved Wi-Fi service. Main ConnMan retains PID `34589` and owner `:1.149831`, and vpnd retains PID `57947`. The installed package is `sailplay-connman-fix-1.0.0-3` with the existing `1.40+git26.6` package baseline. The final read finds zero review fixture task directories. Document the upstream rejection, intentional retention paths, fixture limits and local-workaround status in `connman-patches/README.md`.
- [ ] Capture the real-daemon Wi-Fi collision through the normal projection handover and identify the outstanding reference owner. Agree with upstream on interface ownership when an unsaved service has actually left the identifier table and its identifier reappears. The review fixtures deliberately retain a reference and substitute the D-Bus registry, so real-daemon acceptance remains open.

### Message sending on 2026-11-13

- [x] Diagnose the reported trusted-PID rejection on `192.168.43.155`, running SailfishOS `5.3.0.16`. PID `13021` is the information backend's `xdg-dbus-proxy`. The native information application's remote `sendMessage` entry rejects that caller. Both modem SIM slots report `Present=false`, while the generated ring-account path remains nonempty.
- [x] Replace the native application's remote-send call with the installed Telepathy channel API under handler identity `org.sailplay.Systemmessages`. Create outgoing CommHistory events, process success and failure callbacks, mark failed events and retain the send guard when a submitted message times out. A history callback arriving after a pre-submission timeout marks its event failed and cannot send. Remove the obsolete native-application D-Bus permission and declare the directly used message and telephony modules.
- [x] Check SIM presence, lock and enablement, messaging permission and account availability before SMS submission. Rebind historical SMS accounts to the currently selected modem. Keep non-SMS accounts subject to their own online state. Show the translated SIM/account error and disable SMS submission in the renderer. Initialize SIM and sending objects when used by the information backend.
- [x] Extend the existing C++ backend fixture and exercise the production sending QML with isolated module mocks. Cover inactive callers, invalid requests, no-SIM/locked/disabled/permission/offline rejection, asynchronous success/failure, concurrent sends, unrelated completion tokens, timeout guards, obsolete SMS accounts and non-SMS replies. Run the fixtures on the host and ARM device.
- [x] Build and install Sailplay `0.1.1-111` on `192.168.43.155`. The final 2,031,284-byte RPM has SHA256 `b050e9990185a194f3560819686b096387b5fa83773a67f3c032f762770e1762`. Verify 27 communication, SDK, QML, translation and permission files, both AArch64 executables and launcher ownership/mode. Pass 419 unittest tests, 1026 pytest tests and 1039 subtests, the host and ARM communication fixtures, production-QML sending mocks and the hidden Wayland UI state probe. The actual SDK reports `smsAvailable=false`, translated no-SIM text and `org.sailplay.Error1.NoSim` before submission. Install with RPM scriptlets suppressed after checking the already installed audio policy, retaining the current projection. Reload the information backend. The running car UI loads the new executable on the next vehicle reconnection.
- [ ] Verify a real SMS with a usable SIM and an authorized test recipient, including receipt and the corresponding history event. Confirm the updated information page's appearance on the car display after reopening it. This device has no SIM, so its live acceptance covers the no-SIM gate.

### Phone and car shared map viewport on 2026-11-13

- [x] Fix shared phone-map frames in Organic Maps commit `380195b0633ecfa9adc62f268f8ca4344657a7d2`. Center-crop the phone framebuffer to the requested car aspect ratio and scale it to the requested dimensions. Apply the corresponding source-viewport transform to map touch input. Keep the shared backend and SDK session when the phone view closes.
- [x] Automatically reactivate a navigation provider when its backend exits while the car map remains active. Bound recovery to three attempts and cancel pending recovery when the host becomes inactive, closes or rejects the provider identity. Pass the Qt reconnect fixture and an actual ARM host reconnect test against Organic Maps after its backend process exits. The host resumes `640x360` frames without reopening the application list.
- [x] Build and install Organic Maps `2026.11.13-1`, a 76,021,762-byte AArch64 RPM with SHA256 `6c7e338677e7282faa50db9ae4df811ee81f4b0bdf785bdc4305c7e23a5ae14b`. Verify the executable, library, 43 integration source files, 70 QML files, dependencies, license and SDK declarations. Pass root RPM verification. The device supplies `640x360` background frames, `1280x720` frames while the phone view is open, `720x1280` frames for a portrait car viewport and `1280x720` frames after closing the phone view, retaining the same SDK session. Update the SDK baseline and lifecycle patch to the committed integration.
- [x] Remove both task directories and their exact uploaded files after path, ownership, file-set and hash checks. The root-created reconnect log retains its expected root ownership until removal. The final audit finds zero remaining task directories or test processes. Root RPM verification passes for both installed applications. The running Organic Maps executable and library match the installed payload, the projection service retains PID `12339`, PulseAudio retains PID `3975` and the audio-policy hash matches its pre-install value.
- [ ] Confirm the map layout, crop and touch behavior visually on the vehicle after reconnecting to load Sailplay 111. Device frame dimensions, session retention and backend recovery have passed. Evidence is retained under `.private/map-phone-20261113/`.

### Connection feedback sailplay_logs_057 on 2026-11-13

- [x] Separate the supplied logs by date and component. The latest Bluetooth run starts at `2026-11-13 12:50:41` and targets `/org/bluez/hci1/dev_54_2A_1B_B2_6B_D0`, labelled `Sonos Roam (SONOS 6BD0)`. Its snapshot advertises the CarPlay accessory UUID, while its connection checkpoints remain `bluetooth=False`, `pending=False`, `worker=False`, `media=False`. The complete supplied Bluetooth session log contains no RFCOMM connection or profile request. `Android-Vlink` is paired and disconnected, advertising only the Serial Port UUID. The supplied files do not identify how the Sonos target was configured or remembered.
- [x] Review the older attempts separately. The `2026-10-23` reconnect failures target an unavailable BlueZ Device1 object and return `UnknownObject`. The `2026-10-27` Wi-Fi attempts reach supplicant `completed` and ConnMan `ready` with DHCP address `192.168.43.53`, then exit the handover worker. These files contain no successful RTSP/media session. The advertisement UUID-removal errors coincide with Bluetooth power changes and the following phone profile registration succeeds.
- [ ] Identify the user's actual receiver and protocol, capture its current installed package version, projection-service log, Android Auto log, systemd ExecStart and saved last-head-unit identities, then reproduce with that receiver connected. Check whether a configured target or a previously remembered UUID-only device selected Sonos. A CarPlay UUID is sufficient for a candidate in the current selection logic, and the startup path can remember a connected candidate before iAP2 authentication. Validate a correction against genuine first-use receivers and historical saved targets. This user's vehicle connection remains unverified.
