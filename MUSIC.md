# Background music integration

Sailplay 0.1.1-41 activates the selected player's declared background service
instead of launching its desktop UI. Already-running MPRIS players are reused.
Opening the car music view prepares playback but never implicitly plays music;
the play button sends MPRIS Play after the remembered player becomes ready.

## Mconnect adapter

Source: `sfos-music/flutter-sailfishos/apps/mconnect`.
Package: `harbour-mconnect-1.5.0-8.aarch64.rpm`.

The desktop declares:

```ini
X-Sailplay-BackgroundService=org.sailfishos.Mconnect
```

The session D-Bus service runs `/usr/bin/harbour-mconnect --background`.
That mode initializes one shared ProviderContainer, authentication, storage,
PlayerNotifier, saved queue/position and MPRIS. It does not build the phone widget
tree. The existing embedder needs an EGL rendering context before starting, so
the host prepares it but defers the first phone buffer/presentation until the
user explicitly opens the phone app. This is not a launch-then-minimize trick.

A runtime flock and `org.sailfishos.Mconnect` control service serialize launches.
A normal phone launch sends Show to the existing process. MPRIS Raise then builds
the phone UI using the existing ProviderContainer; queue, track and playback
remain owned by the same core. Raise itself never starts music. The car controls
remain Sailplay QML controls reading and controlling that core through MPRIS.

Pinned embedder implementation inspected during development:
https://github.com/flutter-elinux/flutter-embedded-linux/blob/a98514bf569189f8534a887616dc5e33ca58b022/src/flutter/shell/platform/linux_embedded/flutter_elinux.cc

## Scope

Players without a background adapter are controlled when already running, but
Sailplay no longer forces their phone window open. The card explains that such
players need one manual launch on the phone.

Explicitly closing an attached Mconnect phone window still exits its host under
the current embedder lifecycle. Keeping playback alive after that explicit close
is a separate lifecycle task. Minimizing or locking the phone is different from
closing the app. This release does not claim the complete iOS lifecycle model.

## Verified deployment — 2026-10-22

Mconnect 1.5.0-8 and Sailplay 0.1.1-41 are installed on JollaPhone2026. Both
pass rpm -V and sailplay.service is active. Background cold start restores the
remembered track paused, repeat activation reuses the PID, and muted hardware
playback testing confirms advancing audio position. Hardware mutes were restored.
The real Sailplay controller activates the adapter without a foreground launch.

Phone lock-screen metadata/artwork/controls are visible. A Wayland trace shows
zero phone buffer attachments before explicit Show and consecutive buffers
after Show, while preserving the playback process. An unlocked-phone visual
check is pending because automatic approval rejected changing the lock state.
No lock settings were changed. Final state is background/paused, ready for use.

Mconnect RPM SHA256: 36e8f6dbfedd04ed8825c7f8e52afdea40862c464ce04a178fa5c4cf8ab55f76


Mconnect source is committed locally in the flutter-sailfishos checkout on
branch `sailplay-background-mconnect-20261022`, commit `136846d`. That checkout
still points to its third-party upstream remote; it was not pushed there.
