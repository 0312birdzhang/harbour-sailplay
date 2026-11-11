# Sailplay SDK Architecture Proposal

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

Google's official [[Car App Library](<https://developer.android.com/training/cars/apps/library>)](https://developer.android.com/training/cars/apps/library) documents the same broad host-template approach, while its [[release notes](<https://developer.android.com/jetpack/androidx/releases/car-app>)](https://developer.android.com/jetpack/androidx/releases/car-app) describe map canvas plus host content.

## 4. D-Bus Service Ownership and Sailjail Integration

App developers should expose the Sailplay interfaces on the **D-Bus service already owned by their app identity**, such as:

`org.example.MyApp`

Sailplay discovers that service from installed metadata and acts as a client.

This is a useful fit for Sailjail:

- `OrganizationName` and `ApplicationName` define the name the app may own.
- `ExecDBus` supports background activation without showing a window.

Reference: [[Official Sailfish Launcher Documentation](<https://docs.sailfishos.org/Reference/Core_Areas_and_APIs/Apps_and_MW/Lipstick/Launchers/>)](https://docs.sailfishos.org/Reference/Core_Areas_and_APIs/Apps_and_MW/Lipstick/Launchers/)

This avoids assuming every sandboxed app can call a newly invented central Sailplay bus name.

Real permissions still need testing, especially renderer access to the private compositor.

### API Versioning Principles

- Version interfaces and object paths from v1.
- Keep the app's existing service identity so it retains its Sailjail ownership grant.
- Allow multiple interface versions to coexist.
- Ship the XML as the source of truth.
- Avoid opaque JSON strings as the entire API.

Reference: [[D-Bus API Design Guidance](<https://dbus.freedesktop.org/doc/dbus-api-design.html>)](https://dbus.freedesktop.org/doc/dbus-api-design.html)

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

Current code supports this architectural direction but does not yet implement the complete model.

### 6.1 Mconnect Lifecycle

The native C++/Silica runtime owns playback, storage and MPRIS independently
of the phone QML tree. Closing the phone presentation releases its QML and
polling, while car leases and ongoing work retain the core. Show rebuilds the
phone presentation over that core. The integration and installed verification
are recorded below. [Background music integration](MUSIC.md)

### 6.2 Navigation Provider Abstraction

**Reference:** [[navigationfeed.py — Line 24](<https://chatgpt.com/home/bin4ry/hadk/hybris/mw/harbour-sailplay/carplay_proto/navigationfeed.py:24>)](/home/bin4ry/hadk/hybris/mw/harbour-sailplay/carplay_proto/navigationfeed.py:24)

The existing implementation and its file scanning are Organic Maps specific.

**Required action:**

- Preserve the current implementation as a legacy adapter.
- Expose a provider-neutral navigation interface to new applications.

### 6.3 Dedicated Car Renderer Activation

**Reference:** [[main.cpp — Line 332](<https://chatgpt.com/home/bin4ry/hadk/hybris/mw/harbour-sailplay/display-source/carui/main.cpp:332>)](/home/bin4ry/hadk/hybris/mw/harbour-sailplay/display-source/carui/main.cpp:332)

The current code launches projected binaries onto Imira.

The comment near line 59 acknowledges skipping normal wrappers because they would connect applications to Lipstick.

**Required action:** Treat sandboxed activation of a dedicated car renderer as an early validation task, not as an already solved problem.

## 7. Recommended Acceptance Milestone

The first meaningful SDK acceptance milestone should demonstrate that:

1. **Mconnect and one map application** remain usable simultaneously on phone and car.
2. Closing either presentation does not terminate shared work.
3. A second navigation provider integrates without modifications to Sailplay core.

This is stronger evidence of a useful SDK than implementing many API categories upfront.

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

- [x] App1 and Session1 canonical XML, Python provider/client helpers and Qt/QML client bindings.
- [x] Caller-owned sessions, asynchronous requests, revisioned snapshots and backend-owner reconnect handling.
- [x] Backend lifecycle notifications including accepted work whose presentation has closed.
- [x] Navigation1 model and XML, Python navigation helpers and installed desktop declaration readers.
- [x] Compact and expanded car guidance templates through the existing app, dock and dashboard entry points.
- [x] Provider-neutral instrument sender with the Organic Maps v1 adapter and a second fake provider integration test.
- [x] Install and verify the navigation SDK RPM and Qt/Python calls on Sailfish.
- [x] Mconnect window/core lifecycle separation using its current native runtime.
- [x] One authoritative map backend with independent phone and car presentations through the navigation template.
- [x] Optional map canvas, map gestures and route controls inside the car navigation template.
- [ ] Sandboxed dedicated renderer activation and Imira/input permission validation.
- [x] Content1 browsing, lists, search, actions and messages, with their host templates.
- [ ] Real Mconnect and map phone/car acceptance, followed by a second real navigation provider.

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
- Real phone gesture closure and vehicle visual acceptance remain open, alongside independent map presentations, dedicated renderer sandbox permissions and Content1 templates.

### Shared map backend verification (2026-11-11)

- Organic Maps owns one framework, route, location source, recording session and writable state. Its full Silica phone window can close and rebuild while Sailplay retains the car navigation template. The complete integration covers 33 source files and applies to the recorded original baseline. The final map source commit is `b40a00d89a665b06374371b9b5e8914139174231`. [Shared map integration](sdk/integrations/organicmaps/README.md)
- Retaining the configured phone QML engine across rebuilt windows preserves asynchronous Silica callbacks. Initial offscreen surface bindings are serialized for the device's EGL bridge. Ten consecutive production-bridge lifecycle runs passed after these fixes, including offline route progress and recording while the phone view was closed. All seven device fixture groups passed and cleaned their temporary resources.
- Python verification passed 341 unittest tests, 948 pytest tests and 493 subtests. An AAC timeout in the first full run passed its isolated seven-test retry and the subsequent complete runs. The native source integration passed baseline application, source hashes and reverse application. The Mconnect overlay's applied state passed its content checks.
- JollaPhone2026 received Organic Maps `2026.11.10-3`, Sailplay `0.1.1-64` and Mconnect `1.6.0-53`. Root RPM verification, installed binary hashes, dynamic library resolution, 106 installed QML files, three Sailjail profiles and three SDK license notices passed. Build and installation helpers now select the version declared by the RPM spec.
- Normal Sailjail activation passed the installed map's typed Navigation1 interface, three phone Show/Close cycles over the same backend, directed state/guidance/action/property signals, invalid stop rejection, accepted stop completion, hidden car leases, caller loss and idle exit. Installed Python clients also received completion signals when acquiring their temporary client name after backend activation.
- Installed Mconnect clients passed directed media updates, Active notifications, paused-state preservation, hidden leases and idle exit. A concurrent device check observed both real application backends and their existing D-Bus identities while their lifecycle suites ran.
- The installed carui desktop/dock entry and navigation template passed at 1920x720, 1280x720 and 720x1280 with a hidden window. Hiding the template retained its car lease. Graceful carui exit removed its guidance export and the final lease, allowing the map backend to exit. A cleanup check initially matched its own command text. Matching actual process arguments fixed the check, and the verified fixture files and directories were removed on recovery and the complete retry.
- Guarded restoration matched all saved application data and shell-state bytes. The playback memory differed only in its save timestamp and was restored under its native lock. The exact test-created bookmark backup was removed under its saved hash. The restoration cleanup helper's allowed prefix was corrected for its dedicated temporary directory, and both verified restoration sources were removed. All installed packages passed root RPM verification and Sailplay remained active and enabled.
- Dedicated map canvas rendering, sandboxed renderer/compositor/input validation, Content1 host templates, physical phone/vehicle acceptance and a second real navigation provider remain unchecked.

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

Dedicated map canvas rendering, sandboxed renderer/compositor/input validation,
physical phone/vehicle acceptance and a second real navigation provider remain
open. The real Mconnect browsing integration currently covers its playback queue
and search within that queue.

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
- Physical vehicle UI/audio acceptance, dedicated map rendering and sandboxed renderer permissions, and a second real navigation provider are subsequent milestones.

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
- Physical hand-touch and visual/audio acceptance, the same-signature DAuto receiver patch installation, a sandboxed dedicated renderer and a second real navigation provider remain open. Phone and car continue to share the map viewport, and map requests retain their one-in-flight, 200-millisecond limit.
