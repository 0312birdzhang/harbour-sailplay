# Instrument navigation integration

## Stage 1: receiver field codecs and subscription diagnostics

Implemented, but not enabled as a navigation sender:

- `carplay_proto/navigation.py` encodes the route and maneuver fields traced
  through the HSAE receiver's event bridge.
- Each RFCOMM worker tracks authenticated `0x5200` start and `0x5203` stop
  requests. Existing persistent Bluetooth logs record the component ID and
  requested option IDs. Road names, destinations and packet bodies are not logged.
- Invalid navigation requests are logged without terminating an otherwise
  working projection session. State is reset with the RFCOMM worker.
- This stage sends no navigation frames and does not change the head unit,
  MCU/CAN configuration, or the installed map application.

The frame builders describe the receiver-consumed subset. They do not yet
claim full iAP2 route-guidance conformance: component/index fields, maneuver
lists, enum meanings and subscription option semantics need further validation.
Do not connect arbitrary Organic Maps enum values to these builders.

## Receiver evidence

Read-only inspection on 2026-10-22 used the image mounted in **Ubuntu-22.04**
at `/mnt/system`, not Ubuntu-24.04. The receiver library is:

```
/app/carplay/libs/libiAP2.so
SHA256 f7f28e152d1791a38c91ee4495297c5ea078bd6f30386dcde121413f21d9a29f
```

Analysis used `aarch64-linux-gnu-objdump`; no REA Evidence record was produced.
The connected REA tools were unavailable and the diagnostic CLI failed on a
missing npm-cache package.json. The saved disassembly and input digest remain
under the ignored `diagnostics/navigation/` directory. No receiver code ran.

The mounted `/app/carplay/ipodconfig.xml` declares
`RouteGuidanceDisplayComponent` ID 9, with 30-character text limits. This is
configuration evidence, not proof that the live receiver has subscribed.

| Message | Receiver function / ELF VA | Confirmed behavior |
| --- | --- | --- |
| `0x5200` | `startRouteGuidanceUpdate`, `0x33d88` | Parameter 0 is a two-byte big-endian component ID; parameters 1, 2, 3 have empty bodies. |
| `0x5201` | `routeGuidanceUpdate`, `0x33fd0` | Parses route state, maneuver state, road names, remaining time and display distances/units. |
| `0x5202` | `routeGuidanceManeuverInformation`, `0x34460` | Parses maneuver fields; the bridge forwards type, after-road name and driving side. |
| `0x5203` | `stopRouteGuidanceUpdate`, `0x347f8` | Component ID is stored with a native halfword store before encoding: this build emits little-endian bytes. |

The start/stop asymmetry is in this HSAE build, not a general iAP2 rule. The
subscription parser accepts the reversed stop value only if it matches the
currently active component; it does not learn a new component from a stop.

### Route fields used by the event bridge

| Parameter | Meaning | Encoding / receiver storage |
| --- | --- | --- |
| 1 | Route guidance state | One byte, object offset `0xc4` |
| 2 | Maneuver state | One byte, `0xc8` |
| 3 | Current road | NUL-terminated UTF-8, `0xcc` |
| 4 | Destination | NUL-terminated UTF-8, `0x14c` |
| 6 | Remaining time | Eight-byte big-endian integer seconds, `0x1d8` |
| 8 | Remaining distance display string | NUL-terminated UTF-8, `0x1e8` |
| 9 | Remaining distance display unit | One-byte enum, `0x268` |
| 11 | Next maneuver distance display string | NUL-terminated UTF-8, `0x278` |
| 12 | Next maneuver distance display unit | One-byte enum, `0x2f8` |

`AppleCarPlay` at `0x40aa00..0x40aa64` loads the time at event offset
`0x118` (the source structure begins at object offset `0xc0`) and divides it
into hours and minutes using integer arithmetic. The parser's use of a SIMD
register to copy those bytes does **not** make this an IEEE floating-point field.

### Maneuver fields used by the event bridge

| Parameter | Meaning | Receiver storage |
| --- | --- | --- |
| 3 | Maneuver type | One-byte enum, `0x404` |
| 4 | After-maneuver road | NUL-terminated UTF-8, `0x408` |
| 7 | Driving side | One-byte enum, `0x510` |

