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

**Reference:** [[MUSIC.md — Line 19](<https://chatgpt.com/home/bin4ry/hadk/hybris/mw/harbour-sailplay/MUSIC.md:19>)](/home/bin4ry/hadk/hybris/mw/harbour-sailplay/MUSIC.md:19)

Describes one Mconnect core with phone UI and Sailplay's MPRIS controls.

**Known limitation:** [[MUSIC.md — Line 41](<https://chatgpt.com/home/bin4ry/hadk/hybris/mw/harbour-sailplay/MUSIC.md:41>)](/home/bin4ry/hadk/hybris/mw/harbour-sailplay/MUSIC.md:41) explicitly says closing the phone window still terminates the core.

**Required action:** Fix this before using Mconnect as the SDK lifecycle example.

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
- [ ] Mconnect window/core lifecycle separation using its current native runtime.
- [ ] One authoritative map backend with independent phone and car presentations.
- [ ] Sandboxed dedicated renderer activation and Imira/input permission validation.
- [ ] Content1 browsing, lists, search, actions and messages, with their host templates.
- [ ] Real Mconnect and map phone/car acceptance, followed by a second real navigation provider.

### Navigation SDK verification (2026-11-10)

- Sailplay 0.1.1-61 was built and installed on JollaPhone2026. RPM verification, installed runtime imports and XML, AArch64 binary hashes and dependency resolution passed.
- The complete documented unittest suite passed 329 tests. Pytest passed 936 tests and 491 subtests, including the regression for new activity arriving before the example backend's idle-exit callback.
- Installed Python and Qt calls verified caller-owned guidance, backend replacement, a second fake provider, phone session closure, hidden car sessions, accepted stop completion and explicit navigation stop.
- The installed carui dock entry and guidance card passed geometry checks at 1920x720, 1280x720 and 720x1280 with hidden windows on the minimal platform. The live snapshot reader and subscribed iAP2 codec passed, and graceful carui exit preserved the backend and removed its export.
- Final device checks restored the saved recent-app history and compositor command bytes and removed their test files and directories. An earlier AAC timeout passed its isolated seven-test retry and subsequent complete runs.
- An earlier timed-out GUI check lacked a saved original history backup. Recovery removed its confirmed test entry under an exact-content guard. Byte-for-byte restoration of that earlier history remains unverified.
- This stage completes navigation SDK integration. Real phone-window and vehicle visual acceptance, Mconnect lifecycle separation, shared map presentations, Sailjail renderer permissions and Content1 remain subsequent milestones.
