#!/usr/bin/env python3
"""Connect to the supplied HU AP temporarily, with an independent restoration process."""
import argparse
import json
import os
import plistlib
import subprocess
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', default='/tmp/sailplay-session.json')
    parser.add_argument('--connect', action='store_true')
    parser.add_argument('--direct-passphrase', action='store_true')
    parser.add_argument('--forget-target', action='store_true')
    parser.add_argument('--trace-supplicant', action='store_true')
    parser.add_argument('--restore-debug')
    parser.add_argument('--restore-clock')
    parser.add_argument('--sustained', action='store_true')
    parser.add_argument('--force-wpa2', action='store_true')
    parser.add_argument('--log-file')
    parser.add_argument('--restore', nargs=2, metavar=('OLD', 'TARGET'))
    parser.add_argument('--restore-after', type=int, default=45)
    args = parser.parse_args()
    media_lock = None
    if not args.restore:
        import fcntl
        media_lock = os.open('/run/sailplay-media.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(media_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(media_lock)
            print('Existing media handover active; duplicate StartSession ignored', flush=True)
            return
    if args.log_file:
        original_log=args.log_file
        args.log_file += '.'+str(os.getpid())
        descriptor = os.open(args.log_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.fchmod(descriptor, 0o600)
        temporary_link=original_log+'.link.'+str(os.getpid())
        os.symlink(args.log_file,temporary_link)
        os.replace(temporary_link,original_log)
        sys.stdout = os.fdopen(descriptor, 'w', buffering=1)
        sys.stderr = sys.stdout
    if not 10 <= args.restore_after <= 120:
        parser.error('restore-after must be 10..120 seconds')
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    manager = dbus.Interface(bus.get_object('net.connman', '/'), 'net.connman.Manager')
    loop = GLib.MainLoop()
    def service(path):
        return dbus.Interface(bus.get_object('net.connman', path), 'net.connman.Service')
    if args.restore:
        deadline = float('inf') if args.sustained else time.monotonic() + 300
        while True:
            updated = os.path.getmtime(args.restore_clock) if args.restore_clock and os.path.exists(args.restore_clock) else time.time() - args.restore_after
            remaining = args.restore_after - (time.time() - updated)
            if not args.restore_clock:
                time.sleep(args.restore_after)
                break
            if remaining <= 0 or time.monotonic() >= deadline:
                break
            time.sleep(min(remaining, 1))
        print('RESTORE Wi-Fi safety timer expired at {:.3f}'.format(time.monotonic()), flush=True)
        old, target = args.restore
        if args.restore_debug:
            dbus.Interface(bus.get_object('fi.w1.wpa_supplicant1','/fi/w1/wpa_supplicant1'),
                           'org.freedesktop.DBus.Properties').Set('fi.w1.wpa_supplicant1', 'DebugLevel', args.restore_debug)
        try:
            service(target).Disconnect()
        except dbus.DBusException:
            pass
        if args.forget_target:
            try:
                service(target).Remove()
            except dbus.DBusException:
                pass
        service(old).Connect(reply_handler=lambda: loop.quit(), error_handler=lambda error: loop.quit())
        GLib.timeout_add_seconds(30, lambda: (loop.quit(), False)[1])
        loop.run()
        return
    with open(args.session) as stream:
        session = json.load(stream)
    if args.force_wpa2:
        def network_added(path, properties):
            network = dbus.Interface(bus.get_object('fi.w1.wpa_supplicant1', path), 'org.freedesktop.DBus.Properties')
            configuration = network.Get('fi.w1.wpa_supplicant1.Network', 'Properties')
            if str(configuration.get('ssid', '')).strip('"') == session['ssid']:
                network.Set('fi.w1.wpa_supplicant1.Network', 'Properties',
                            dbus.Dictionary({'key_mgmt': dbus.String('WPA-PSK'),
                                             'proto': dbus.String('RSN')}, signature='sv'))
                print('HU network only: selected WPA2-PSK instead of SAE', flush=True)
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
        dbus.Interface(monitor.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus'),
                       'org.freedesktop.DBus.Monitoring').BecomeMonitor(
                           dbus.Array(["type='error',sender='{}'".format(owner),
                                       "type='method_return',sender='{}'".format(owner),
                                       "type='signal',sender='{}'".format(owner),
                                       "type='method_call',destination='fi.w1.wpa_supplicant1'",
                                       "type='method_call',destination='{}'".format(owner),
                                       "type='method_call',sender='{}'".format(connman_owner)], signature='s'), dbus.UInt32(0))
    services = manager.GetServices()
    target = next((str(path) for path, props in services if props.get('Type') == 'wifi' and props.get('Name') == session['ssid']), None)
    if args.connect and not target:
        # StartSession can precede ConnMan discovering the newly enabled HU AP.
        wifi_path = next((path for path,props in manager.GetTechnologies() if props.get('Type')=='wifi'),None)
        for attempt in range(6):
            if wifi_path:
                try:
                    dbus.Interface(bus.get_object('net.connman',wifi_path),'net.connman.Technology').Scan(timeout=8)
                except dbus.DBusException:
                    pass
            services=manager.GetServices()
            target=next((str(path) for path,props in services if props.get('Type')=='wifi' and props.get('Name')==session['ssid']),None)
            if target:
                break
            time.sleep(1)
    old = next((str(path) for path, props in services if props.get('Type') == 'wifi' and props.get('State') in ('ready', 'online')), None)
    if not old:
        old=next((str(path) for path,props in services if props.get('Type')=='wifi'
                  and props.get('Favorite') and str(path)!=target),None)
    print('HU AP visible={}, existing Wi-Fi connected={}'.format(bool(target), bool(old)), flush=True)
    if not args.connect:
        return
    if not target or not old:
        raise RuntimeError('cannot establish a reversible Wi-Fi test')
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
    manager.RegisterAgent('/org/sailplay/WifiAgent')
    # A separate systemd unit survives SSH logout AND the probe unit's teardown.
    restore_command = ['systemd-run', '--unit=sailplay-wifi-restore-{}'.format(os.getpid()),
                    sys.executable, os.path.abspath(__file__), '--restore', old, target,
                    '--restore-after', str(args.restore_after)]
    restore_clock = '/tmp/sailplay-wifi-restore-clock'
    descriptor = os.open(restore_clock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    os.fchmod(descriptor, 0o600)
    os.utime(descriptor, None)
    os.close(descriptor)
    restore_command += ['--restore-clock', restore_clock]
    if args.sustained:
        restore_command.append('--sustained')
    if args.direct_passphrase and not target_props.get('Favorite'):
        restore_command.append('--forget-target')
    if args.trace_supplicant:
        debug_properties = dbus.Interface(bus.get_object('fi.w1.wpa_supplicant1','/fi/w1/wpa_supplicant1'),
                                           'org.freedesktop.DBus.Properties')
        previous_debug = str(debug_properties.Get('fi.w1.wpa_supplicant1', 'DebugLevel'))
        restore_command += ['--restore-debug', previous_debug]
    if not already_connected:
        subprocess.run(restore_command, check=True,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if args.trace_supplicant and not already_connected:
        if debug_properties.Get('fi.w1.wpa_supplicant1', 'DebugShowKeys'):
            raise RuntimeError('refusing diagnostic trace with secret-key logging enabled')
        debug_properties.Set('fi.w1.wpa_supplicant1', 'DebugLevel', 'debug')
    if args.direct_passphrase and not already_connected:
        if not target_props.get('Favorite') and str(target_props.get('IPv4.Configuration',{}).get('Method','')) in ('','off','unknown'):
            service(target).SetProperty('IPv4.Configuration',dbus.Dictionary(
                {'Method':dbus.String('dhcp')},signature='sv',variant_level=1))
            print('New HU profile: IPv4 DHCP enabled; temporary profile will be removed on restoration',flush=True)
        service(target).SetProperty('Passphrase', dbus.String(session['passphrase'], variant_level=1))
        print('ConnMan accepted the HU passphrase property (value redacted)', flush=True)
    def connected():
        os.utime(restore_clock, None)
        from carplay_proto.rtspclient import connect
        props = service(target).GetProperties()
        interface = str(props['Ethernet']['Interface'])
        print('HU Wi-Fi connected; probing AirPlay', flush=True)
        from carplay_proto.networktrace import NetworkTrace
        network_trace = NetworkTrace(target)
        print('HU IP state: {}'.format({key:str(props.get(key)) for key in ('IPv4','IPv6','IPv6.Configuration')}), flush=True)
        addresses = list(session['addresses'])
        gateway = str(props.get('IPv4', {}).get('Gateway', ''))
        if gateway and gateway not in addresses:
            addresses.append(gateway)
        for address in addresses:
            client = None
            timing = None
            try:
                client = connect(address, session['port'], interface)
                status, headers, body = client.request('GET', '/info', plistlib.dumps({}, fmt=plistlib.FMT_BINARY),
                    {'Content-Type':'application/x-apple-binary-plist', 'User-Agent':'AirPlay/566.25.21'})
                print('AirPlay /info status={}, bytes={}'.format(status, len(body)), flush=True)
                if status == 455:
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
                        pairing = pair_setup(client, identity['id'], bytes.fromhex(identity['private_key']))
                        print('AirPlay Pair-Setup peer proof verified', flush=True)
                        verified = pair_verify(client, identity['id'], bytes.fromhex(identity['private_key']), pairing)
                        print('AirPlay Pair-Verify complete; encrypted control enabled', flush=True)
                        from carplay_proto.airplaytiming import TimingServer
                        timing = TimingServer(client.sock.sock)
                        import uuid
                        setup = {'deviceID':'D8:B0:53:22:CE:CF','macAddress':'D8:B0:53:22:CE:CF',
                                 'model':'Sailplay1,1','name':'SailfishOS Sailplay','osName':'SailfishOS',
                                 'osBuildVersion':'5.2','sourceVersion':'566.25.21',
                                 'sessionUUID':str(uuid.uuid4()),'timingPort':timing.port,
                                 'features':[],'statsCollectionEnabled':False}
                        setup_status, _, setup_body = client.request('SETUP','/setup',plistlib.dumps(setup,fmt=plistlib.FMT_BINARY),
                            {'Content-Type':'application/x-apple-binary-plist','User-Agent':'AirPlay/566.25.21'})
                        print('Encrypted initial SETUP status={} bytes={}'.format(setup_status,len(setup_body)),flush=True)
                        if setup_status == 200:
                            setup_info = plistlib.loads(setup_body)
                            print('Initial SETUP response={}'.format(setup_info),flush=True)
                        status, headers, body = client.request('GET', '/info', plistlib.dumps({}, fmt=plistlib.FMT_BINARY),
                            {'Content-Type':'application/x-apple-binary-plist','User-Agent':'AirPlay/566.25.21'})
                        print('Encrypted AirPlay /info status={} bytes={}'.format(status,len(body)), flush=True)
                    except ValueError as error:
                        print(str(error), flush=True)
                if status == 200:
                    info = plistlib.loads(body)
                    with open('/tmp/sailplay-hu-info.plist','wb') as saved_info:
                        saved_info.write(plistlib.dumps(info,fmt=plistlib.FMT_BINARY))
                    print('AirPlay /info keys={}'.format(sorted(info)), flush=True)
                    for key in ('model','sourceVersion','features','statusFlags','displays','audioFormats','hidDevices'):
                        if key in info:
                            print('AirPlay {}={}'.format(key, repr(info[key])), flush=True)
                    demo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                             'diagnostics','video-demo.h264')
                    live_ui = os.path.exists(os.path.join(os.path.dirname(demo_path),'display-ui'))
                    if live_ui or os.path.exists(demo_path):
                        from carplay_proto.videodemo import run_demo
                        os.utime(restore_clock, None)
                        run_demo(client,address,interface,verified.shared,setup_info,info,demo_path,
                                 seconds=(0 if args.sustained else 45) if live_ui else 15,live=live_ui,
                                 on_activity=lambda:os.utime(restore_clock,None))
                        break
            except Exception as error:
                print('AirPlay probe failed: {}, errno={}'.format(type(error).__name__, getattr(error, 'errno', None)), flush=True)
                if isinstance(error,(RuntimeError,TimeoutError)):
                    print('Failure detail: {}'.format(str(error).replace(session['passphrase'],'<password>')),flush=True)
            finally:
                if timing:
                    timing.close()
                if client:
                    client.sock.close()
        network_trace.close()
        loop.quit()
    def failed(error):
        print('ConnMan Connect failed: {}'.format(error.get_dbus_name()), flush=True)
        if args.trace_supplicant:
            output = subprocess.run(['journalctl', '_COMM=wpa_supplicant', '--since', '-2 min', '--no-pager', '-o', 'cat'],
                                    stdout=subprocess.PIPE, universal_newlines=True).stdout
            for line in output.splitlines()[-160:]:
                print(line.replace(session['passphrase'], '<password>').replace(session['ssid'], '<HU-SSID>'), flush=True)
        loop.quit()
    if already_connected:
        print('Reusing existing HU Wi-Fi; leaving network configuration unchanged', flush=True)
        GLib.idle_add(connected)
    else:
        service(target).Connect(reply_handler=connected, error_handler=failed, timeout=25)
    GLib.timeout_add_seconds(30, lambda: (loop.quit(), False)[1])
    try:
        loop.run()
    finally:
        manager.UnregisterAgent('/org/sailplay/WifiAgent')
        agent.remove_from_connection()


if __name__ == '__main__':
    import signal
    def terminate(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,terminate)
    main()
