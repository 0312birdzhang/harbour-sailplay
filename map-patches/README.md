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