`AppleCarPlay` at `0x40a988..0x40a9a0` forwards these three fields. Parameter
1 is a different field and must not be used as the maneuver type.

Text builders apply a conservative 30 UTF-16-code-unit limit without splitting
supplementary Unicode characters, then encode UTF-8 for iAP2. The receiver's
meter module separately converts road text to at most 60 bytes of UTF-16LE;
that is not the encoding to send over iAP2.

## Stage 2: projected Organic Maps snapshot bridge

Implemented in the source patch under `map-patches/` and applied to the local
Organic Maps checkout. A rebuilt map application is required; the installed map
does not gain this interface just by upgrading Sailplay.

`carui` sets `SAILPLAY_NAVIGATION_EXPORT=1` for projected child processes. The
patched Organic Maps publishes only with that opt-in, under its user's
`$XDG_RUNTIME_DIR/sailplay-navigation/organicmaps-PID.json`. It does not export
normal phone launches by default. No route files are added to persistent logs.

The exporter uses an atomic `QSaveFile`, a 0700 directory and 0600 snapshot. It
includes schema version, PID, process start ticks, boot ID, app key, sequence,
boot-time update timestamp and a separate heartbeat. A one-second heartbeat
does not advance the navigation update timestamp. Normal destruction removes
the snapshot; crashes leave an expired file, which the reader rejects.

Raw active guidance includes:

- Organic Maps `CarDirection` integer, router type and roundabout exit number;
- `FollowingInfo.m_time` as integer remaining seconds;
- current/next road and destination;
- numeric next-turn and remaining distances, with explicit **Organic Maps**
  distance-unit enums (`0=m`, `1=km`, `2=ft`, `3=mi`). These are not iAP2 enums.

The source comes directly from `Routing::UpdateNavigation`, not QML text/icon
parsing. Idle, stopped, arrived and unavailable snapshots replace rather than
retain the previous guidance payload. This version does not distinguish every
recalculation or GPS-loss reason: invalid following info is `unavailable`, and
guidance without an update for ten seconds expires even if the app is alive.

`NavigationFeed` reads at most 32 files in the private directory, checks the
owning user, real executable and process start identity, rejects symlinks,
non-regular files, oversized JSON, invalid data and ambiguous concurrent sources.
Heartbeat age is limited to three seconds, and navigation age to ten seconds.
The authenticated RFCOMM worker polls once a second and logs only availability,
lifecycle state, raw turn enum and subscribed component. It still **does not
send navigation frames**: the iAP2 enum/component mapping remains a separate gate.

Validation on 2026-10-22:

- Nine Linux snapshot/reader tests and four existing RFCOMM tests passed.
- The new exporter and its standalone QtCore probe compiled for Sailfish aarch64.
- The standalone probe ran successfully as the phone session user, verifying
  opt-in, Unicode snapshot writing, heartbeat/update separation, file permissions,
  terminal-state replacement and cleanup. It did not start a map or alter services.
- The full Organic Maps application has not been rebuilt or installed; actual
  route/GPS-to-snapshot behavior and instrument navigation are not yet verified.

## Remaining stages

1. Recover the enum meanings and remaining component/index requirements;
   compare with an iPhone navigation start/turn/recalculation/arrival trace.
2. Rebuild/install the patched Organic Maps and validate route start, live
   position updates, recalculation, cancellation and arrival snapshots.
3. Connect the snapshot to the authenticated, subscribed RFCOMM worker.
   Serialize sends through its existing acknowledged outgoing queue. Bound and
   coalesce pending updates; preserve turn-before-route ordering where required
   by the receiver's cached fields. Stop and expire stale state on app/session
   termination, and restore a snapshot after an accepted re-subscription.
4. Verify reception through the stock HSAE route signals and
   `sendMeterLinkInfo` command `0x1e040c`, then verify actual vehicle instrument
   rendering. A bench receiver or successful MCU method call is insufficient
   evidence of vehicle instrument output.

Send remaining duration, not phone-local absolute ETA: this HSAE meter path
adds duration to its own local clock. Incorrect receiver time can therefore
affect the displayed arrival time independently of route data.

## Tests

```
python3 -m unittest discover -s tests -p 'test_navigation_unittest.py' -v
python3 -m unittest discover -s tests -p 'test_navigationfeed_unittest.py' -v
```

These are offline codec/subscription tests, not a real navigation session.
