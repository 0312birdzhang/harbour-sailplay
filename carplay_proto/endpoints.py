"""Endpoint catalog: ids, directions, and the typed schemas we have.

Only endpoints whose reference body is typed are declared here. Everything
else is usable through ``BodyBuilder(raw)`` / ``BodyReader.of`` without a
schema. Direction:

  MD  -- IPHONE_TO_ACCESSORY  -> we build and send
  ACC -- ACCESSORY_TO_IPHONE  -> we parse only
  BOTH -- BIDIRECTIONAL
"""

from . import body
from .body import Field
from . import types as t

IPHONE_TO_ACCESSORY = "IPHONE_TO_ACCESSORY"
ACCESSORY_TO_IPHONE = "ACCESSORY_TO_IPHONE"
BIDIRECTIONAL = "BIDIRECTIONAL"


class Endpoint(object):
    __slots__ = ("id", "name", "group", "direction", "fields")

    def __init__(self, id, name, group, direction, fields=()):
        self.id = id
        self.name = name
        self.group = group
        self.direction = direction
        self.fields = tuple(fields)

    def __repr__(self):
        return "Endpoint(0x{0:04x}, {1}, {2})".format(self.id, self.name,
                                                      self.direction)


IDENTIFICATION_INFORMATION = Endpoint(
    0x1d01, "IdentificationInformation", "Identification",
    ACCESSORY_TO_IPHONE,
    [
        Field(0, "name", t.STRING, required=True),
        Field(1, "modelIdentifier", t.STRING, required=True),
        Field(2, "manufacturer", t.STRING, required=True),
        Field(3, "serialNumber", t.STRING, required=True),
        Field(4, "firmwareVersion", t.STRING, required=True),
        Field(5, "hardwareVersion", t.STRING, required=True),
        Field(6, "MessagesSentByAccessory", t.U16_LIST, required=True),
        Field(7, "MessagesReceivedFromDevice", t.U16_LIST, required=True),
        Field(8, "powerProvidingCapability", t.U8),
        Field(9, "maximumCurrentDrawnFromDevice", t.U16),
        Field(10, "externalAccessoryProtocols", t.GROUP),
        Field(12, "currentLanguage", t.STRING, required=True),
        Field(13, "supportedLanguages", t.STRING_LIST, required=True),
        Field(16, "USBHostTransport", t.GROUP, children=[
            Field(0, "componentID", t.U16),
            Field(1, "name", t.STRING),
            Field(2, "isSupported", t.VOID),
            Field(3, "interfaceNumber", t.U8),
            Field(4, "isAvailable", t.VOID),
        ]),
        Field(17, "BluetoothTransport", t.GROUP, children=[
            Field(0, "componentID", t.U16),
            Field(1, "name", t.STRING),
            Field(2, "isSupported", t.VOID),
            Field(3, "bluetoothMAC", t.BYTES),
            Field(4, "transportName", t.STRING),
            Field(5, "isAvailable", t.VOID),
        ]),
        Field(20, "VehicleInformation", t.GROUP),
        Field(21, "VehicleStatus", t.GROUP),
        Field(22, "LocationInformation", t.GROUP),
        Field(24, "WirelessCarPlayTransport", t.GROUP, children=[
            Field(0, "componentID", t.U16),
            Field(1, "SSID", t.STRING),
            Field(2, "isSupported", t.VOID),
            Field(3, "transportIdentifier", t.U16),
            Field(4, "isAvailable", t.VOID),
            Field(5, "isEnabled", t.VOID),
        ]),
    ],
)

AUTHENTICATION_CERTIFICATE = Endpoint(
    0xaa01, "AuthenticationCertificate", "AccAuthentication",
    ACCESSORY_TO_IPHONE,
    [Field(0, "certificate", t.BYTES, required=True)],
)

AUTHENTICATION_RESPONSE = Endpoint(
    0xaa03, "AuthenticationResponse", "AccAuthentication",
    ACCESSORY_TO_IPHONE,
    [Field(0, "signatureResponse", t.BYTES, required=True)],
)

REQUEST_AUTHENTICATION_CHALLENGE_RESPONSE = Endpoint(
    0xaa02, "RequestAuthenticationChallengeResponse", "AccAuthentication",
    IPHONE_TO_ACCESSORY,
    [Field(0, "challenge", t.BYTES, required=True)],
)

CARPLAY_AVAILABILITY = Endpoint(
    0x4300, "CarPlayAvailability", "CarPlayConnectionRequest",
    IPHONE_TO_ACCESSORY,
    [
        Field(0, "wired", t.GROUP, children=[
            Field(0, "wiredAvailable", t.U8),
            Field(1, "usbIdentifier", t.STRING),
        ]),
        Field(1, "wireless", t.GROUP, children=[
            Field(0, "wirelessAvailable", t.U8),
            Field(1, "bluetoothIdentifier", t.STRING),
        ]),
        Field(2, "themeAssets", t.GROUP, children=[
            Field(0, "themeAssetsAvailable", t.U8),
        ]),
    ],
)

