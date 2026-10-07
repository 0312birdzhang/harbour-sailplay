# Wireless implementation notes

Bluetooth pairs through the normal SailfishOS interface. Sailplay announces its phone-role services, receives or initiates RFCOMM, negotiates iAP2, verifies the observed accessory certificate pin and challenge, and consumes the head unit's Wi-Fi configuration and StartSession request.

The Wi-Fi helper uses the exact SSID received over iAP2. On the tested device, SAE association fails in the driver; the helper selects WPA2-PSK/RSN for the matching head-unit network. It supports saved networks in sustained mode, refreshes the received passphrase and preserves previously saved network profiles. An independent restoration process returns to the previous Wi-Fi after media activity stops.

AirPlay pairing establishes encrypted control and event channels. The standalone display pipeline owns its compositor, launcher and encoder; audio captures a private PulseAudio monitor rather than microphone input. HID reports create reverse touch input before compositor startup.

## Fixed connection lifecycle defects

A previous implementation rejected incoming RFCOMM channels whenever a worker for that device was still alive, producing BlueZ `Connection already active` errors. New channels now supersede the old channel; Bluetooth disconnection explicitly retires its worker and shuts down the socket. Profile connection retries no longer depend on receiving another Connected property change. Active media handovers suppress unnecessary outgoing connection attempts.

The installed service now has an Install section and is enabled by RPM installation. A complete device reboot followed by automatic connection remains a pending hardware validation.

## Screen ownership limitation

The tested head unit acknowledges the modesChanged message used by the return tile, but this did not demonstrate a switch to its native UI. Pausing video after that acknowledgement froze the displayed Sailplay frame. That candidate was reverted. The return tile currently displays a limitation notice; native screen switching requires further protocol and hardware validation.

Device-specific captures, certificates, pins, private identities and operational scripts are kept locally and are not repository fixtures.
