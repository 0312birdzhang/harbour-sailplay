# Wireless implementation notes

Bluetooth pairs through the normal SailfishOS interface. Sailplay announces its phone-role services, receives or initiates RFCOMM, negotiates iAP2, verifies the observed accessory certificate pin and challenge, and consumes the head unit's Wi-Fi configuration and StartSession request.

The Wi-Fi helper uses the exact SSID received over iAP2. On the tested device, SAE association fails in the driver; the helper selects WPA2-PSK/RSN for the matching head-unit network. It supports saved networks in sustained mode, refreshes the received passphrase and preserves previously saved network profiles. An independent restoration process returns to the previous Wi-Fi after media activity stops.

AirPlay pairing establishes encrypted control and event channels. The standalone display pipeline owns its compositor, launcher and encoder; audio captures a private PulseAudio monitor rather than microphone input. HID reports create reverse touch input before compositor startup.

## Fixed connection lifecycle defects

A previous implementation rejected incoming RFCOMM channels whenever a worker for that device was still alive, producing BlueZ `Connection already active` errors. New channels now supersede the old channel; Bluetooth disconnection explicitly retires its worker and shuts down the socket. Profile connection retries no longer depend on receiving another Connected property change. Active media handovers suppress unnecessary outgoing connection attempts.

The installed service now has an Install section and is enabled by RPM installation. A complete device reboot followed by automatic connection remains a pending hardware validation.

## Screen ownership lifecycle

The return tile sends modesChanged and shuts down the screen TCP socket before a screen-only TEARDOWN (type 110 and display UUID). Audio and control remain active. The native head-unit UI switch was confirmed in a device test. A subsequent head-unit requestUI caused fresh screen-only SETUP and RECORD, followed by IDR-started video transmission. Resume uses a new stream connection ID and encryption key. Earlier video-pause behavior only froze the picture and has been replaced. Version 0.1.0-17 was installed and the user confirmed the full tile return, head-unit CarPlay re-entry and restored-touch round trip.

Device-specific captures, certificates, pins, private identities and operational scripts are kept locally and are not repository fixtures.
