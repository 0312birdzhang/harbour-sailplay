"""Run as root on SailfishOS to check non-introspected agent wire signatures.

Uses a separate bus connection and temporary agent path; does not connect,
disconnect, restart ConnMan, or replace another process's registered agent.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from carplay_proto.networkdbus import network_object, network_interface


def main():
    DBusGMainLoop(set_as_default=True)
    bus=dbus.SystemBus(private=True)
    manager=network_interface(network_object(bus,'net.connman','/'),'net.connman.Manager')
    path=dbus.ObjectPath('/org/sailplay/AgentSignatureProbe'+str(os.getpid()))
    try:
        manager.RegisterAgent(path)
        try:
            print('ConnMan accepted RegisterAgent object-path signature')
        finally:
            manager.UnregisterAgent(path)
        print('ConnMan accepted UnregisterAgent object-path signature')
    finally:
        bus.close()


if __name__=='__main__':
    main()
