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
