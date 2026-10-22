#!/usr/bin/env python3
"""Temporary BlueZ phone-role RFCOMM/iAP2 probe, not a CarPlay sender yet.

Requires Sailfish python3-dbus and python3-gobject. Pair using system UI first.
No Wi-Fi changes, pairing-agent replacement or persistent adapter changes.
"""
import argparse
import hashlib
import logging
import os
import socket
import sys
import threading
import time
import uuid
import struct
import json
import subprocess
import fcntl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from carplay_proto.bluezadapter import select_adapter, adapter_name, select_head_unit, previous_head_unit, remember_head_unit
from carplay_proto.projectionpower import with_connection_power, ProfileConnectionPower
from carplay_proto.iap2link import (ACK, DETECT, EAK, RST, SYN, Decoder,
                                   Packet, encode, parse_synchronization,
                                   synchronization)
from carplay_proto.wire import Frame, Framer, encode_param, parse_params
from carplay_proto.accessoryauth import PinnedAccessory, paired_accessory
from carplay_proto.wireless import (parse_wifi_configuration,
                                    peer_supports_wifi_configuration_request,
                                    request_wifi_configuration,
                                    parse_start_session, StartSession)

PHONE_UUID = '00000000-deca-fade-deca-deafdecacafe'
ACCESSORY_UUID = '00000000-deca-fade-deca-deafdecacaff'
IAP_V2_UUID = '02030302-1d19-415f-86f2-22a2106a0a77'
PROFILE_PATH = '/org/sailplay/wireless_phone'


def text_value(payload):
    return payload.split(b'\x00', 1)[0].decode('utf-8', 'replace')


def payload_hex(payload, limit=512):
    suffix = '...' if len(payload) > limit else ''
    return payload[:limit].hex() + suffix


def parse_ea_protocols(frame):
    protocols = []
    for parameter in frame.parameters():
        if parameter.id != 10:
            continue
        try:
            nested = {item.id: item.payload for item in parse_params(parameter.payload)}
        except ValueError:
            logging.warning('invalid EA protocol group=%d payload=%s',
                            parameter.id, payload_hex(parameter.payload))
            continue
        identifier = nested.get(0, b'')[:1]
        if not identifier:
            continue
        name = text_value(nested.get(1, b''))
        protocols.append((identifier[0], name))
        logging.info('EA protocol id=%d name=%r', identifier[0], name)
    return protocols


def parse_component_ids(frame):
    identifiers = []
    for parameter in frame.parameters():
        if parameter.id != 0:
            continue
        if len(parameter.payload) != 2:
            logging.warning('invalid Bluetooth component identifier payload=%s',
                            payload_hex(parameter.payload))
            continue
        identifiers.append(struct.unpack('>H', parameter.payload)[0])
    return identifiers


def service_record(channel):
    if not 1 <= channel <= 30:
        raise ValueError('invalid RFCOMM channel')
    return '''<?xml version="1.0"?>
<record>
 <attribute id="0x0001"><sequence><uuid value="%s"/><uuid value="%s"/></sequence></attribute>
 <attribute id="0x0004"><sequence>
  <sequence><uuid value="0x0100"/></sequence>
  <sequence><uuid value="0x0003"/><uint8 value="%d"/></sequence>
 </sequence></attribute>
 <attribute id="0x0005"><sequence><uuid value="0x1002"/></sequence></attribute>
 <attribute id="0x0009"><sequence><sequence>
  <uuid value="0x1101"/><uint16 value="0x0102"/>
 </sequence></sequence></attribute>
 <attribute id="0x0100"><text value="Wireless iAP v2"/></attribute>
</record>''' % (PHONE_UUID, IAP_V2_UUID, channel)


def retire_worker(worker):
    """A new BlueZ channel supersedes the previous channel for that device."""
    if worker is None:
        return
    stop, thread, sock = worker
    stop.set()
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    thread.join(1)
    if thread.is_alive():
        logging.warning('old RFCOMM worker still unwinding; socket has been shut down')


def media_active(path='/run/sailplay-media.lock'):
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True
    finally:
        os.close(fd)


HANDOVER_HEARTBEAT = '/tmp/sailplay-handover-heartbeat'


