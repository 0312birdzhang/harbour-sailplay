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
