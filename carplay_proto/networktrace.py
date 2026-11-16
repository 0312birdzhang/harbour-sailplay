"""Persistent read-only network evidence, including discovery and daemon restart."""
import json
import threading
import time
from .runtime_logging import collection_enabled


def plain_value(value):
    """Convert D-Bus scalar types without Byte's character string conversion."""
    if isinstance(value, dict):
        return {str(key): plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_value(item) for item in value]
    if isinstance(value, bool) or type(value).__name__ == 'Boolean':
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return None if value is None else str(value)


def daemon_evidence():
    """Read current daemon exit/restart state directly from systemd."""
    if not collection_enabled():
        return
    import subprocess
    commands = [
        ['systemctl', 'show', 'connman', 'bluetooth', 'wpa_supplicant',
         '-p', 'Id', '-p', 'ActiveState', '-p', 'SubState', '-p', 'MainPID',
         '-p', 'Result', '-p', 'NRestarts', '-p', 'ExecMainCode', '-p', 'ExecMainStatus',
         '-p', 'ExecMainStartTimestamp', '-p', 'ExecMainExitTimestamp']]
    for command in commands:
        try:
            result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,universal_newlines=True,timeout=2)
            for line in result.stdout.splitlines():
                if line:
                    print('NETWORK daemon evidence '+line[:1024],flush=True)
        except (OSError,subprocess.SubprocessError):
            print('NETWORK daemon evidence unavailable',flush=True)


class NetworkTrace:
    def __init__(self,target=None,ssid=None):
        self.target,self.ssid=target,ssid
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,name='network-state',daemon=True)
        self.thread.start()

    def run(self):
        import dbus
        from .networkdbus import network_object, network_interface
        from .wifidiscovery import find_service
        bus=dbus.SystemBus(private=True)
        def interface(name,path,kind):
            return network_interface(network_object(bus,name,path),kind)
        manager=interface('net.connman','/','net.connman.Manager')
        owner_api=interface('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus')
        previous=None
        last_error=None
        last_owner=None
        try:
            while not self.stop.is_set():
                if not collection_enabled():
                    previous = last_owner = last_error = None
                    self.stop.wait(1)
                    continue
                try:
                    owner=str(owner_api.GetNameOwner('net.connman',timeout=2))
                    if owner != last_owner:
                        print('NETWORK ConnMan owner changed old={} new={}'.format(last_owner,owner),flush=True)
                        last_owner=owner
                        daemon_evidence()
                    safe={'connmanOwner':owner}
                    technologies=manager.GetTechnologies(timeout=2)
                    safe['wifi']=[{k:plain_value(p.get(k)) for k in ('Powered','Connected')}
                                  for _,p in technologies if p.get('Type')=='wifi']
                    target=self.target
                    if self.ssid:
                        services=manager.GetServices(timeout=2)
                        target=find_service(services,self.ssid,True) or find_service(services,self.ssid)
                    elif not target:
                        safe['services'] = [dict(path=str(path), **{
                            key: plain_value(props.get(key)) for key in ('State', 'Strength', 'Error', 'IPv4')})
                            for path, props in manager.GetServices(timeout=2)
                            if props.get('Type') == 'wifi' and props.get('State') != 'idle']
                    safe['targetPresent']=bool(target)
                    props={}
                    if target:
                        props=interface('net.connman',target,'net.connman.Service').GetProperties(timeout=2)
                        safe.update({k:plain_value(props.get(k)) for k in ('State','Strength','Error','IPv4','Nameservers')})
                    supp=interface('fi.w1.wpa_supplicant1','/fi/w1/wpa_supplicant1','org.freedesktop.DBus.Properties')
                    safe['supplicant']=[]
                    for path in supp.Get('fi.w1.wpa_supplicant1','Interfaces',timeout=2):
                        values=interface('fi.w1.wpa_supplicant1',path,'org.freedesktop.DBus.Properties').GetAll('fi.w1.wpa_supplicant1.Interface',timeout=2)
                        if props.get('Ethernet',{}).get('Interface') and str(values.get('Ifname'))!=str(props['Ethernet']['Interface']):continue
                        safe['supplicant'].append({k:plain_value(values.get(k)) for k in ('Ifname','State','DisconnectReason','CurrentBSS','AuthStatusCode','AssocStatusCode')})
                    if safe!=previous:
                        print('NETWORK t={:.3f} {}'.format(time.monotonic(),json.dumps(safe,sort_keys=True)),flush=True)
                        previous=safe
                    last_error=None
                except Exception as error:
                    name=getattr(error,'get_dbus_name',lambda:type(error).__name__)()
                    if name!=last_error:
                        print('NETWORK sampler waiting after error={}'.format(name),flush=True)
                        last_error=name
                        if last_owner and name in ('org.freedesktop.DBus.Error.ServiceUnknown','org.freedesktop.DBus.Error.NameHasNoOwner','org.freedesktop.DBus.Error.NoReply'):
                            daemon_evidence()
                    # Keep sampling through daemon replacement; no network mutation.
                self.stop.wait(1)
        finally:
            bus.close()

    def close(self):
        self.stop.set()
        self.thread.join(3)
