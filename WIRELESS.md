# Wireless implementation notes

Bluetooth pairs through the normal SailfishOS interface. Sailplay announces its phone-role services, receives or initiates RFCOMM, negotiates iAP2, verifies the observed accessory certificate pin and challenge, and consumes the head unit's Wi-Fi configuration and StartSession request.

The Wi-Fi helper uses the exact SSID received over iAP2. On the tested device, SAE association fails in the driver; the helper selects WPA2-PSK/RSN for the matching head-unit network. It supports saved networks in sustained mode, refreshes the received passphrase and preserves previously saved network profiles. An independent restoration process returns to the previous Wi-Fi after media activity stops.

AirPlay pairing establishes encrypted control and event channels. The standalone display pipeline owns its compositor, launcher and encoder; audio captures a private PulseAudio monitor rather than microphone input. HID reports create reverse touch input before compositor startup.

## Fixed connection lifecycle defects

A previous implementation rejected incoming RFCOMM channels whenever a worker for that device was still alive, producing BlueZ `Connection already active` errors. New channels now supersede the old channel; Bluetooth disconnection explicitly retires its worker and shuts down the socket. Profile connection retries no longer depend on receiving another Connected property change. Active media handovers suppress unnecessary outgoing connection attempts.

The installed service now has an Install section and is enabled by RPM installation. A complete device reboot followed by automatic connection remains a pending hardware validation.

Version 0.1.1-30 adds recovery for a distinct ConnMan registry inconsistency observed after head-unit restart: `GetServices` exposes a live Wi-Fi network with an interface, while `GetProperties` on the identical path exposes a detached saved object. `Connect` then returns `NoCarrier` immediately despite a fresh supplicant BSS. After two matching observations on an inactive target, Sailplay requests one ConnMan restart and lets the authenticated Bluetooth worker retry the handover. A boot-scoped marker limits recovery to once per daemon owner and at least five minutes between recoveries. Ordinary association failures, missing hotspots, active sessions and local-only connectivity do not trigger this restart. The mismatch, recovery request and subsequent network state are retained in the persistent Wi-Fi log. This handles the observed stale registry; the underlying ConnMan object lifecycle defect is not patched here.

The underlying retained-object defect is addressed separately by the source
patch and version-restricted system RPM documented in
[connman-patches/README.md](connman-patches/README.md). It unregisters a removed
service immediately, rather than waiting for its last asynchronous reference.
The daemon restart above remains a fallback for unpatched systems.

Version 0.1.1-32 keeps the CPU awake for at most 90 seconds during RFCOMM
profile discovery/connection, a real RFCOMM worker, Wi-Fi/AirPlay handover or manual reconnect, including teardown of the
old session. Idle Bluetooth listeners and Wi-Fi restoration timers do not
acquire this lease. Retries on the same Bluetooth link cannot renew its profile
wake window indefinitely. The setup deadline uses boot time so suspension cannot
extend it; setup and media leases have distinct tokens even within one
process. A setup lease expiring therefore cannot release the active video
session's CPU lease. Display and lock state are only read, never changed.

## Screen ownership lifecycle

The return tile sends modesChanged and shuts down the screen TCP socket before a screen-only TEARDOWN (type 110 and display UUID). Audio and control remain active. The native head-unit UI switch was confirmed in a device test. A subsequent head-unit requestUI caused fresh screen-only SETUP and RECORD, followed by IDR-started video transmission. Resume uses a new stream connection ID and encryption key. Earlier video-pause behavior only froze the picture and has been replaced. Version 0.1.0-17 was installed and the user confirmed the full tile return, head-unit CarPlay re-entry and restored-touch round trip.

Device-specific captures, certificates, pins, private identities and operational scripts are kept locally and are not repository fixtures.


## Split map viewport (0.1.1-33)

The private Silica adapter uses the client's live QtQuick Screen geometry,
which is updated by the per-client output mode, rather than feeding layout
back through a QWindow whose width and height can still be changing. It does
not modify the system Silica files. Map and expanded sizes continue to derive
from the negotiated output dimensions and scaled dock/card margins.

Home now hides content without resizing hidden apps. Dashboard selection goes
directly to the split layout, and restoring an app resizes only the selected
visible content. An unchanged viewport does not send another configure unless
the actual surface size still differs; that exception is necessary because a
request made before the Wayland shell role exists may be ignored. Replaced
hidden surfaces are hidden together with their clipping viewport.

Client frame callbacks run after framebuffer readback completes. A glFlush
alone submits rendering but does not establish completion of sampling from
imported client buffers.

