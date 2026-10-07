"""Phone-side wireless CarPlay messages; credentials must not be logged."""
import ipaddress
import struct
from .wire import Frame, ProtocolError, parse_params, encode_param


def request_wifi_configuration():
    return Frame(0x5702, b'')


class WifiConfiguration:
    __slots__ = ('ssid', 'passphrase', 'security', 'channel')

    def __init__(self, ssid, passphrase, security, channel):
        self.ssid, self.passphrase = ssid, passphrase
        self.security, self.channel = security, channel

    def __repr__(self):
        return 'WifiConfiguration(credentials=<redacted>, security={}, channel={})'.format(
            self.security, self.channel)


def parse_wifi_configuration(frame):
    if frame.message_id != 0x5703:
        raise ProtocolError('expected AccessoryWiFiConfigurationInformation')
    fields = {}
    for parameter in frame.parameters():
        if parameter.id in fields:
            raise ProtocolError('duplicate Wi-Fi parameter')
        fields[parameter.id] = parameter.payload

    def string(pid, required=False):
        value = fields.get(pid)
        if value is None:
            if required:
                raise ProtocolError('missing SSID')
            return None
        if not value.endswith(b'\x00') or b'\x00' in value[:-1]:
            raise ProtocolError('invalid Wi-Fi string termination')
        try:
            return value[:-1].decode('utf-8')
        except UnicodeDecodeError:
            raise ProtocolError('invalid Wi-Fi string encoding')

    def scalar(pid):
        value = fields.get(pid)
        if value is None:
            return None
        if len(value) != 1:
            raise ProtocolError('invalid Wi-Fi scalar size')
        return value[0]

    ssid = string(1, required=True)
    if not 1 <= len(ssid.encode('utf-8')) <= 32:
        raise ProtocolError('invalid SSID length')
    # Retain unknown security values for diagnosis; do not assume WPA2.
    return WifiConfiguration(ssid, string(2), scalar(3), scalar(4))


class StartSession:
    def __init__(self, wifi, addresses, port, metadata):
        self.wifi, self.addresses, self.port, self.metadata = wifi, addresses, port, metadata

    def __repr__(self):
        return 'StartSession(addresses={!r}, port={}, credentials=<redacted>)'.format(self.addresses, self.port)

    def as_dict(self):
        return {'ssid': self.wifi.ssid, 'passphrase': self.wifi.passphrase,
                'security': self.wifi.security, 'channel': self.wifi.channel,
                'addresses': self.addresses, 'port': self.port, 'metadata': self.metadata}


def parse_start_session(frame, fallback_wifi=None):
    if frame.message_id != 0x4301:
        raise ProtocolError('expected CarPlayStartSession')
    fields = {}
    for parameter in frame.parameters():
        if parameter.id in fields:
            raise ProtocolError('duplicate start-session field')
        fields[parameter.id] = parameter.payload
    wireless = parse_params(fields.get(1, b''))
    config_fields, addresses = {}, []
    for parameter in wireless:
        if parameter.id == 3:
            value = parameter.payload
            if not value.endswith(b'\x00'):
                raise ProtocolError('unterminated IP address')
            try:
                addresses.append(str(ipaddress.ip_address(value[:-1].decode('ascii'))))
            except (ValueError, UnicodeError):
                raise ProtocolError('invalid start-session IP address')
        else:
            if parameter.id in config_fields:
                raise ProtocolError('duplicate start-session Wi-Fi field')
            config_fields[parameter.id] = parameter.payload
    mapped = {1: config_fields.get(0), 2: config_fields.get(1),
              3: config_fields.get(4), 4: config_fields.get(2)}
    if fallback_wifi:
        defaults = {1: fallback_wifi.ssid.encode('utf-8') + b'\x00',
                    2: None if fallback_wifi.passphrase is None else fallback_wifi.passphrase.encode('utf-8') + b'\x00',
                    3: None if fallback_wifi.security is None else bytes([fallback_wifi.security]),
                    4: None if fallback_wifi.channel is None else bytes([fallback_wifi.channel])}
        mapped = {key: value if value is not None else defaults[key] for key, value in mapped.items()}
    wifi = parse_wifi_configuration(Frame(0x5703, b''.join(
        encode_param(key, value) for key, value in mapped.items() if value is not None)))
    raw_port = fields.get(2)
    if raw_port is None or len(raw_port) != 4:
        raise ProtocolError('missing or invalid AirPlay port')
    port = struct.unpack('>I', raw_port)[0]
    if not 1 <= port <= 65535:
        raise ProtocolError('AirPlay port outside TCP range')
    # Metadata is opaque until its exact meaning is checked against live /info.
    metadata = {str(key): value.hex() for key, value in fields.items() if key not in (0, 1, 2)}
    return StartSession(wifi, addresses, port, metadata)
