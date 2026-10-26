# Organic Maps navigation export

`organicmaps-navigation-export.patch` is based on
`klahr/organicmaps-sailfish` commit `2b7957a` and changes only the Sailfish UI layer.
The matching changes are applied to the local `organicmaps-sailfish` checkout.
They are carried here so Sailplay can track the integration without pushing to
the upstream Organic Maps repository.

On a clean checkout of that revision:

```sh
git apply --check /path/to/harbour-sailplay/map-patches/organicmaps-navigation-export.patch
git apply /path/to/harbour-sailplay/map-patches/organicmaps-navigation-export.patch
```

Rebuild the full Sailfish application using its documented CMake workflow.
An existing RPM or library is not updated by applying the source patch. The
patch neither changes the renderer nor exposes navigation for ordinary phone
launches: export requires `SAILPLAY_NAVIGATION_EXPORT=1`, which Sailplay sets on
projected launches. See [NAVIGATION.md](../NAVIGATION.md) for the snapshot contract
and remaining protocol validation.

`tests/navigation_export_probe.cpp` in Sailplay is a standalone QtCore probe.
Compile it together with the patched `sailfish/navigation_export.cpp`, adding
the Organic Maps repository root to the include path and linking Qt5Core.
It verifies the exporter in isolation; it does not verify live routing or the
full Organic Maps application.

The complete patched application was subsequently built and installed as
`organicmaps-2026.10.22-1.aarch64.rpm`. The existing Linux build cache was switched
to the matching local commit `5ce93a2`; the build used the official spec with
`rpmbuild -bb --build-in-place` inside the Sailfish aarch64 SDK. The SDK's matching
`pulseaudio-devel` dependency was required. Real application startup, an accepted
idle snapshot, and rejection after process exit passed. Live navigation data
and instrument display are separate pending checks, described in NAVIGATION.md.

## Projected navigation UI and rendering (2026-10-25)

Apply `organicmaps-projection-ui.patch` **after** the navigation export patch.
It is based on local commit `5ce93a2` and changes only the Sailfish layer.
Projected navigation hides search/bookmark shortcuts and scales navigation
panels to the actual viewport and phone theme metrics. Normal phone launches
retain the original layout and background-rendering policy. Projected
map processes keep Drape rendering when phone activation is lost; GPS/navigation
updates already continued during the old background-renderer pause.

The matching local Organic Maps source commit is `d3d00c6`. No changes are
pushed to its upstream repository; this patch carries the integration here.

Validation on JollaPhone2026 uses a temporary 1920x720 compositor; no vehicle
system files are changed. `tests/viewport_integration.py` checks five split/full
round trips (1126x688 and 1780x720). `tests/navigation_layout_probe.qml` can be
used as the viewport probe's QML to check the installed navigation components
with long Chinese units. This fixture supplies guidance data; it does not
simulate GPS navigation or verify a vehicle's instrument display.

The adapter's unit tests cover both Screen-based and newer contentArea-based
Silica ApplicationWindow layouts, rejecting unknown or duplicated patterns.
The generated QML stays in the user's Sailplay cache; system Silica files are
never overwritten.

Installed and verified on 2026-10-25:

- Sailplay `0.1.1-56`, service active/running; compatibility script SHA256
  `ce599dfd6c0864d605ac3cec7a30459563106d440d9e445a22ea73fb83ebdf0f`.
- Organic Maps `2026.10.25-2`; library SHA256
  `3ec8e0d804ba38bce17899331c5f5d77d3dbb34c7d608672a612f159c9d808e1`.
- Actual projected map started with exporter=1 on imira-comp-0. A pan after
  requesting phone display-off changed the map framebuffer; the display was
  turned back on and temporary test processes stopped afterwards.
- Normal phone-window startup and valid idle navigation snapshots passed;
  snapshots were rejected after that process exited.

These are device/runtime and component-layout checks, not an on-road GPS
navigation replay. Continuous real-car following still needs vehicle testing.
The phone's saved maps and bookmarks were retained through normal RPM upgrades.

## Selected sailfish-1-core fixes (2026-10-25)

`organicmaps-core-fixes.patch` applies after `organicmaps-projection-ui.patch`
(base `d3d00c6`). It carries these independent downstream commits:

- `2c25c6a2`: upstream `51a0f178`, routing cache generations, guarded road
  projection during rebuilds and removal of unavailable alternative routes.
- `96b0f557`: upstream `647ff124`, per-download validation lifetime, cancellation,
  retries and saved-file revalidation, including the upstream regression tests.