CARPLAY_START_SESSION = Endpoint(
    0x4301, "CarPlayStartSession", "CarPlayConnectionRequest",
    ACCESSORY_TO_IPHONE,
    [
        Field(0, "wired", t.GROUP, children=[
            Field(0, "wiredIP", t.STRING, repeatable=True),
            Field(1, "reserved", t.U32),
        ]),
        Field(1, "wireless", t.GROUP, children=[
            Field(0, "SSID", t.STRING),
            Field(1, "passphrase", t.STRING),
            Field(2, "channel", t.U8),
            Field(3, "wirelessIP", t.STRING, repeatable=True),
            Field(4, "securityType", t.U8),
        ]),
        Field(2, "airPlayPort", t.U32),
        Field(3, "deviceIdentifier", t.STRING),
        Field(4, "publicKey", t.STRING),
        Field(5, "sourceVersion", t.STRING),
        Field(6, "SDKVersion", t.STRING),
        Field(7, "clusterAsset", t.GROUP, children=[
            Field(0, "assetID", t.STRING),
            Field(1, "assetVersion", t.U32),
        ]),
        Field(8, "mutualAuth", t.U8),
    ],
)

WIFI_INFORMATION = Endpoint(
    0x5701, "WiFiInformation", "WiFiSharing",
    IPHONE_TO_ACCESSORY,
    [
        Field(0, "status", t.U8, required=True),
        Field(1, "securityType", t.U8),
        Field(2, "SSID", t.STRING),
        Field(3, "passphrase", t.STRING),
    ],
)

DEVICE_INFORMATION_UPDATE = Endpoint(
    0x4e09, "DeviceInformationUpdate", "DeviceNotifications",
    IPHONE_TO_ACCESSORY,
    [Field(0, "deviceName", t.STRING)],
)

DEVICE_LANGUAGE_UPDATE = Endpoint(
    0x4e0a, "DeviceLanguageUpdate", "DeviceNotifications",
    IPHONE_TO_ACCESSORY,
    [Field(0, "language", t.STRING)],
)

DEVICE_TIME_UPDATE = Endpoint(
    0x4e0b, "DeviceTimeUpdate", "DeviceNotifications",
    IPHONE_TO_ACCESSORY,
    [
        Field(0, "secondsSinceReferenceDate", t.U64),
        Field(1, "timeZoneOffsetMinutes", t.I16),
        Field(2, "daylightSavingsOffsetMinutes", t.I8),
    ],
)

DEVICE_UUID_UPDATE = Endpoint(
    0x4e0c, "DeviceUuidUpdate", "DeviceNotifications",
    IPHONE_TO_ACCESSORY,
    [Field(0, "deviceUUID", t.STRING)],
)

WIRELESS_CARPLAY_UPDATE = Endpoint(
    0x4e0d, "WirelessCarPlayUpdate", "DeviceNotifications",
    IPHONE_TO_ACCESSORY,
    [Field(0, "availability", t.U8, required=True)],
)

DEVICE_TRANSPORT_IDENTIFIER = Endpoint(
    0x4e0e, "DeviceTransportIdentifierNotification", "DeviceNotifications",
    IPHONE_TO_ACCESSORY,
    [
        Field(0, "bluetoothMAC", t.STRING),
        Field(1, "usbTransportIdentifier", t.STRING),
    ],
)

ALL = [
    IDENTIFICATION_INFORMATION,
    AUTHENTICATION_CERTIFICATE,
    AUTHENTICATION_RESPONSE,
    REQUEST_AUTHENTICATION_CHALLENGE_RESPONSE,
    CARPLAY_AVAILABILITY,
    CARPLAY_START_SESSION,
    WIFI_INFORMATION,
    DEVICE_INFORMATION_UPDATE,
    DEVICE_LANGUAGE_UPDATE,
    DEVICE_TIME_UPDATE,
    DEVICE_UUID_UPDATE,
    WIRELESS_CARPLAY_UPDATE,
    DEVICE_TRANSPORT_IDENTIFIER,
]

BY_ID = dict((ep.id, ep) for ep in ALL)


def send_ids():
    """Endpoint ids we must construct and send."""
    return [ep.id for ep in ALL if ep.direction == IPHONE_TO_ACCESSORY]


def recv_ids():
    """Endpoint ids we must parse."""
    return [ep.id for ep in ALL if ep.direction == ACCESSORY_TO_IPHONE]


def builder(endpoint, validate=True):
    """A schema-aware builder for a declared endpoint."""
    return body.BodyBuilder(
        fields=endpoint.fields, message_id=endpoint.id, validate=validate)


def raw_builder(message_id):
    """A builder for an undeclared or opaque endpoint."""
    return body.BodyBuilder(message_id=message_id, validate=False)
