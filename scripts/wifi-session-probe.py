#!/usr/bin/env python3
"""Connect to the supplied HU AP temporarily, with an independent restoration process."""
import argparse
import atexit
import json
import os
import plistlib
import subprocess
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def sender_device_id(bluetooth_address, fallback='D8:B0:53:22:CE:CF'):
    """AirPlay deviceID: the phone's Bluetooth address when it is valid."""
    import re
    address = str(bluetooth_address or '').upper()
    return address if re.fullmatch(r'[0-9A-F]{2}(?::[0-9A-F]{2}){5}', address) else fallback


def airplay_iap_link(local_name, local_address=None):
    """Return the iAP2 link runner for iAPSendMessage, or None if unavailable."""
    import importlib.util
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wireless-probe.py')
        spec = importlib.util.spec_from_file_location('sailplay_wireless_probe', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as error:
        print('iAP tunnel unavailable: {}'.format(type(error).__name__), flush=True)
        return None
    return lambda sock, stop: module.airplay_link(sock, stop, local_name, local_address)


def refresh_session(path, session):
    # StartSession can replace the initial Wi-Fi configuration during discovery.
    try:
        with open(path) as stream:
            updated = json.load(stream)
    except (OSError, ValueError):
        return
    if isinstance(updated, dict) and updated.get('ssid') == session['ssid']:
        session.update(updated)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', default='/tmp/sailplay-session.json')
    parser.add_argument('--connect', action='store_true')
    parser.add_argument('--direct-passphrase', action='store_true')
    parser.add_argument('--forget-target', action='store_true')
    parser.add_argument('--trace-supplicant', action='store_true')
    parser.add_argument('--restore-debug')
    parser.add_argument('--restore-clock')
    parser.add_argument('--session-id')
    parser.add_argument('--sustained', action='store_true')
    parser.add_argument('--force-wpa2', action='store_true')
    parser.add_argument('--log-file')
    parser.add_argument('--restore', nargs=2, metavar=('OLD', 'TARGET'))
    parser.add_argument('--restore-after', type=int, default=45)
    args = parser.parse_args()
    session_started = time.monotonic()
    from carplay_proto.runtime_logging import collection_enabled, persist_output, log_to_stdout, socket_endpoint
    persist_output('wifi-restore' if args.restore else 'wifi-airplay', args.log_file)
    log_to_stdout()
    args.trace_supplicant = args.trace_supplicant and collection_enabled()
    media_lease = None
    if not args.restore:
        from carplay_proto.session import SessionBusy, SessionLease
        media_lease = SessionLease('carplay')
        try:
            media_lease.acquire()
        except SessionBusy:
            message = 'Existing media handover active; duplicate StartSession ignored'
            print(message, flush=True)
            return
        atexit.register(media_lease.close)
    if not 10 <= args.restore_after <= 120:
        parser.error('restore-after must be 10..120 seconds')
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBusGMainLoop(set_as_default=True)
    from carplay_proto.networkdbus import network_object, network_interface
    bus = dbus.SystemBus()
    if media_lease is not None:
        from carplay_proto.networksession import restore_previous_network
        restore_previous_network(media_lease, bus, reconnect=False)
        media_lease.phase('connecting')
    manager = network_interface(network_object(bus, 'net.connman', '/'), 'net.connman.Manager')
    loop = GLib.MainLoop()
    from carplay_proto.wifiretry import ReassociationWindow
    wpa2_retry = ReassociationWindow()
    wpa2_retries = 0
    wpa2_interface_path = None
    def service(path):
        return network_interface(network_object(bus, 'net.connman', path), 'net.connman.Service')
    if args.restore:
        deadline = float('inf') if args.sustained else time.monotonic() + 300
        heartbeat = '/tmp/sailplay-handover-heartbeat'
        def modified(path):
            try:
                return os.path.getmtime(path)
            except OSError:
                return 0.0
        while True:
            if args.session_id:
                from carplay_proto.session import current_owner
                try:
                    owner = current_owner()
                except ValueError:
                    owner = {}
                if owner.get('id') and owner['id'] != args.session_id:
                    print('Retired CarPlay restore job superseded by another projection session', flush=True)
                    return
            if not args.restore_clock:
                time.sleep(args.restore_after)
                break
            # The authenticated probe touches the heartbeat while it is still
            # retrying. Without this a single failed AirPlay attempt would
            # restore the old network and flap Wi-Fi between the HU and the
            # previous AP every retry cycle.
            updated = max(modified(args.restore_clock), modified(heartbeat))
            remaining = args.restore_after - (time.time() - updated)
            if remaining <= 0 or time.monotonic() >= deadline:
                break
            time.sleep(min(remaining, 1))
        print('RESTORE Wi-Fi safety timer expired at {:.3f}'.format(time.monotonic()), flush=True)
        old, target = args.restore
        old = old or None
        from carplay_proto.session import SessionBusy, SessionLease
        restoration = SessionLease('carplay')
        try:
            if not restoration.acquire(expected=args.session_id):
                return
        except SessionBusy:
            return
        try:
            # An older RPM's timer has no identity. Its saved paths are valid
            # only until a newer backend has taken ownership of the network.
            plan = restoration.previous.get('network') or {}
            if not args.session_id and restoration.previous.get('id') and (
                    plan.get('old') != old or plan.get('target') != target):
                return
            if restoration.state.get('network') is None and not restoration.previous.get('id'):
                restoration.plan_network(old, target, forget=args.forget_target, debug=args.restore_debug)
            from carplay_proto.networksession import restore_network
            restore_network(restoration, bus)
        finally:
            restoration.close()
        return
    with open(args.session) as stream:
        session = json.load(stream)
    print('Wi-Fi handover started session={} security={} channel={} addresses={} port={}'.format(
        media_lease.identity, session.get('security'), session.get('channel'), session['addresses'], session['port']),flush=True)
    from carplay_proto.networktrace import NetworkTrace
    network_trace = NetworkTrace(ssid=session['ssid'])
    phone_name = session.get('device_name')
    if not phone_name:
        from carplay_proto.bluezadapter import select_adapter, adapter_name
        objects = network_interface(bus.get_object('org.bluez', '/'),
                                 'org.freedesktop.DBus.ObjectManager').GetManagedObjects()
        adapter, _ = select_adapter(objects)
        phone_name = adapter_name(objects[adapter]['org.bluez.Adapter1'])
    def network_added(path, properties):
        nonlocal wpa2_interface_path
        network = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1', path), 'org.freedesktop.DBus.Properties')
        configuration = network.Get('fi.w1.wpa_supplicant1.Network', 'Properties')
        if str(configuration.get('ssid', '')).strip('"') == session['ssid']:
            from carplay_proto.wifiretry import mixed_wpa_security
            if not args.force_wpa2 and not mixed_wpa_security(configuration):
                return
            wpa2_retry.arm()
            print('HU supplicant security before fallback: {}'.format({
                key:str(configuration.get(key)) for key in ('key_mgmt','proto','ieee80211w')}),flush=True)
            network.Set('fi.w1.wpa_supplicant1.Network', 'Properties',
                        dbus.Dictionary({'key_mgmt': dbus.String('WPA-PSK'),
                                         'proto': dbus.String('RSN')}, signature='sv', variant_level=1))
            print('HU network only: selected WPA2-PSK instead of SAE', flush=True)
            # Keep ConnMan's association alive. Explicit Disconnect was
            # interpreted as SAE authentication failure and removed this
            # network before the WPA2 attempt could complete.
            interface_path = str(path).split('/Networks/')[0]
            wpa2_interface_path = interface_path
            interface = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1', interface_path),
                                       'fi.w1.wpa_supplicant1.Interface')
            properties = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1', interface_path),
                                        'org.freedesktop.DBus.Properties')
            from carplay_proto.wifiretry import reassociate_target
            selection_deadline=time.monotonic()+2
            def apply_reassociation():
                try:
                    if reassociate_target(interface,properties,path):
                        print('HU network only: requested WPA2 reassociation without Disconnect',flush=True)
                        return False
                except dbus.DBusException as error:
                    print('WPA2 reassociation request failed: '+error.get_dbus_name(),flush=True)
                    return False
                if time.monotonic() >= selection_deadline:
                    print('HU WPA2 properties updated; target was not selected, leaving current network unchanged',flush=True)
                    return False
                return True
            if apply_reassociation():
                GLib.timeout_add(50,apply_reassociation)
    bus.add_signal_receiver(network_added, signal_name='NetworkAdded',
                            dbus_interface='fi.w1.wpa_supplicant1.Interface', bus_name='fi.w1.wpa_supplicant1')
    if args.trace_supplicant:
        monitor = dbus.SystemBus(private=True)
        owner = str(bus.get_name_owner('fi.w1.wpa_supplicant1'))
        connman_owner = str(bus.get_name_owner('net.connman'))
        def message_received(connection, message):
            if message.get_type() == dbus.lowlevel.MESSAGE_TYPE_ERROR:
                detail = str(message.get_args_list()).replace(session['passphrase'], '<password>').replace(session['ssid'], '<HU-SSID>')
                print('Supplicant D-Bus error: {} {}'.format(message.get_error_name(), detail), flush=True)
            elif message.get_type() == dbus.lowlevel.MESSAGE_TYPE_METHOD_CALL:
                print('ConnMan D-Bus call: {} {}'.format(message.get_interface(), message.get_member()), flush=True)
                if message.get_member() == 'AddNetwork':
                    values = message.get_args_list()[0]
                    print('Supplicant network options: {}'.format({str(k): str(v) for k,v in values.items()
                        if str(k) in ('key_mgmt', 'proto', 'ieee80211w', 'pairwise', 'group', 'bgscan', 'scan_ssid')}), flush=True)
            elif message.get_type() == dbus.lowlevel.MESSAGE_TYPE_METHOD_RETURN:
                print('Supplicant D-Bus reply serial={}'.format(message.get_reply_serial()), flush=True)
            elif message.get_type() == dbus.lowlevel.MESSAGE_TYPE_SIGNAL and message.get_member() == 'PropertiesChanged':
                arguments = message.get_args_list()
                values = next((v for v in arguments if isinstance(v, dict)), {})
                safe = {str(k): str(v) for k,v in values.items() if str(k) in ('State','DisconnectReason','AuthStatusCode','AssocStatusCode','CurrentBSS')}
                if safe:
                    print('Supplicant state: {}'.format(safe), flush=True)
        monitor.add_message_filter(message_received)
        network_interface(monitor.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus'),
                       'org.freedesktop.DBus.Monitoring').BecomeMonitor(
                           dbus.Array(["type='error',sender='{}'".format(owner),
                                       "type='method_return',sender='{}'".format(owner),
                                       "type='signal',sender='{}'".format(owner),
                                       "type='method_call',destination='fi.w1.wpa_supplicant1'",
                                       "type='method_call',destination='{}'".format(owner),
                                       "type='method_call',sender='{}'".format(connman_owner)], signature='s'), dbus.UInt32(0))
    from carplay_proto.wifidiscovery import find_service, ensure_wifi_powered
    wifi_path = None
    if args.connect:
        wifi_path = ensure_wifi_powered(manager,
            lambda path, powered: network_interface(network_object(bus, 'net.connman', path),
                'net.connman.Technology').SetProperty('Powered', dbus.Boolean(powered, variant_level=1)),
            log=lambda message: print(message, flush=True))
    services = manager.GetServices()
    target = find_service(services, session['ssid'], require_available=True)
    if args.connect:
        # StartSession can precede ConnMan discovering the newly enabled HU AP.
        from carplay_proto.wifidiscovery import discover
        from carplay_proto.networkrecovery import recover_split_registry
        owner_api = network_interface(network_object(bus, 'org.freedesktop.DBus',
            '/org/freedesktop/DBus'), 'org.freedesktop.DBus')
        recovering_owner = None
        def prepare_service(path):
            nonlocal recovering_owner
            owner = str(owner_api.GetNameOwner('net.connman'))
            if owner == recovering_owner:
                return False
            if recovering_owner is not None:
                print('HU ConnMan owner replaced; continuing discovery within the current handover', flush=True)
                recovering_owner = None
            try:
                recovered = recover_split_registry(manager, service, path, session['ssid'], owner,
                    log=lambda line: print(line, flush=True))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print('HU registry recovery unavailable: '+type(error).__name__, flush=True)
                return True
            if recovered:
                recovering_owner = owner
                return False
            return True
        def cached_bss_visible(ssid):
            try:
                props = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1', '/fi/w1/wpa_supplicant1'),
                                       'org.freedesktop.DBus.Properties')
                for interface in props.Get('fi.w1.wpa_supplicant1', 'Interfaces'):
                    interface_props = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1', interface),
                                                     'org.freedesktop.DBus.Properties')
                    for bss in interface_props.Get('fi.w1.wpa_supplicant1.Interface', 'BSSs'):
                        bss_props = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1', bss),
                                                  'org.freedesktop.DBus.Properties')
                        if bytes(bss_props.Get('fi.w1.wpa_supplicant1.BSS', 'SSID')) == ssid.encode('utf-8'):
                            return True
            except dbus.DBusException:
                pass
            return False
        if wifi_path:
            target, services = discover(manager, wifi_path, session['ssid'],
                scan=lambda path: network_interface(network_object(bus, 'net.connman', path),
                    'net.connman.Technology').Scan(timeout=8),
                cached_bss_visible=cached_bss_visible,
                set_powered=lambda path, powered: network_interface(network_object(bus, 'net.connman', path),
                    'net.connman.Technology').SetProperty('Powered', dbus.Boolean(powered, variant_level=1)),
                log=lambda message: print(message, flush=True), require_available=True,
                prepare=prepare_service)
    previous_network = media_lease.state.get('network') or {}
    old = next((str(path) for path, props in services if props.get('Type') == 'wifi'
                and props.get('State') in ('ready', 'online')), None)
    if not old and previous_network.get('old') != target:
        old = previous_network.get('old')
    print('HU AP visible={}, previous Wi-Fi recorded={}'.format(bool(target), bool(old)), flush=True)
    if not args.connect:
        return
    if not target:
        raise RuntimeError('HU Wi-Fi service unavailable after discovery and recovery')
    refresh_session(args.session, session)
    already_connected = target == old
    target_props = service(target).GetProperties()
    print('HU pre-connect configuration: {}'.format({k:str(target_props.get(k)) for k in
          ('State','Error','Strength','IPv4.Configuration','IPv6.Configuration','Nameservers')}),flush=True)
    if args.direct_passphrase and not args.sustained and not already_connected and target_props.get('Favorite'):
        raise RuntimeError('direct credential test requires an unsaved HU network')
    class Agent(dbus.service.Object):
        @dbus.service.method('net.connman.Agent', in_signature='oa{sv}', out_signature='a{sv}')
        def RequestInput(self, path, fields):
            print('ConnMan credential fields={}'.format(sorted(str(key) for key in fields)), flush=True)
            if str(path) != target or set(fields) - {'Passphrase', 'Name', 'SSID', 'WPS', 'PreviousPassphrase'}:
                raise dbus.exceptions.DBusException('unsupported credential request')
            return {'Passphrase': dbus.String(session['passphrase'])}
        @dbus.service.method('net.connman.Agent', in_signature='os', out_signature='')
        def ReportError(self, path, error):
            print('ConnMan reported connection failure: {}'.format(str(error)), flush=True)
        @dbus.service.method('net.connman.Agent', in_signature='', out_signature='')
        def Release(self):
            pass
        @dbus.service.method('net.connman.Agent', in_signature='', out_signature='')
        def Cancel(self):
            pass
    agent = Agent(bus, '/org/sailplay/WifiAgent')
    manager.RegisterAgent(dbus.ObjectPath('/org/sailplay/WifiAgent'))
    # A separate systemd unit survives SSH logout AND the probe unit's teardown.
    restore_command = ['systemd-run', '--unit=sailplay-wifi-restore-{}'.format(os.getpid()),
                    sys.executable, os.path.abspath(__file__), '--restore', old or '', target,
                    '--restore-after', str(args.restore_after)]
    restore_clock = '/tmp/sailplay-wifi-restore-clock-' + media_lease.identity
    descriptor = os.open(restore_clock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    restore_clock_inode = os.fstat(descriptor).st_ino
    os.fchmod(descriptor, 0o600)
    os.utime(descriptor, None)
    os.close(descriptor)
    def cleanup_clock():
        try:
            if os.lstat(restore_clock).st_ino == restore_clock_inode:
                os.unlink(restore_clock)
        except FileNotFoundError:
            pass
    atexit.register(cleanup_clock)
    restore_command += ['--restore-clock', restore_clock, '--session-id', media_lease.identity]
    if args.sustained:
        restore_command.append('--sustained')
    if args.direct_passphrase and not target_props.get('Favorite'):
        restore_command.append('--forget-target')
    if args.trace_supplicant:
        debug_properties = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1','/fi/w1/wpa_supplicant1'),
                                           'org.freedesktop.DBus.Properties')
        previous_debug = str(debug_properties.Get('fi.w1.wpa_supplicant1', 'DebugLevel'))
        restore_command += ['--restore-debug', previous_debug]
    if not already_connected:
        media_lease.plan_network(old, target,
            forget=args.direct_passphrase and not target_props.get('Favorite'),
            wifi_path=previous_network.get('wifi_path'), powered=previous_network.get('powered', True),
            debug=previous_debug if args.trace_supplicant else None)
    if not already_connected:
        subprocess.run(restore_command, check=True,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if args.trace_supplicant and not already_connected:
        if debug_properties.Get('fi.w1.wpa_supplicant1', 'DebugShowKeys'):
            raise RuntimeError('refusing diagnostic trace with secret-key logging enabled')
        debug_properties.Set('fi.w1.wpa_supplicant1', 'DebugLevel', dbus.String('debug', variant_level=1))
    if args.direct_passphrase and not already_connected:
        if not target_props.get('Favorite') and str(target_props.get('IPv4.Configuration',{}).get('Method','')) in ('','off','unknown'):
            service(target).SetProperty('IPv4.Configuration',dbus.Dictionary(
                {'Method':dbus.String('dhcp')},signature='sv',variant_level=1))
            print('New HU profile: IPv4 DHCP enabled; temporary profile will be removed on restoration',flush=True)
        service(target).SetProperty('Passphrase', dbus.String(session['passphrase'], variant_level=1))
        print('ConnMan accepted the HU passphrase property (value redacted)', flush=True)
    def connected():
        if wpa2_retry.started:
            return
        wpa2_retry.started = True
        media_lease.phase('projecting')
        os.utime(restore_clock, None)
        from carplay_proto.rtspclient import connect
        props = service(target).GetProperties()
        interface = str(props['Ethernet']['Interface'])
        print('HU Wi-Fi connected; probing AirPlay elapsedMs={:.1f}'.format(
            (time.monotonic()-session_started)*1000), flush=True)
        print('HU IP state: {}'.format({key:str(props.get(key)) for key in ('IPv4','IPv6','IPv6.Configuration')}), flush=True)
        from carplay_proto.airplaydiscovery import endpoints
        for address, port in endpoints(session['addresses'], session['port'], props,
                                       log=lambda line: print(line, flush=True)):
            client = None
            timing = None
            setup_status = None
            setup_info = None
            attempt_started = time.monotonic()
            stage = 'control-connect'
            try:
                print('AirPlay attempt started address={} port={} interface={}'.format(
                    address,port,interface),flush=True)
                client = connect(address, port, interface, bind_device=True, source_address_wait=5, refused_wait=15)
                print('AirPlay control connected local={} peer={} elapsedMs={:.1f}'.format(
                    socket_endpoint(client.sock,'getsockname'),socket_endpoint(client.sock,'getpeername'),
                    (time.monotonic()-attempt_started)*1000),flush=True)
                stage = 'public-info'
                status, headers, body = client.request('GET', '/info', plistlib.dumps({}, fmt=plistlib.FMT_BINARY),
                    {'Content-Type':'application/x-apple-binary-plist', 'User-Agent':'AirPlay/566.25.21'})
                print('AirPlay /info status={}, bytes={}'.format(status, len(body)), flush=True)
                # Public /info does not establish encrypted media keys.
                if status in (200, 455):
                    from carplay_proto.airplaypair import pair_setup, pair_verify
                    identity_path = '/tmp/sailplay-airplay-identity.json'
                    try:
                        with open(identity_path) as identity_file:
                            identity = json.load(identity_file)
                    except FileNotFoundError:
                        import uuid
                        identity = {'id':str(uuid.uuid4()), 'private_key':os.urandom(32).hex()}
                        descriptor = os.open(identity_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                        with os.fdopen(descriptor, 'w') as identity_file:
                            json.dump(identity, identity_file)
                    try:
                        stage = 'pair-setup'
                        pairing_started = time.monotonic()
                        print('AirPlay Pair-Setup started',flush=True)
                        pairing = pair_setup(client, identity['id'], bytes.fromhex(identity['private_key']))
                        print('AirPlay Pair-Setup peer proof verified elapsedMs={:.1f}'.format(
                            (time.monotonic()-pairing_started)*1000), flush=True)
                        stage = 'pair-verify'
                        pairing_started = time.monotonic()
                        print('AirPlay Pair-Verify started',flush=True)
                        verified = pair_verify(client, identity['id'], bytes.fromhex(identity['private_key']), pairing)
                        print('AirPlay Pair-Verify complete; encrypted control enabled elapsedMs={:.1f}'.format(
                            (time.monotonic()-pairing_started)*1000), flush=True)
                        from carplay_proto.airplaytiming import TimingServer
                        timing = TimingServer(client.sock.sock)
                        import uuid
                        from carplay_proto.audio import audio_compat_build
                        os_build = audio_compat_build()
                        print('AirPlay audio compatibility build={} RTP authenticated header=timestamp+SSRC (8 bytes)'.format(
                            os_build), flush=True)
                        # CarPlay identifies devices by Bluetooth address: the head
                        # unit's own deviceID is its Bluetooth address, and the
                        # iAP2 link reports ours. Use the same identity here.
                        device_id = sender_device_id(session.get('bluetooth_address'))
                        print('AirPlay sender deviceID={}'.format(device_id), flush=True)
                        setup = {'deviceID':device_id,'macAddress':device_id,
                                 'model':'Sailplay1,1','name':phone_name,'osName':'SailfishOS',
                                 'osBuildVersion':os_build,'sourceVersion':'566.25.21',
                                 'sessionUUID':str(uuid.uuid4()),'timingPort':timing.port,
                                 'features':[],'statsCollectionEnabled':False}
                        stage = 'initial-setup'
                        setup_started = time.monotonic()
                        print('Encrypted initial SETUP request={}'.format(json.dumps({
                            key: setup[key] for key in ('deviceID','macAddress','model','osName',
                                'osBuildVersion','sourceVersion','timingPort','features','statsCollectionEnabled')
                        },sort_keys=True)),flush=True)
                        setup_status, setup_headers, setup_body = client.request('SETUP','/setup',plistlib.dumps(setup,fmt=plistlib.FMT_BINARY),
                            {'Content-Type':'application/x-apple-binary-plist','User-Agent':'AirPlay/566.25.21'})
                        public_headers = {key: value for key, value in setup_headers.items()
                            if key.lower() in ('server','cseq','content-type','content-length','connection','x-apple-error','x-apple-error-code')}
                        print('Encrypted initial SETUP status={} bytes={} headers={} elapsedMs={:.1f}'.format(
                            setup_status,len(setup_body),public_headers,(time.monotonic()-setup_started)*1000),flush=True)
                        if setup_status == 200:
                            setup_info = plistlib.loads(setup_body)
                            print('Initial SETUP response keys={} eventPort={} timingPort={}'.format(
                                sorted(setup_info), setup_info.get('eventPort'), setup_info.get('timingPort')),flush=True)
                        stage = 'encrypted-info'
                        status, headers, body = client.request('GET', '/info', plistlib.dumps({}, fmt=plistlib.FMT_BINARY),
                            {'Content-Type':'application/x-apple-binary-plist','User-Agent':'AirPlay/566.25.21'})
                        print('Encrypted AirPlay /info status={} bytes={}'.format(status,len(body)), flush=True)
                    except ValueError:
                        raise
                if status == 200:
                    info = plistlib.loads(body)
                    if collection_enabled():
                        descriptor = os.open('/tmp/sailplay-hu-info.plist', os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
                        os.fchmod(descriptor, 0o600)
                        with os.fdopen(descriptor, 'wb') as saved_info:
                            saved_info.write(plistlib.dumps(info,fmt=plistlib.FMT_BINARY))
                    print('AirPlay /info keys={}'.format(sorted(info)), flush=True)
                    for key in ('model','sourceVersion','features','statusFlags','displays','audioFormats','hidDevices'):
                        if key in info:
                            print('AirPlay {}={}'.format(key, repr(info[key])), flush=True)
                    demo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                             'diagnostics','video-demo.h264')
                    live_ui = os.path.exists(os.path.join(os.path.dirname(demo_path),'display-ui'))
                    if live_ui or os.path.exists(demo_path):
                        if setup_info is None:
                            stage = 'initial-setup'
                            raise RuntimeError('Encrypted initial SETUP rejected status={}'.format(setup_status))
                        stage = 'media-session'
                        from carplay_proto.videodemo import run_demo
                        os.utime(restore_clock, None)
                        run_demo(client,address,interface,verified.shared,setup_info,info,demo_path,
                                 seconds=(0 if args.sustained else 45) if live_ui else 15,live=live_ui,
                                 on_activity=lambda:(os.utime(restore_clock,None),media_lease.streaming()),
                                 bluetooth_address=session.get('bluetooth_address'),
                                 bluetooth_device=session.get('bluetooth_device'),
                                 iap_link=airplay_iap_link(session.get('device_name') or 'SailfishOS',
                                                           session.get('bluetooth_address')))
                        break
            except Exception as error:
                print('AirPlay probe failed stage={} elapsedMs={:.1f} error={} errno={}'.format(
                    stage,(time.monotonic()-attempt_started)*1000,type(error).__name__,getattr(error,'errno',None)), flush=True)
                print('Failure detail: {}'.format(str(error).replace(session['passphrase'],'<password>')),flush=True)
            finally:
                if timing:
                    timing.close()
                if client:
                    client.sock.close()
        loop.quit()
    no_carrier_retries = [0]
    def after_carrier_scan(*unused):
        nonlocal target
        try:
            available = find_service(manager.GetServices(timeout=5), session['ssid'], require_available=True)
            if available:
                if available!=target:
                    print('HU service refreshed after scan; replacing stale object path',flush=True)
                    target=available
                props=service(target).GetProperties()
                print('Retrying HU Wi-Fi after fresh scan state={} strength={} error={}'.format(props.get('State'),int(props.get('Strength') or 0),props.get('Error')),flush=True)
                service(target).Connect(reply_handler=connected, error_handler=failed, timeout=12)
            else:
                failed(NoCarrierRetry())
        except dbus.DBusException as error:
            failed(error)
    def carrier_scan_failed(error):
        print('HU retry scan failed: {}'.format(error.get_dbus_name()), flush=True)
        failed(NoCarrierRetry())
    def retry_no_carrier():
        # A synchronous Scan inside a GLib callback stalls the deadline and
        # D-Bus handlers. Oct 16 retries took 64 seconds instead of 8 seconds.
        try:
            technology = network_interface(network_object(bus, 'net.connman', wifi_path, introspect=False),
                                        'net.connman.Technology')
            technology.Scan(reply_handler=after_carrier_scan,
                            error_handler=carrier_scan_failed, timeout=8)
        except dbus.DBusException as error:
            carrier_scan_failed(error)
        return False
    class NoCarrierRetry:
        def get_dbus_name(self):
            return 'net.connman.Error.NoCarrier'
    def failed(error):
        nonlocal wpa2_interface_path
        print('ConnMan Connect failed: {}'.format(error.get_dbus_name()), flush=True)
        # Connect errors can coexist with a usable local link. Never infer this
        # merely from cached IPs or lack of Internet; verify association and TCP.
        props = {}
        try:
            props=service(target).GetProperties()
            iface=str(props.get('Ethernet',{}).get('Interface',''))
            associated=None
            root=network_interface(network_object(bus, 'fi.w1.wpa_supplicant1','/fi/w1/wpa_supplicant1'),
                                'org.freedesktop.DBus.Properties')
            for path in root.Get('fi.w1.wpa_supplicant1','Interfaces'):
                iprops=network_interface(network_object(bus, 'fi.w1.wpa_supplicant1',path),
                                      'org.freedesktop.DBus.Properties')
                state = iprops.GetAll('fi.w1.wpa_supplicant1.Interface')
                if str(state.get('Ifname'))!=iface:continue
                wpa2_interface_path = str(path)
                if str(state.get('State'))!='completed':continue
                bss=state.get('CurrentBSS')
                bprops=network_interface(network_object(bus, 'fi.w1.wpa_supplicant1',bss),
                                      'org.freedesktop.DBus.Properties')
                associated=bytes(bprops.Get('fi.w1.wpa_supplicant1.BSS','SSID')).decode('utf-8')
            from carplay_proto.wifidiscovery import verify_local_carplay,probe_bound_endpoint
            if verify_local_carplay(props,session['ssid'],associated,session['addresses'],session['port'],
                                    probe_bound_endpoint,log=lambda line:print(line,flush=True)):
                print('Ignoring ConnMan Connect error for verified local CarPlay link',flush=True)
                connected()
                return
        except (dbus.DBusException,OSError,ValueError,KeyError) as check_error:
            print('HU local bypass check failed: '+type(check_error).__name__,flush=True)
        if (error.get_dbus_name() == 'net.connman.Error.Failed'
                and props.get('State') in ('idle', 'failure') and wpa2_interface_path):
            wpa2_retry.arm()
        if wpa2_retry.waiting():
            print('Waiting for HU association status after the connection failed', flush=True)
            return
        if error.get_dbus_name() == 'net.connman.Error.NoCarrier':
            try:
                from carplay_proto.networkrecovery import recover_split_registry
                owner_api = network_interface(network_object(bus, 'org.freedesktop.DBus',
                    '/org/freedesktop/DBus'), 'org.freedesktop.DBus')
                if recover_split_registry(manager, service, target, session['ssid'],
                        str(owner_api.GetNameOwner('net.connman')),
                        log=lambda line: print(line, flush=True)):
                    loop.quit()
                    return
            except (dbus.DBusException, OSError, ValueError, subprocess.SubprocessError) as recovery_error:
                print('HU registry recovery unavailable: '+type(recovery_error).__name__, flush=True)
        if error.get_dbus_name() == 'net.connman.Error.NoCarrier' and wifi_path and no_carrier_retries[0] < 3:
            no_carrier_retries[0] += 1
            print('HU carrier not ready; scheduling scan retry {}/3'.format(no_carrier_retries[0]), flush=True)
            GLib.timeout_add_seconds(2, retry_no_carrier)
            return
        from carplay_proto.networktrace import daemon_evidence
        daemon_evidence()
        loop.quit()
    def check_wpa2_retry():
        nonlocal wpa2_retry, wpa2_retries
        if wpa2_retry.started:
            return False
        if wpa2_retry.deadline:
            try:
                props = service(target).GetProperties()
            except dbus.DBusException as error:
                print('WPA2 retry status unavailable: '+error.get_dbus_name(),flush=True)
                loop.quit()
                return False
            if props.get('State') in ('ready','online'):
                connected()
                return False
            if wpa2_interface_path:
                try:
                    properties = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1', wpa2_interface_path),
                                                   'org.freedesktop.DBus.Properties')
                    supplicant = properties.GetAll('fi.w1.wpa_supplicant1.Interface')
                    associated = None
                    if supplicant.get('State') == 'completed' and supplicant.get('CurrentBSS') not in (None, '/'):
                        bss = network_interface(network_object(bus, 'fi.w1.wpa_supplicant1', supplicant['CurrentBSS']),
                                                'org.freedesktop.DBus.Properties')
                        associated = bytes(bss.Get('fi.w1.wpa_supplicant1.BSS', 'SSID')).decode('utf-8')
                    abandoned = wpa2_retry.abandoned(props.get('State'), supplicant, associated, session['ssid'])
                except (dbus.DBusException, ValueError, TypeError):
                    wpa2_retry.idle_since = None
                    abandoned = False
                if abandoned:
                    if wpa2_retries >= 2:
                        print('HU association retry limit reached; retiring the handover', flush=True)
                        loop.quit()
                        return False
                    wpa2_retries += 1
                    wpa2_retry = ReassociationWindow()
                    print('HU association ended state={} error={}; retrying within the current handover {}/2'.format(
                        props.get('State'), props.get('Error'), wpa2_retries), flush=True)
                    try:
                        refresh_session(args.session, session)
                        if args.direct_passphrase:
                            service(target).SetProperty('Passphrase', dbus.String(session['passphrase'], variant_level=1))
                        service(target).Connect(reply_handler=connected, error_handler=failed, timeout=12)
                    except dbus.DBusException as error:
                        failed(error)
                    return True
            if not wpa2_retry.waiting():
                print('WPA2 reassociation did not reach ready: state={} error={}'.format(
                    props.get('State'),props.get('Error')),flush=True)
                loop.quit()
                return False
        return True
    GLib.timeout_add_seconds(1, check_wpa2_retry)
    network_trace.target = target
    try:
        if already_connected:
            print('Reusing existing HU Wi-Fi; leaving network configuration unchanged', flush=True)
            GLib.idle_add(connected)
        else:
            service(target).Connect(reply_handler=connected, error_handler=failed, timeout=25)
        GLib.timeout_add_seconds(30, lambda: (loop.quit(), False)[1])
        loop.run()
    finally:
        print('Wi-Fi/AirPlay handover worker exiting; releasing media lock', flush=True)
        network_trace.close()
        try:
            manager.UnregisterAgent(dbus.ObjectPath('/org/sailplay/WifiAgent'))
        except dbus.DBusException as error:
            print('ConnMan agent cleanup after daemon change: '+error.get_dbus_name(),flush=True)
        agent.remove_from_connection()
        try:
            from carplay_proto.networksession import restore_network
            restore_network(media_lease, bus)
        except Exception as error:
            print('CarPlay Wi-Fi restoration deferred to its recovery job: ' + type(error).__name__, flush=True)
        finally:
            media_lease.close()
            cleanup_clock()


if __name__ == '__main__':
    import signal
    def terminate(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,terminate)
    if '--restore' in sys.argv:
        main()
    else:
        from carplay_proto.projectionpower import with_connection_power
        with_connection_power(main)
