"""Bounded Content1 pages. Browsing history belongs to each presentation."""
from .model import Fault, MAX_UINT64, state_copy

try:
    from dbus import Boolean
except ImportError:
    Boolean = bool


PAGE_FIELDS = frozenset(('id', 'title', 'version', 'items', 'actions', 'searchEnabled', 'message',
                         'messageKind', 'offset', 'hasMore'))
ITEM_FIELDS = frozenset(('id', 'title', 'subtitle', 'kind', 'action', 'parameters', 'enabled'))
MAX_ITEMS = 50
MAX_OFFSET = (1 << 32) - 1


def _text(value, maximum=1024, required=False):
    return isinstance(value, str) and len(value) <= maximum and '\0' not in value and (value or not required)


def _integer(value, maximum=MAX_OFFSET):
    return isinstance(value, int) and not isinstance(value, (bool, Boolean)) and 0 <= value <= maximum


def content_item(identity, title, subtitle='', kind='folder', action='', parameters=None, enabled=True):
    return validate_item(dict(id=identity, title=title, subtitle=subtitle, kind=kind, action=action,
                              parameters={} if parameters is None else parameters, enabled=enabled))


def validate_item(value):
    if not isinstance(value, dict) or set(value) != ITEM_FIELDS:
        raise Fault('InvalidArgument', 'content item fields do not match Content1')
    if (not _text(value['id'], 256, True) or not _text(value['title'], required=True)
            or not _text(value['subtitle']) or value['kind'] not in ('folder', 'action')
            or not _text(value['action'], 256) or not isinstance(value['enabled'], (bool, Boolean))):
        raise Fault('InvalidArgument', 'invalid content item')
    if (value['kind'] == 'action') != bool(value['action']):
        raise Fault('InvalidArgument', 'action items require an action and folders require an empty action')
    parameters = state_copy(value['parameters'])
    return dict(id=str(value['id']), title=str(value['title']), subtitle=str(value['subtitle']),
                kind=str(value['kind']), action=str(value['action']), parameters=parameters, enabled=bool(value['enabled']))


def content_page(identity='root', title='', items=(), actions=(), search_enabled=False,
                 message='', message_kind='none', offset=0, has_more=False, version=1):
    return validate_content(dict(id=identity, title=title, version=version, items=list(items), actions=list(actions),
        searchEnabled=search_enabled, message=message, messageKind=message_kind, offset=offset, hasMore=has_more))


def validate_content(value):
    if not isinstance(value, dict) or set(value) != PAGE_FIELDS:
        raise Fault('InvalidArgument', 'content page fields do not match Content1')
    if (not _text(value['id'], 256, True) or not _text(value['title']) or not _text(value['message'])
            or value['messageKind'] not in ('none', 'info', 'warning', 'error')
            or not isinstance(value['searchEnabled'], (bool, Boolean)) or not isinstance(value['hasMore'], (bool, Boolean))
            or not _integer(value['offset']) or not _integer(value['version'], MAX_UINT64)):
        raise Fault('InvalidArgument', 'invalid content page')
    lists = {}
    for key, maximum in (('items', MAX_ITEMS), ('actions', 4)):
        entries = value[key]
        if not isinstance(entries, (list, tuple)) or len(entries) > maximum:
            raise Fault('InvalidArgument', 'content page exceeds its item limit')
        lists[key] = [validate_item(item) for item in entries]
        if len({item['id'] for item in lists[key]}) != len(entries):
            raise Fault('InvalidArgument', 'content item identities must be unique within a list')
    if any(item['kind'] != 'action' for item in lists['actions']):
        raise Fault('InvalidArgument', 'page controls must be action items')
    if value['hasMore'] and (not lists['items'] or value['offset'] + len(lists['items']) > MAX_OFFSET):
        raise Fault('InvalidArgument', 'paginated content must advance its offset')
    return dict(id=str(value['id']), title=str(value['title']), version=int(value['version']),
                searchEnabled=bool(value['searchEnabled']), message=str(value['message']),
                messageKind=str(value['messageKind']), offset=int(value['offset']), hasMore=bool(value['hasMore']), **lists)


def validate_query(parameters, search=False):
    fields = {'id', 'offset', 'limit'} | ({'query'} if search else set())
    if not isinstance(parameters, dict) or set(parameters) != fields:
        raise Fault('InvalidArgument', 'content query fields do not match Content1')
    if (not _text(parameters['id'], 256, True) or not _integer(parameters['offset'])
            or not _integer(parameters['limit'], MAX_ITEMS) or not parameters['limit']
            or (search and not _text(parameters['query'], 256, True))):
        raise Fault('InvalidArgument', 'invalid content query')
    result = dict(id=str(parameters['id']), offset=int(parameters['offset']), limit=int(parameters['limit']))
    if search:
        result['query'] = str(parameters['query'])
    return result
