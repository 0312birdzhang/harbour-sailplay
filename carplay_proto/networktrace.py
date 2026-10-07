"""Independent read-only network sampling while the GLib thread sends video."""
import threading
import time


class NetworkTrace:
    def __init__(self,target):
        self.target=target
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def run(self):
        import dbus
        bus=dbus.SystemBus(private=True)
        service=dbus.Interface(bus.get_object('net.connman',self.target),'net.connman.Service')
        previous=None
        try:
            while not self.stop.is_set():
                props=service.GetProperties(timeout=2)
                safe={k:str(props.get(k)) for k in ('State','Error','IPv4','Nameservers')}
                supp=dbus.Interface(bus.get_object('fi.w1.wpa_supplicant1','/fi/w1/wpa_supplicant1'),
                                     'org.freedesktop.DBus.Properties')
                for path in supp.Get('fi.w1.wpa_supplicant1','Interfaces',timeout=2):
                    values=dbus.Interface(bus.get_object('fi.w1.wpa_supplicant1',path),
                        'org.freedesktop.DBus.Properties').GetAll('fi.w1.wpa_supplicant1.Interface',timeout=2)
                    if str(values.get('Ifname'))==str(props.get('Ethernet',{}).get('Interface')):
                        safe['supplicant']={k:str(values.get(k)) for k in ('State','DisconnectReason','CurrentBSS')}
                if safe!=previous:
                    print('NETWORK t={:.3f} {}'.format(time.monotonic(),safe),flush=True)
                    previous=safe
                self.stop.wait(.25)
        except Exception as error:
            print('NETWORK sampler error={}'.format(type(error).__name__),flush=True)
        finally:
            bus.close()

    def close(self):
        self.stop.set()
        self.thread.join(3)
