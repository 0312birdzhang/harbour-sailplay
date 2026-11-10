# Background music integration

Sailplay activates the selected player's declared background service and reuses
its MPRIS player. Opening the car music view prepares the backend. The play
button sends MPRIS Play after the remembered player becomes ready.

## Mconnect adapter

The current implementation uses the native C++/Silica runtime in
`sfos-music/flutter-sailfishos/apps/mconnect`. The lifecycle integration produces
Mconnect 1.6.0-52 and Sailplay 0.1.1-62. Its source patch and checked SDK overlay
are published with Sailplay. [Integration](sdk/integrations/mconnect/README.md)

The desktop declares its existing activation identity and the media template.

```ini
X-Sailplay-BackgroundService=org.sailfishos.Mconnect
X-Sailplay-ApiVersion=1
X-Sailplay-Service=org.sailfishos.Mconnect
X-Sailplay-ObjectPath=/org/sailplay/v1/App
X-Sailplay-Presentation=template
X-Sailplay-Capabilities=media;
```

The session D-Bus service launches the native binary through its Sailjail
desktop identity with `--background`. It initializes one native storage,
authentication, playback and MPRIS core, restoring the queue and position paused.
Phone QML loads on Show or MPRIS Raise. Repeated activation uses the root D-Bus
owner and the same core.

Closing the phone window hides it, releases its QML tree and suspends phone
polling. A later Show rebuilds the presentation over the live runtime.
Sailplay holds a caller-owned car session while using the selected SDK player,
including an already-running MPRIS player. Switching car pages changes session
activity, while projection teardown or player replacement releases the lease.
The compatibility desktop identity resolves to the visible native launcher.

## Scope

Legacy players with a background declaration retain their activation path.
Already-running players remain available through MPRIS. The card identifies
players requiring an initial phone launch.

Car leases and ongoing playback, downloads, login calls, scans, lyric loading
and accepted core/bridge requests retain Mconnect. A paused leased core stays
paused. When the phone presentation, leases and work have ended, ten idle
seconds permit exit. The deadline callback checks current activity again.

Installed verification and remaining phone/car visual acceptance are recorded
in `todo.md`.

## Verified deployment — 2026-10-22

Mconnect 1.5.0-9 and Sailplay 0.1.1-42 are installed on JollaPhone2026. Both
pass rpm -V and sailplay.service is active. Background cold start restores the
remembered track paused, repeat activation reuses the PID, and muted hardware
playback testing confirms advancing audio position. Hardware mutes were restored.
The real Sailplay controller activates the adapter without a foreground launch.

Phone lock-screen metadata/artwork/controls are visible. A Wayland trace shows
zero phone buffer attachments before explicit Show and consecutive buffers
after Show, while preserving the playback process. An unlocked-phone visual
check is pending because automatic approval rejected changing the lock state.
No lock settings were changed. Final state is background/paused, ready for use.

Mconnect RPM SHA256: c2346ab180d6df6bc7efe8bc6405711132902de511978ac0184139bb27aa4077


Mconnect source is committed locally in the flutter-sailfishos checkout on
branch `sailplay-background-mconnect-20261022`, commits `136846d` and `82f09c4`. That checkout
still points to its third-party upstream remote; it was not pushed there.

## Music shortcut classification

Mconnect now declares `Categories=AudioVideo;Audio;Music;Player;`.
Sailplay also recognizes a desktop with its background-music declaration and
parses both scalar and list-valued Categories from QSettings. Previously the
missing classification sent Mconnect through the ordinary projected-app path,
which could leave the map visible instead of opening the native music view.
The device controller test switches from the dashboard using dockClicked and
confirms musicActive=true, dashboardActive=false and an empty currentApp.

Separate open issue: the pre-existing Mconnect native audio startup can select
maximum system volume on this phone (also reproduced using digital silence).
Experimental volume guards did not pass device checks and are not shipped.
The original audio implementation and packaged library were preserved exactly.

In Sailplay 0.1.1-43, a paused player retains its track metadata, artwork and
controls on the compact dashboard card. Only non-playing, non-paused states
show Not Playing. The device check confirmed a real paused Mconnect player
has idleCard=false, a track title and CanPlay=true without starting playback.

In 0.1.1-44, progress reads the player's authoritative MPRIS Position using
bounded asynchronous D-Bus queries. Re-emitting metadata on pause can reset
Amber.Mpris's cached position to zero even while the real position remains
unchanged. The audio-free device regression reproduced cache=0 with the
production UI correctly retaining 73.5 seconds. It also covers paused seeks to
zero and forward, resume, track changes, and rejection of stale track/service
replies. Position replies convert microseconds directly to UI seconds; duration
still converts Amber metadata milliseconds to seconds. Run
`tests/music_position_integration.py` on Sailfish as the session user.


## Car lyrics and control placement (0.1.1-57)

The split music card displays the current timed lyric; the expanded car music
page adds the next line. The song header, transport buttons, progress and lyrics
are centered together, with a bounded width on wide displays. Lyrics follow the
queried MPRIS position, including pause and seek, and clear on track/service
changes; late results for an old track are ignored.

`player-lyrics.py` uses MPRIS `xesam:asText` when provided. For Mconnect it can
also read its existing `mconnect.sqlite` lyrics cache in SQLite read-only mode,
matching the exact platform/song hash published as the MPRIS track ID. It does
not modify the database, activate the phone UI, download lyrics, or select
songs by potentially ambiguous titles. A song with no cached/exported lyrics
keeps the normal music controls; support is not universal across players.
LRC and decoded QRC/KRC timing are supported, as are cached per-song offsets.

Device validation parsed all six existing cached lyric entries and confirmed
landscape/portrait video startup. The Linux unittest suite passed 217 tests.
Actual car-side lyric appearance and the new control placement still need
visual confirmation in a projection session.
