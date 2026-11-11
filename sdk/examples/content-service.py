#!/usr/bin/env python3
"""A fixed content provider for browsing, search, actions and messages."""
import argparse
import signal
import sys
from pathlib import Path

root_path = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root_path if (root_path / 'sailplay_sdk').is_dir() else Path('/opt/sailplay')))

import dbus.mainloop.glib
from gi.repository import GLib

from sailplay_sdk.content import ContentBackend, wire_content
from sailplay_sdk.content_model import content_item, content_page
from sailplay_sdk.model import Fault


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--service', default='org.example.SailplayContent')
    parser.add_argument('--application-id', default='sailplay-content-example')
    arguments = parser.parse_args()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    loop = GLib.MainLoop()
    selected = [None]
    idle_timer = [0]

    def lifecycle(backend):
        if idle_timer[0]:
            GLib.source_remove(idle_timer[0])
            idle_timer[0] = 0
        if not backend.session_count and not backend.pending_count:
            def quit_if_idle():
                idle_timer[0] = 0
                if not backend.session_count and not backend.pending_count:
                    loop.quit()
                return False
            idle_timer[0] = GLib.timeout_add_seconds(10, quit_if_idle)

    def root():
        return content_page(title='Content example', search_enabled=True,
            items=[content_item('library', 'Library', '125 example items')],
            message='Choose an item' if selected[0] is None else 'Selected ' + selected[0], message_kind='info')

    def browse(parameters, invocation):
        identity = parameters['id']
        if identity not in ('root', 'library'):
            raise Fault('NotFound', 'content folder is unavailable')
        query = parameters.get('query', '').casefold()
        entries = [content_item('item-' + str(index), 'Item ' + str(index), 'Example library item',
            kind='action', action='content.select', parameters={'id': 'item-' + str(index)}) for index in range(125)]
        if query:
            entries = [entry for entry in entries if query in entry['title'].casefold()]
        if identity == 'root' and not query:
            page = root()
            if parameters['offset']:
                page['items'] = []
            page['offset'] = parameters['offset']
        else:
            offset, limit = parameters['offset'], parameters['limit']
            page = content_page(identity, 'Search results' if query else 'Library', entries[offset:offset + limit],
                search_enabled=True, offset=offset, has_more=offset + limit < len(entries),
                message='' if entries else 'No matching items', message_kind='none' if entries else 'info')
        invocation.complete({'content': wire_content(page)})

    def select(parameters, invocation):
        identity = parameters.get('id')
        if identity not in {'item-' + str(index) for index in range(125)}:
            raise Fault('NotFound', 'content item is unavailable')
        selected[0] = identity
        backend.publish({'content': root()})
        invocation.complete({'selected': identity})

    backend = ContentBackend(arguments.service, arguments.application_id,
        {'content.browse': browse, 'content.search': browse, 'content.select': select}, {'content': root()}, on_lifecycle=lifecycle)
    backend.bus.call_on_disconnection(lambda connection: loop.quit())
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, lambda number, frame: loop.quit())
    try:
        loop.run()
    finally:
        if idle_timer[0]:
            GLib.source_remove(idle_timer[0])
        backend.close()


if __name__ == '__main__':
    main()
