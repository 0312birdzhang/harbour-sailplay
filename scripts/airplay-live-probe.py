#!/usr/bin/env python3
"""Probe AirPlay on an already connected HU Wi-Fi; never change networking."""
import json
import os
import plistlib
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dbus
from carplay_proto.rtspclient import connect

with open('/tmp/sailplay-session.json') as stream:
    session = json.load(stream)
manager = dbus.Interface(dbus.SystemBus().get_object('net.connman', '/'), 'net.connman.Manager')
match = next((props for path, props in manager.GetServices() if props.get('Name') == session['ssid'] and props.get('State') in ('ready','online')), None)
if match is None:
    raise RuntimeError('HU Wi-Fi is not connected')
interface = str(match['Ethernet']['Interface'])
print('HU connection:', {key:str(match.get(key)) for key in ('State','IPv4','IPv6','IPv6.Configuration')}, flush=True)
addresses = list(session['addresses'])
gateway = str(match.get('IPv4', {}).get('Gateway', ''))
if gateway and gateway not in addresses:
    addresses.append(gateway)
for address in addresses:
    client = None
    try:
        client = connect(address, session['port'], interface)
        status, headers, body = client.request('GET', '/info', plistlib.dumps({}, fmt=plistlib.FMT_BINARY),
            {'Content-Type':'application/x-apple-binary-plist','User-Agent':'AirPlay/566.25.21'})
        print('AirPlay endpoint={} status={} bytes={}'.format(address,status,len(body)), flush=True)
        if status == 200:
            info = plistlib.loads(body)
            print('Info keys:', sorted(info), flush=True)
            for key in ('model','sourceVersion','features','statusFlags','displays','audioFormats','hidDevices','modes'):
                if key in info:
                    print(key, repr(info[key]), flush=True)
    except Exception as error:
        print('Endpoint={} error={} errno={}'.format(address,type(error).__name__,getattr(error,'errno',None)), flush=True)
    finally:
        if client:
            client.sock.close()