def touch_handover_heartbeat():
    """Keep the independent restore worker from reviving the old network."""
    try:
        os.utime(HANDOVER_HEARTBEAT, None)
    except FileNotFoundError:
        descriptor = os.open(HANDOVER_HEARTBEAT, os.O_WRONLY | os.O_CREAT |
                             os.O_NOFOLLOW, 0o600)
        os.close(descriptor)


def probe(sock, stop, duration, certificate_out=None, accessory_key=None,
          announce_wireless=False, local_address=None, session_out=None, wifi_handover=False,sustained=False,
          local_name='SailfishOS', paired_pin_path=None, on_authenticated=None,
          transport='bluetooth'):
    handover_started = False
    handover_command = None
    def retry_handover():
        command = list(handover_command)
        command[1] = '--unit=sailplay-handover-{}-{}'.format(os.getpid(), time.monotonic_ns())
        logging.info('Authenticated Bluetooth remains connected; retrying retired Wi-Fi/AirPlay handover')
        try:
            subprocess.run(command, check=True, timeout=10)
        except (subprocess.SubprocessError, OSError):
            logging.exception('Wi-Fi/AirPlay handover retry launch failed')
    from carplay_proto.wifiretry import HandoverRetry
    handover_retry = HandoverRetry(media_active, retry_handover)

    def write_session(start):
        descriptor = os.open(session_out, os.O_WRONLY | os.O_CREAT |
                             os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            session_data = start.as_dict()
            session_data['device_name'] = local_name
            session_data['bluetooth_address'] = local_address
            json.dump(session_data, output)

    def start_handover(trigger):
        nonlocal handover_started, handover_command
        if not wifi_handover or handover_started:
            return
        handover_command=['systemd-run', '--unit=sailplay-handover-{}-{}'.format(os.getpid(),time.monotonic_ns()),
            sys.executable, os.path.join(os.path.dirname(__file__), 'wifi-session-probe.py'),
            '--connect', '--direct-passphrase',
            '--restore-after', '90', '--log-file', '/tmp/sailplay-wifi-probe.log']
        if sustained:
            handover_command.append('--sustained')
        else:
            handover_command.append('--trace-supplicant')
        subprocess.run(handover_command,check=True)
        handover_started = True
        touch_handover_heartbeat()
        handover_retry.arm()
        logging.info('%s triggered independent Wi-Fi/AirPlay handover', trigger)

    decoder, csm = Decoder(), Framer()
    deadline = time.monotonic() + duration if duration else float('inf')
    sync_at = 0
    peer_syn = False
    local_syn_acked = False
    last_rx = None
    session = None
    negotiated = False
    outgoing = []
    pending = None
    sequence = 0
    retry_at = 0
    retries = 0
    detection_deadline = time.monotonic() + 15
    authenticator = None
    authenticated = False
    peer_received_messages = set()
    ea_protocols = []
    wifi_config = None
    sock.settimeout(0.2)
    try:
        authenticator = PinnedAccessory(accessory_key) if accessory_key else None
        while not stop.is_set() and time.monotonic() < deadline:
            handover_retry.poll()
            if handover_started:
                touch_handover_heartbeat()
            now = time.monotonic()
            if not negotiated and now >= detection_deadline:
                raise ValueError('iAP2 handshake timeout; release RFCOMM for retry')
            if sync_at and not local_syn_acked and now >= sync_at:
                sock.sendall(encode(Packet(SYN | ACK, 0, last_rx, 0, sync_payload)))
                sync_at = now + 1
            if negotiated and pending is None and outgoing:
                sequence = (sequence + 1) & 255
                frame = outgoing.pop(0)
                logging.info('CSM tx message=0x%04x body_bytes=%d', frame.message_id, len(frame.body))
                pending = Packet(ACK, sequence, last_rx, session, frame.encoded())
                retries = 0
                retry_at = 0
            if pending is not None and now >= retry_at:
                if retries >= 5:
                    raise ValueError('control packet acknowledgement timeout')
                sock.sendall(encode(pending._replace(acknowledgement=last_rx)))
                retries += 1
                retry_at = now + 1
            try:
                raw = sock.recv(4096)
            except socket.timeout:
                continue
            if not raw:
                break
            for packet in decoder.feed(raw):
                if transport == 'airplay':
                    if packet == DETECT:
                        logging.info('link rx DETECT')
                    else:
                        logging.info('link rx control=0x%02x seq=%d ack=%d session=%s bytes=%d',
                                     packet.control, packet.sequence, packet.acknowledgement,
                                     packet.session, len(packet.payload or b''))
                if packet == DETECT:
                    if not sync_at:
                        logging.info('peer iAP2 detection confirmed')
                        # Phone is the iAP2 host: echo DETECT and wait for accessory SYN.
                        sock.sendall(DETECT)
                    elif transport == 'airplay':
                        # The head unit dropped this link and is starting over;
                        # end it so the tunnel answers the next DETECT afresh.
                        raise ValueError('peer restarted the iAP2 link (DETECT after sync)')
                    continue
                if packet.control & RST:
                    raise ValueError('peer reset link')
                if packet.control & SYN:
                    limits, sessions = parse_synchronization(packet.payload or b'')
                    logging.info('peer SYN limits=%s sessions=%s', limits, sessions)
                    controls = [s[0] for s in sessions if s[1] == 0 and s[2] in (1, 2)]
                    if not controls:
                        raise ValueError('peer has no compatible control session')
                    session = controls[0]
                    peer_syn = True
                    last_rx = packet.sequence
                    sync_payload = packet.payload
                    sock.sendall(encode(Packet(SYN | ACK, 0, last_rx, 0, sync_payload)))
                    sync_at = time.monotonic() + 1
                if sync_at and packet.control & ACK and packet.acknowledgement == 0:
                    local_syn_acked = True
                if pending is not None and packet.control & ACK and packet.acknowledgement == pending.sequence:
                    pending = None
                if peer_syn and local_syn_acked and not negotiated:
                    negotiated = True
                    outgoing.append(Frame(0x1d00, b''))
                    logging.info('iAP2 link negotiated; requesting accessory identification')
                if packet.control & EAK:
                    logging.warning('peer extended ACK; probe has no queued control packets')
                if packet.control & ~(ACK) == 0 and packet.payload is not None:
                    if not negotiated:
                        raise ValueError('data before synchronization completed')
                    if packet.sequence == ((last_rx + 1) & 255):
                        last_rx = packet.sequence
                        if packet.session == session:
                            for frame in csm.offer(packet.payload):
                                # Never log Wi-Fi credentials or authentication bodies.
                                logging.info('CSM rx message=0x%04x body_bytes=%d',
                                             frame.message_id, len(frame.body))
                                if transport == 'airplay' and frame.message_id not in (
                                        0xaa01, 0xaa03, 0x5703, 0x4301):
                                    # Bodies identify what the head unit expects
                                    # next; credentials and auth are never logged.
                                    logging.info('CSM rx body=%s', payload_hex(frame.body, 4096))
                                if frame.message_id == 0x1d01:
                                    identity = {}
                                    for parameter in frame.parameters():
                                        if parameter.id in (0, 1, 2):
                                            identity[parameter.id] = text_value(parameter.payload)
                                        elif parameter.id in (6, 7):
                                            if len(parameter.payload) % 2:
                                                raise ValueError('invalid supported-message list')
                                            ids = list(struct.unpack('>' + 'H' * (len(parameter.payload) // 2), parameter.payload))
                                            logging.info('accessory %s message IDs=%s',
                                                         'sent' if parameter.id == 6 else 'received',
                                                         ','.join('0x%04x' % value for value in ids))
                                            if parameter.id == 7:
                                                peer_received_messages = set(ids)
                                    logging.info('accessory identity name=%r model=%r manufacturer=%r',
                                                 identity.get(0, ''), identity.get(1, ''), identity.get(2, ''))
                                    logging.info('identification parameter ids=%s',
                                                 [(parameter.id, len(parameter.payload))
                                                  for parameter in frame.parameters()])
                                    ea_protocols = parse_ea_protocols(frame)
                                    outgoing.extend([Frame(0x1d02, b''), Frame(0xaa00, b'')])
                                elif frame.message_id == 0xaa01:
                                    parameters = frame.parameters()
                                    certificates = [p.payload for p in parameters if p.id == 0]
                                    if len(certificates) != 1 or not certificates[0]:
                                        raise ValueError('invalid accessory certificate message')
                                    certificate = certificates[0]
                                    logging.info('accessory certificate sha256=%s bytes=%d',
                                                 hashlib.sha256(certificate).hexdigest(), len(certificate))
                                    if certificate_out:
                                        descriptor = os.open(certificate_out, os.O_WRONLY | os.O_CREAT |
                                                             os.O_TRUNC | os.O_NOFOLLOW, 0o600)
                                        with os.fdopen(descriptor, 'wb') as output:
                                            output.write(certificate)
                                    if paired_pin_path:
                                        authenticator = paired_accessory(certificate, paired_pin_path, authenticator)
                                    if authenticator:
                                        challenge = authenticator.begin(certificate)
                                        outgoing.append(Frame(0xaa02, encode_param(0, challenge)))
                                        logging.info('accessory certificate selected; random challenge queued')
                                    else:
                                        logging.info('accessory certificate received; challenge verification disabled')
                                elif frame.message_id == 0xaa03:
                                    if not authenticator or authenticated:
                                        raise ValueError('unexpected authentication response')
                                    signatures = [p.payload for p in frame.parameters() if p.id == 0]
                                    if len(signatures) != 1:
                                        raise ValueError('invalid authentication response')
                                    authenticator.verify(signatures[0])
                                    authenticated = True
                                    if on_authenticated:
                                        on_authenticated()
                                    outgoing.append(Frame(0xaa05, b''))
                                    if announce_wireless:
                                        if not local_address:
                                            raise ValueError('missing local Bluetooth transport identity')
                                        device_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'org.sailplay:' + local_address)).upper()
                                        outgoing.extend([
                                            Frame(0x4e0c, encode_param(0, device_id.encode('ascii') + b'\x00')),
                                            Frame(0x4e09, encode_param(0, local_name.encode('utf-8') + b'\x00')),
                                            Frame(0x4e0e, encode_param(0, local_address.encode('ascii') + b'\x00')),
                                            Frame(0x4e0d, encode_param(0, b'\x01')),
                                        ])
                                        if 0x4300 in peer_received_messages:
                                            # Existing xcertplay receiver's grouped availability layout.
                                            wired = encode_param(0, b'\x00')
                                            wireless = (encode_param(0, b'\x01') +
                                                        encode_param(1, local_address.encode('ascii') + b'\x00'))
                                            outgoing.append(Frame(0x4300, encode_param(0, wired) +
                                                                   encode_param(1, wireless)))
                                            logging.info('HU advertises 4300; diagnostic grouped CarPlayAvailability queued')
                                        logging.info('DIAGNOSTIC wireless capability notification queued; no media sender yet')
                                    if transport == 'airplay':
                                        # Wi-Fi is already up; only the link and
                                        # authentication are needed here.
                                        logging.info('iAP2 over AirPlay: accessory authenticated')
                                        for frame in device_notifications(local_name, local_address,
                                                                          peer_received_messages):
                                            outgoing.append(frame)
                                            logging.info('device notification queued message=0x%04x',
                                                         frame.message_id)
                                    else:
                                        for protocol_id, protocol_name in ea_protocols:
                                            if 0xea00 not in peer_received_messages:
                                                logging.info('accessory does not receive 0xea00; skipping EA protocol=%d name=%r',
                                                             protocol_id, protocol_name)
                                                continue
                                            outgoing.append(Frame(0xea00, encode_param(0, bytes([protocol_id])) +
                                                                  encode_param(1, struct.pack('>H', protocol_id))))
                                            logging.info('EA session requested protocol=%d session=%d name=%r',
                                                         protocol_id, protocol_id, protocol_name)
                                        if peer_supports_wifi_configuration_request(peer_received_messages):
                                            outgoing.append(request_wifi_configuration())
                                            logging.info('pinned accessory challenge signature VERIFIED; requesting Wi-Fi config')
                                        else:
                                            logging.info('pinned accessory challenge signature VERIFIED; '
                                                         'waiting for notification-driven Wi-Fi handover '
                                                         '(peer does not advertise 0x5702)')
                                elif frame.message_id == 0x4e01:
                                    logging.info('Bluetooth component information body=%s', payload_hex(frame.body))
                                elif frame.message_id == 0x4e03:
                                    component_ids = parse_component_ids(frame)
                                    logging.info('Bluetooth connection updates requested components=%s body=%s',
                                                 component_ids, payload_hex(frame.body))
                                    for component_id in component_ids:
                                        profiles = encode_param(7, b'')
                                        outgoing.append(Frame(0x4e04,
                                                              encode_param(0, struct.pack('>H', component_id)) +
                                                              encode_param(1, profiles)))
                                        logging.info('Bluetooth connection update queued component=%d profiles=iAP2Link',
                                                     component_id)
                                elif frame.message_id == 0x4e05:
                                    logging.info('Bluetooth connection updates stopped body=%s', payload_hex(frame.body))
                                elif frame.message_id == 0xea02:
                                    bundle = ''
                                    for parameter in frame.parameters():
                                        if parameter.id == 0:
                                            bundle = text_value(parameter.payload)
                                    logging.info('accessory app launch requested bundle=%r body=%s',
                                                 bundle, payload_hex(frame.body))
                                elif frame.message_id == 0xea03:
                                    logging.info('EA session status body=%s', payload_hex(frame.body))
                                elif frame.message_id == 0x5703:
                                    if not authenticated:
                                        raise ValueError('Wi-Fi credentials arrived before authentication')
                                    config = parse_wifi_configuration(frame)
                                    wifi_config = config
                                    logging.info('accessory Wi-Fi configuration received: %r', config)
                                    # Some head units (Honda) never send
                                    # CarPlayStartSession over Bluetooth; they
                                    # expect the phone to join their access point
                                    # and find AirPlay on the default port.
                                    if session_out:
                                        write_session(StartSession(config, [], 7000, {}))
                                        start_handover('Wi-Fi configuration')
                                elif frame.message_id == 0x4301:
                                    if not authenticated:
                                        raise ValueError('StartSession before authentication')
                                    start = parse_start_session(frame, wifi_config)
                                    logging.info('parsed CarPlay StartSession: %r', start)
                                    if session_out:
                                        write_session(start)
                                        start_handover('StartSession')
                    elif packet.sequence != last_rx:
                        # A stale window means this RFCOMM link is poisoned;
                        # exit and let the advertiser relaunch a clean probe.
                        raise ValueError('out-of-order packet; restarting probe')
                    sock.sendall(encode(Packet(ACK, 0, last_rx, 0, None)))
        logging.info('probe ended; checksum errors=%d', decoder.errors)
    except (OSError, ValueError):
        logging.exception('probe failed')
    finally:
        sock.close()


def device_notifications(local_name, local_address, received_message_ids):
    """Device updates an iPhone sends once the accessory is authenticated.

    Only messages the accessory lists as received are sent; an empty list
    (no identification parameters) sends all of them.
    """
    frames = [Frame(0x4e09, encode_param(0, local_name.encode('utf-8') + b'\x00'))]
    if local_address:
        device_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'org.sailplay:' + local_address)).upper()
        frames[:0] = [Frame(0x4e0c, encode_param(0, device_id.encode('ascii') + b'\x00'))]
        frames.append(Frame(0x4e0e, encode_param(0, local_address.encode('ascii') + b'\x00')))
    frames.append(Frame(0x4e0d, encode_param(0, b'\x01')))
    if received_message_ids:
        frames = [frame for frame in frames if frame.message_id in received_message_ids]
    return frames