Device validation used a 1920x720 output: split map 1126x688 and expanded app
1780x720. The live viewport probe passed initial split startup and five rounds
of hide/restore/dashboard switching. Organic Maps passed five real split/full
round trips without the observed uniform blank right-hand region. Forty
consecutive static map samples showed no large-area pixel changes in the
sampled map region. This is phone-side compositor validation; prolonged
in-vehicle rendering still needs observation.


Version 0.1.1-34 also handles the cold-start path which was still faulty in
0.1.1-33: content output negotiation waits until the first surface is mapped.
A newly started split-map client first receives a full-content configure;
after its buffer acknowledges that size it receives the actual card size.
These bootstrap buffers remain invisible. A client which already mapped a
full-content buffer goes straight to the requested viewport. Apps that ignore
configure remain fitted, with a one-second maximum initial visibility delay.
This is a native map startup compatibility measure, not a CarPlay video
resolution change. Both sizes derive from the actual negotiated output.

The 0.1.1-34 candidate was checked in a live head-unit media session, including
three complete Organic Maps process restarts through the normal launcher,
five viewport-probe round trips, five real map round trips and forty static
frame samples. Cold starts no longer showed the observed blank right-hand
map region. This does not establish prolonged driving-session stability.

## Honda Civic head unit

Observed with a Samsung Galaxy Note 10+ running Sailfish OS 5.2 against a
Honda Civic head unit. These are field notes, not a specification.

- The head unit has an RSA-1024 authentication certificate; the challenge
  signature verifies as PKCS#1 v1.5 over the 20-byte challenge with SHA-1.
- It alternates between two iAP2 identifications. The wireless CarPlay one
  sends only 0xaa06, 0x5703 and 0xea02, so CarPlayStartSession never arrives:
  the handover starts from the Wi-Fi credentials and AirPlay is found on the
  access point's gateway at port 7000. The other one offers Bluetooth
  component updates (0x4e01/0x4e03/0x4e05) and no Wi-Fi.
- Within seconds of the Wi-Fi handover starting it resets the RFCOMM iAP2
  link and drops Bluetooth. The advertiser relaunches the probe in place so
  the running projection survives.
- Video only shows with iOS-style screen packet headers (timestamp, display
  size and IDR flag on every packet).
- During projection it restarts iAP2 inside the AirPlay session: about once a
  second it sends an iAPSendMessage event whose 94-byte plist matches
  `{type: iAPSendMessage, params: {data: <iAP2 detect, 6 bytes>}}`. When
  nothing answered, it ended every session about 26 s after the first video
  frame. Sailplay now runs the same phone-side iAP2 link over this channel
  (detect, link sync, identification, authentication against the Bluetooth
  pin) and answers with iAPSendMessage commands. Not yet tested in the car.

### Factory-reset receiver diagnosis (0.1.1-49)

The 2026-10-23 LEVIN attempt reached Bluetooth/RFCOMM, but the receiver
closed the channel before iAP2 DETECT/authentication or Wi-Fi handover.
Re-registering the EIR markers during later service restarts did not resolve
that attempt. This does not establish a certificate or ConnMan failure.

The passive monitor now starts before our EIR registration, and persists
controller EIR writes (public 128-bit service UUIDs only), their command
completion status, and simple-pairing/authentication completion status in
`/var/lib/sailplay/logs/bluetooth-advertise.log`. A write request and successful
controller completion are separate evidence; neither proves reception by the
head unit. Device names, manufacturer payloads, link keys and pairing secrets
are excluded. This release adds diagnosis, not a verified fix for the missing
CarPlay icon; another receiver-side test is still required.


### Mixed WPA2/SAE target networks (0.1.1-51)

The matching head-unit supplicant network now automatically uses the existing
WPA2/RSN compatibility path when its configured key-management list contains
both WPA-PSK and SAE. Previously this path required `--force-wpa2`, which the
normal handover did not pass. WPA3-only, enterprise, WPA2-only and other SSIDs
are not changed. Reassociation still avoids an explicit Disconnect.

On the 2026-10-23 WILDLANDER attempt the accessory challenge verified and
StartSession arrived, but association was repeatedly rejected; ConnMan labelled
these failures invalid-key despite receiving the same passphrase as iAP2.
One observed WPA2 retry was still rejected. The user subsequently reported
192.168.43.124, but SSH was inaccessible, so completion of projection and the
causal effect of this change remain unverified.


The WILDLANDER subsequently completed Wi-Fi, screen/AAC SETUP and AirPlay iAP2
authentication but closed the session about four seconds after the first IDR.
0.1.1-51 restores the pre-PR screen packet header for receivers identifying as
Desay or WILDLANDER, while retaining the new header for Honda and other peers.
This is a compatibility experiment; a displayed image and stable session must
still be verified on the receiver. Screen reopen retains the selected profile.
