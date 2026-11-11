"""Exercise the normal example entry point with two independent clients."""
import subprocess
import sys
import time
from pathlib import Path

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

from sailplay_sdk.content import ContentClient
from sailplay_sdk.content_model import validate_content
from sailplay_sdk.contract import APP_PATH, CONTENT_INTERFACE


dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
context = GLib.MainContext.default()
root = Path(__file__).resolve().parents[1]
backend = subprocess.Popen([sys.executable, str(root / 'sdk/examples/content-service.py')])
service = 'org.example.SailplayContent'
bus = dbus.SessionBus(private=True)
bus.set_exit_on_disconnect(False)
clients = []


def wait(predicate):
    deadline = time.monotonic() + 8
    while not predicate():
        assert backend.poll() is None, 'Content backend exited with ' + str(backend.returncode)
        assert time.monotonic() < deadline
        context.iteration(False)
        time.sleep(.005)


try:
    print('CONTENT_STEP backend', flush=True)
    wait(lambda: bus.name_has_owner(service))
    results = [[], []]
    for index in range(2):
        client = ContentClient(service, presentation='car' if not index else 'phone',
            on_request=lambda *arguments, index=index: results[index].append(arguments))
        client.open()
        clients.append(client)
    wait(lambda: all(client.ready for client in clients))
    print('CONTENT_STEP clients-ready', flush=True)
    for client in clients:
        assert client.content['id'] == 'root'
    path = bus.call_blocking(service, APP_PATH, 'org.sailplay.App1', 'OpenSession', 'sas', ('car', ['content']))
    revision, value = bus.call_blocking(service, path, CONTENT_INTERFACE, 'GetContent', '', ())
    print('CONTENT_STEP typed-get', flush=True)
    assert revision == 1 and validate_content(value)['id'] == 'root'
    intruder = dbus.SessionBus(private=True)
    intruder.set_exit_on_disconnect(False)
    print('CONTENT_STEP intruder', flush=True)
    try:
        intruder.call_blocking(service, path, CONTENT_INTERFACE, 'GetContent', '', (), timeout=3)
        raise AssertionError('caller ownership was not checked')
    except dbus.DBusException as error:
        assert error.get_dbus_name() == 'org.sailplay.Error1.NotOwner'
    finally:
        intruder.close()
    print('CONTENT_STEP ownership', flush=True)
    clients[0].invoke('content.browse', {'id': 'library', 'offset': dbus.UInt32(0), 'limit': dbus.UInt32(50)})
    print('CONTENT_STEP browse-sent', flush=True)
    clients[1].invoke('content.search', {'id': 'library', 'query': 'Item 12', 'offset': dbus.UInt32(0), 'limit': dbus.UInt32(50)})
    print('CONTENT_STEP search-sent', flush=True)
    wait(lambda: all(results))
    print('CONTENT_STEP pages', flush=True)
    pages = [validate_content(result[0][2]['content']) for result in results]
    assert len(pages[0]['items']) == 50 and pages[0]['hasMore']
    assert len(pages[1]['items']) == 6
    assert all(client.content['id'] == 'root' for client in clients)
    clients[0].invoke('content.select', {'id': 'item-12'})
    wait(lambda: len(results[0]) == 2 and all(client.revision == 2 for client in clients))
    print('CONTENT_STEP action', flush=True)
    assert all(client.content['message'] == 'Selected item-12' for client in clients)
    clients[0].invoke('content.browse', {'id': 'library', 'offset': dbus.UInt32(0), 'limit': dbus.UInt32(51)})
    wait(lambda: len(results[0]) == 3)
    assert results[0][-1][3] == 'org.sailplay.Error1.InvalidArgument'
    bus.call_blocking(service, path, 'org.sailplay.Session1', 'Close', '', ())
    print('CONTENT_BUS_PASS ownership separate-pages typed-transport validation actions messages')
finally:
    for client in clients:
        client.close()
    bus.close()
    backend.terminate()
    backend.wait(timeout=5)