- `249a71c7`: the incremental GeoClue changes from `6d4b3a89`, ignoring late
  callbacks after Stop(), selecting available GeoClue plugins and identifying
  GeoClue 1 separately. The phone has only the GeoClue 1 plugin.

No files under `sailfish/` or `qt/qt_common/` differ from `d3d00c6`. The exported
navigation snapshots, projected layout/rendering policy and existing exact-size
GL constructor remain intact. The full core branch and its raster tile changes
are not merged.

For focused aarch64 SDK tests, configure the existing Sailfish build with
`-DCMAKE_PROJECT_INCLUDE=/path/to/harbour-sailplay/tests/map_core_test_hook.cmake`
and build targets `sailplay_core_async`, `sailplay_core_blake3`,
`sailplay_core_storage`, `sailplay_core_routes`, `sailplay_core_location`.
This test-only hook uses the existing Qt5 event loop; it does not replace the
production Qt configuration. Remove the hook with `cmake -U CMAKE_PROJECT_INCLUDE`
after building. The location probe injects a valid fix into the real GeoClue
adapter and checks ignored callbacks before Start()/after Stop() and restart.

Storage tests need the upstream localhost test server on port 24568. All tests
must use isolated HOME/XDG_CONFIG_HOME/MWM_WRITABLE_DIR directories, with
MWM_RESOURCES_DIR pointing to read-only map resources. Never use the user's
map directory as a test writable directory.

Verification for the selected core fixes:

- Built Organic Maps `2026.10.25-5` from `249a71c7` with the existing aarch64
  Sailfish SDK and Qt5.6. No new Qt or graphics interface was introduced.
- On JollaPhone2026: 7 async-router, 30 routing-manager, 17 download-validation
  and 5 BLAKE3 tests passed. The GeoClue lifecycle probe also passed. The map
  tests use the Qt event loop required by upstream's map_tests target.
- Test data, settings and HTTP fixtures stayed in unique private `/tmp`
  directories; no real maps were downloaded, deleted or rewritten by tests.
- Package SHA256:
  `8c80a7c39936e6653df20006508bd8a6bfce1c305952896b9f9bcb57e72a276f`.
- Library SHA256:
  `85a96ce795da4d17fbd343e66e687e06a44110c35c6252b94908963e5baebddb`.

The new map RPM is installed on JollaPhone2026. Normal application startup,
accepted idle export snapshots, rejection after process exit, and projected
map panning after phone display-off passed again. Sailplay remains 0.1.1-56.
The previous 2026.10.25-2 RPM is retained locally for rollback. Actual on-road
GPS guidance and the vehicle instrument display are not claimed by these tests.


## Projected planning layout (2026-10-26)

`organicmaps-planning-layout.patch` records the QML-only changes after 249a71c7.
Projected pages ignore the physical phone camera cutout and soft-key margins.
A new projected launch skips saved-route restoration without deleting the saved
route or changing ordinary phone startup. Route summaries wrap inside a bounded
panel, map buttons are smaller, and the duplicate bottom toolbar is hidden while
planning. URL activation requests focus without restoring physical fullscreen
geometry, preserving the assigned split viewport.

Organic Maps 2026.10.26-5 (222037a1) was installed on JollaPhone2026.
`tests/map_planning_layout_integration.py` passed with a private test profile,
a seeded saved route and external route URL: initial route restoration stayed
off, split surface 1138x688 and expanded surface 1780x720 both retained scale 1.
Captured frames were inspected for margins and overlapping toolbars. Normal
phone action-button sizes remain unchanged. This is device compositor validation;
on-road navigation and vehicle visual acceptance remain unverified.

RPM SHA256: b6f74f02d5e4e0dddb94469c743e7782a9b441c3a0c1c270009c9cf5140b4809.
Library SHA256: 2d90e3647415943d1562e2717176a228d2f6bb5bd815bb477855cfb9d445c0e2.


### Projected controls follow-up

Organic Maps 2026.10.26-6 (abcdd8c3) hides the top-left layer control and the
native renderer copyright-logo widget in projected mode. The existing projected
help-logo suppression remains in place. The navigation speed label uses km/h
for metric settings and mph for imperial settings; ordinary phone UI is unchanged.
RPM SHA256: 759aba9d67addb58600120e30317172eccc890b68c4ec6f87e5e2be2a603cf3e.
Installed library SHA256: bc82144ac406296e7bd7152924d3dfeeed815e486e15d385769dd37b91ee4e72.