def airplay_link(sock, stop, local_name='SailfishOS', local_address=None,
                 accessory_directory='/var/lib/sailplay/accessories'):
    """Run the phone side of an iAP2 link tunnelled through AirPlay.

    Authenticates the accessory against the pin saved for the last head unit
    over Bluetooth. No Wi-Fi request or handover: Wi-Fi is already in use.
    """
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                            format='iAP tunnel: %(message)s')
    device = previous_head_unit()
    pin_path = (os.path.join(accessory_directory, device.rsplit('/', 1)[1] + '.json')
                if device else None)
    logging.info('starting over AirPlay; accessory pin=%s', pin_path)
    probe(sock, stop, 0, local_name=local_name, local_address=local_address,
          paired_pin_path=pin_path, transport='airplay')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', type=int, default=19)
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--sustained', action='store_true')
    parser.add_argument('--device', help='paired BlueZ Device1 path to connect to')
    parser.add_argument('--certificate-out', help='save public accessory certificate for offline verification')
    parser.add_argument('--accessory-key', help='offline-extracted pinned accessory public-key JSON')
    parser.add_argument('--announce-wireless', action='store_true',
                        help='diagnostic capability announcement; media sender is not implemented')
    parser.add_argument('--session-out', help='write private StartSession parameters to a mode-0600 file')
    parser.add_argument('--wifi-handover', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.channel <= 30 or not 0 <= args.seconds <= 3600:
        parser.error('channel must be 1..30; seconds must be 0..3600 (0 is continuous)')
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    objects = dbus.Interface(bus.get_object('org.bluez', '/'),
                             'org.freedesktop.DBus.ObjectManager').GetManagedObjects()
    adapter, args.device = select_adapter(objects, args.device)
    args.device = select_head_unit(objects, args.device, previous_head_unit())
    if args.device and objects.get(args.device, {}).get('org.bluez.Device1', {}).get('Connected'):
        remember_head_unit(args.device)
    adapter, args.device = select_adapter(objects, args.device)
    logging.info('using Bluetooth adapter %s, target %s', adapter, args.device)
    def snapshot(objects):
        for path, interfaces in objects.items():
            if 'org.bluez.Adapter1' in interfaces:
                props = interfaces['org.bluez.Adapter1']
                logging.info('adapter snapshot path=%s state=%s', path,
                             {k: str(props.get(k)) for k in ('Alias', 'Powered', 'Connectable', 'Discoverable', 'Pairable', 'Class', 'UUIDs')})
            elif 'org.bluez.Device1' in interfaces:
                props = interfaces['org.bluez.Device1']
                logging.info('device snapshot path=%s state=%s', path,
                             {k: str(props.get(k)) for k in ('Alias', 'Paired', 'Connected', 'ServicesResolved', 'UUIDs')})
    snapshot(objects)
    local_address = str(dbus.Interface(bus.get_object('org.bluez', adapter),
                            'org.freedesktop.DBus.Properties').Get('org.bluez.Adapter1', 'Address'))
    loop = GLib.MainLoop()
    workers = {}
    profile_power = ProfileConnectionPower()

    class Profile(dbus.service.Object):
        @dbus.service.method('org.bluez.Profile1', in_signature='', out_signature='')
        def Release(self):
            logging.warning('BlueZ released CarPlay profile')
            loop.quit()

        @dbus.service.method('org.bluez.Profile1', in_signature='oha{sv}', out_signature='')
        def NewConnection(self, device, fd, properties):
            sock = socket.socket(fileno=fd.take())
            previous = workers.pop(str(device), None)
            if previous:
                logging.info('replacing previous RFCOMM channel for %s', device)
                retire_worker(previous)
            stop = threading.Event()
            certificate_directory = '/var/lib/sailplay/accessories'
            os.makedirs(certificate_directory, mode=0o700, exist_ok=True)
            certificate_path = os.path.join(certificate_directory, str(device).rsplit('/', 1)[1] + '.der')
            device_props = dbus.Interface(bus.get_object('org.bluez', device),
                                         'org.freedesktop.DBus.Properties').GetAll('org.bluez.Device1')
            pin_path = certificate_path[:-4] + '.json' if device_props.get('Paired') else None
            adapter_props = dbus.Interface(bus.get_object('org.bluez', adapter),
                                          'org.freedesktop.DBus.Properties').GetAll('org.bluez.Adapter1')
            thread = threading.Thread(target=with_connection_power, args=(probe, sock, stop, args.seconds,
                                                         args.certificate_out or certificate_path, args.accessory_key,
                                                         args.announce_wireless, local_address, args.session_out, args.wifi_handover,args.sustained,
                                                         adapter_name(adapter_props), pin_path,
                                                         (lambda: remember_head_unit(str(device))) if pin_path else None))
            workers[str(device)] = (stop, thread, sock)
            thread.start()
            logging.info('RFCOMM connected device=%s', device)

        @dbus.service.method('org.bluez.Profile1', in_signature='o', out_signature='')
        def RequestDisconnection(self, device):
            logging.info('BlueZ requested RFCOMM disconnection device=%s', device)
            worker = workers.pop(str(device), None)
            retire_worker(worker)

    profile = Profile(bus, PROFILE_PATH)
    client_profile = Profile(bus, PROFILE_PATH + '_client')
    manager = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'),
                             'org.bluez.ProfileManager1')
    manager.RegisterProfile(PROFILE_PATH, PHONE_UUID, {
        'Name': 'Sailplay wireless phone probe', 'Role': 'server',
        'Channel': dbus.UInt16(args.channel), 'RequireAuthentication': True,
        'RequireAuthorization': False, 'ServiceRecord': service_record(args.channel),
    })
    try:
        manager.RegisterProfile(PROFILE_PATH + '_client', ACCESSORY_UUID, {
            'Role': 'client', 'RequireAuthentication': True,
        })
    except Exception:
        manager.UnregisterProfile(PROFILE_PATH)
        raise
    if args.device:
        connecting = [False]
        last_state = [None, 0]
        def connect():
            objects = dbus.Interface(bus.get_object('org.bluez', '/'),
                                     'org.freedesktop.DBus.ObjectManager').GetManagedObjects()
            selected = select_head_unit(objects, args.device, previous_head_unit())
            if selected and selected.startswith(adapter + '/') and selected != args.device:
                logging.info('switching active CarPlay target: %s', selected)
                retire_worker(workers.pop(args.device, None))
                args.device = selected
            worker = workers.get(args.device)
            active = media_active()
            if active:
                profile_power.close()
            state = (args.device, bool(objects.get(args.device, {}).get('org.bluez.Device1', {}).get('Connected')),
                     connecting[0], bool(worker and worker[1].is_alive()), active)
            if state != last_state[0] or time.monotonic() - last_state[1] >= 60:
                logging.info('connection checkpoint target=%s bluetooth=%s pending=%s worker=%s media=%s', *state)
                last_state[:] = [state, time.monotonic()]
            if connecting[0] or (worker and worker[1].is_alive()) or active:
                return False
            def done(error=None):
                connecting[0] = False
                if error:
                    logging.warning('CarPlay profile connection failed target=%s: %s %s', args.device, error.get_dbus_name(), str(error))
                else:
                    logging.info('CarPlay profile connection requested')
            try:
                connecting[0] = True
                device = dbus.Interface(bus.get_object('org.bluez', args.device), 'org.bluez.Device1')
                connected = dbus.Interface(bus.get_object('org.bluez', args.device),
                                           'org.freedesktop.DBus.Properties').Get('org.bluez.Device1', 'Connected')
                if not connected:
                    connecting[0] = False
                    return False
                profile_power.open()
                logging.info('requesting CarPlay RFCOMM profile target=%s', args.device)
                device.ConnectProfile(ACCESSORY_UUID, reply_handler=done, error_handler=done, timeout=12)
            except dbus.DBusException as error:
                done(error)
            return False
        def device_changed(interface, changed, invalidated, path=None):
            safe = {str(k): str(v) for k, v in changed.items() if k in
                    ('Powered', 'Connectable', 'Discoverable', 'Pairable', 'Alias', 'Class', 'UUIDs', 'Paired', 'Connected', 'ServicesResolved')}
            if safe:
                logging.info('BlueZ state change path=%s interface=%s values=%s', path, interface, safe)
            if path == adapter and interface == 'org.bluez.Adapter1' and 'Powered' in changed:
                # Re-register SDP and reapply the EIR through our systemd restart.
                # Existing sockets/profiles cannot represent a new controller lifetime.
                logging.info('Bluetooth power changed; rebuilding phone advertisement and profiles')
                loop.quit()
                return
            if interface == 'org.bluez.Device1' and 'Connected' in changed and changed['Connected']:
                GLib.timeout_add(1000, connect)
            if path == args.device and interface == 'org.bluez.Device1' and 'Connected' in changed:
                if changed['Connected']:
                    profile_power.open()
                    logging.info('HU Bluetooth connected; scheduling CarPlay profile handshake')
                    GLib.timeout_add(1000, connect)
                else:
                    profile_power.close()
                    logging.info('HU Bluetooth disconnected; retiring old RFCOMM channel')
                    retire_worker(workers.pop(args.device, None))
        bus.add_signal_receiver(device_changed, signal_name='PropertiesChanged',
                                dbus_interface='org.freedesktop.DBus.Properties',
                                bus_name='org.bluez', path_keyword='path')
        GLib.idle_add(connect)
        # A failed attempt must not require another Bluetooth Connected signal.
        GLib.timeout_add_seconds(10, lambda: (connect(), True)[1])
    logging.info('phone profile registered; waiting for RFCOMM connection')
    if args.seconds:
        GLib.timeout_add_seconds(args.seconds, lambda: (loop.quit(), False)[1])
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        profile_power.close()
        for worker in workers.values():
            retire_worker(worker)
        for path in (PROFILE_PATH + '_client', PROFILE_PATH):
            try:
                manager.UnregisterProfile(path)
            except dbus.DBusException:
                logging.warning('BlueZ profile already released')
        profile.remove_from_connection()
        client_profile.remove_from_connection()


if __name__ == '__main__':
    from carplay_proto.runtime_logging import configure
    configure('bluetooth-session')
    main()
