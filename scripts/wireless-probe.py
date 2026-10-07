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
from carplay_proto.iap2link import (ACK, DETECT, EAK, RST, SYN, Decoder,
                                   Packet, encode, parse_synchronization,
                                   synchronization)
from carplay_proto.wire import Frame, Framer, encode_param
from carplay_proto.accessoryauth import PinnedAccessory
from carplay_proto.wireless import parse_wifi_configuration, request_wifi_configuration, parse_start_session

PHONE_UUID = '00000000-deca-fade-deca-deafdecacafe'
ACCESSORY_UUID = '00000000-deca-fade-deca-deafdecacaff'
IAP_V2_UUID = '02030302-1d19-415f-86f2-22a2106a0a77'
PROFILE_PATH = '/org/sailplay/wireless_phone'


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


def probe(sock, stop, duration, certificate_out=None, accessory_key=None,
          announce_wireless=False, local_address=None, session_out=None, wifi_handover=False,sustained=False):
    handover_started = False
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
    authenticator = None
    authenticated = False
    peer_received_messages = set()
    wifi_config = None
    sock.settimeout(0.2)
    try:
        authenticator = PinnedAccessory(accessory_key) if accessory_key else None
        while not stop.is_set() and time.monotonic() < deadline:
            now = time.monotonic()
            if sync_at and not local_syn_acked and now >= sync_at:
                sock.sendall(encode(Packet(SYN | ACK, 0, last_rx, 0, sync_payload)))
                sync_at = now + 1
            if negotiated and pending is None and outgoing:
                sequence = (sequence + 1) & 255
                pending = Packet(ACK, sequence, last_rx, session, outgoing.pop(0).encoded())
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
                if packet == DETECT:
                    if not sync_at:
                        logging.info('peer iAP2 detection confirmed')
                        # Phone is the iAP2 host: echo DETECT and wait for accessory SYN.
                        sock.sendall(DETECT)
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
                                if frame.message_id == 0x1d01:
                                    for parameter in frame.parameters():
                                        if parameter.id in (6, 7):
                                            if len(parameter.payload) % 2:
                                                raise ValueError('invalid supported-message list')
                                            ids = list(struct.unpack('>' + 'H' * (len(parameter.payload) // 2), parameter.payload))
                                            logging.info('accessory %s message IDs=%s',
                                                         'sent' if parameter.id == 6 else 'received',
                                                         ','.join('0x%04x' % value for value in ids))
                                            if parameter.id == 7:
                                                peer_received_messages = set(ids)
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
                                    if authenticator:
                                        challenge = authenticator.begin(certificate)
                                        outgoing.append(Frame(0xaa02, encode_param(0, challenge)))
                                        logging.info('certificate matches observed pin; random challenge queued')
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
                                    outgoing.append(Frame(0xaa05, b''))
                                    if announce_wireless:
                                        if not local_address:
                                            raise ValueError('missing local Bluetooth transport identity')
                                        device_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'org.sailplay:' + local_address)).upper()
                                        outgoing.extend([
                                            Frame(0x4e0c, encode_param(0, device_id.encode('ascii') + b'\x00')),
                                            Frame(0x4e09, encode_param(0, b'SailfishOS Sailplay\x00')),
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
                                    outgoing.append(request_wifi_configuration())
                                    logging.info('pinned accessory challenge signature VERIFIED; requesting Wi-Fi config')
                                elif frame.message_id == 0x5703:
                                    if not authenticated:
                                        raise ValueError('Wi-Fi credentials arrived before authentication')
                                    config = parse_wifi_configuration(frame)
                                    wifi_config = config
                                    logging.info('accessory Wi-Fi configuration received: %r', config)
                                elif frame.message_id == 0x4301:
                                    if not authenticated:
                                        raise ValueError('StartSession before authentication')
                                    start = parse_start_session(frame, wifi_config)
                                    logging.info('parsed CarPlay StartSession: %r', start)
                                    if session_out:
                                        descriptor = os.open(session_out, os.O_WRONLY | os.O_CREAT |
                                                             os.O_TRUNC | os.O_NOFOLLOW, 0o600)
                                        os.fchmod(descriptor, 0o600)
                                        with os.fdopen(descriptor, 'w') as output:
                                            json.dump(start.as_dict(), output)
                                        if wifi_handover and not handover_started:
                                            handover_command=['systemd-run', '--unit=sailplay-handover-{}-{}'.format(os.getpid(),time.monotonic_ns()),
                                                sys.executable, os.path.join(os.path.dirname(__file__), 'wifi-session-probe.py'),
                                                '--connect', '--direct-passphrase', '--force-wpa2',
                                                '--restore-after', '90', '--log-file', '/tmp/sailplay-wifi-probe.log']
                                            if sustained:
                                                handover_command.append('--sustained')
                                            else:
                                                handover_command.append('--trace-supplicant')
                                            subprocess.run(handover_command,check=True)
                                            handover_started = True
                                            logging.info('StartSession triggered independent Wi-Fi/AirPlay handover')
                    elif packet.sequence != last_rx:
                        raise ValueError('out-of-order packet; probe stops rather than losing data')
                    sock.sendall(encode(Packet(ACK, 0, last_rx, 0, None)))
        logging.info('probe ended; checksum errors=%d', decoder.errors)
    except (OSError, ValueError):
        logging.exception('probe failed')
    finally:
        sock.close()


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
    local_address = str(dbus.Interface(bus.get_object('org.bluez', '/org/bluez/hci0'),
                            'org.freedesktop.DBus.Properties').Get('org.bluez.Adapter1', 'Address'))
    loop = GLib.MainLoop()
    workers = {}

    class Profile(dbus.service.Object):
        @dbus.service.method('org.bluez.Profile1', in_signature='', out_signature='')
        def Release(self):
            loop.quit()

        @dbus.service.method('org.bluez.Profile1', in_signature='oha{sv}', out_signature='')
        def NewConnection(self, device, fd, properties):
            sock = socket.socket(fileno=fd.take())
            previous = workers.pop(str(device), None)
            if previous:
                logging.info('replacing previous RFCOMM channel for %s', device)
                retire_worker(previous)
            stop = threading.Event()
            thread = threading.Thread(target=probe, args=(sock, stop, args.seconds,
                                                         args.certificate_out, args.accessory_key,
                                                         args.announce_wireless, local_address, args.session_out, args.wifi_handover,args.sustained))
            workers[str(device)] = (stop, thread, sock)
            thread.start()
            logging.info('RFCOMM connected device=%s', device)

        @dbus.service.method('org.bluez.Profile1', in_signature='o', out_signature='')
        def RequestDisconnection(self, device):
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
        def connect():
            worker = workers.get(args.device)
            if connecting[0] or (worker and worker[1].is_alive()) or media_active():
                return False
            def done(error=None):
                connecting[0] = False
                if error:
                    logging.warning('CarPlay profile connection failed: %s', error.get_dbus_name())
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
                device.ConnectProfile(ACCESSORY_UUID, reply_handler=done, error_handler=done, timeout=12)
            except dbus.DBusException as error:
                done(error)
            return False
        def device_changed(interface, changed, invalidated, path=None):
            if path == args.device and interface == 'org.bluez.Device1' and 'Connected' in changed:
                if changed['Connected']:
                    logging.info('HU Bluetooth connected; scheduling CarPlay profile handshake')
                    GLib.timeout_add(1000, connect)
                else:
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
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    main()
