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
# Optional presentation hints. They travel beside the page, never inside it,
# so that a host or a provider which predates them keeps working unchanged.
PLAYBACK = ('unplayed', 'started', 'playing', 'finished')
LAYOUTS = ('list', 'grid')
HINT_FIELDS = ('image', 'playback')
MAX_IMAGE = 2048
MAX_OFFSET = (1 << 32) - 1


def _text(value, maximum=1024, required=False):
    return isinstance(value, str) and len(value) <= maximum and '\0' not in value and (value or not required)


def _integer(value, maximum=MAX_OFFSET):
    return isinstance(value, int) and not isinstance(value, (bool, Boolean)) and 0 <= value <= maximum


def _image(value):
    """An absolute local file, or an http(s) address the host may fetch."""
    return (_text(value, MAX_IMAGE, True) and not any(ord(character) < 32 for character in value)
            and (value.startswith('/') or value.startswith(('file:///', 'https://', 'http://'))))


def validate_hints(value):
    """Check the hints of one row; empty values mean the hint is absent."""
    if not isinstance(value, dict) or not set(value).issubset(HINT_FIELDS):
        raise Fault('InvalidArgument', 'unknown content presentation hint')
    image, playback = value.get('image', ''), value.get('playback', '')
    if (image != '' and not _image(image)) or (playback != '' and playback not in PLAYBACK):
        raise Fault('InvalidArgument', 'invalid content presentation hint')
    return {key: str(entry) for key, entry in (('image', image), ('playback', playback)) if entry != ''}


def _split_item(value):
    if not isinstance(value, dict):
        raise Fault('InvalidArgument', 'content item fields do not match Content1')
    hints = validate_hints({key: value[key] for key in HINT_FIELDS if key in value})
    return validate_item({key: entry for key, entry in value.items() if key not in HINT_FIELDS}), hints


def content_item(identity, title, subtitle='', kind='folder', action='', parameters=None, enabled=True,
                 image='', playback=''):
    """A row; `image` and `playback` are optional presentation hints."""
    item, hints = _split_item(dict(id=identity, title=title, subtitle=subtitle, kind=kind, action=action,
        parameters={} if parameters is None else parameters, enabled=enabled, image=image, playback=playback))
    return dict(item, **hints)


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
                 message='', message_kind='none', offset=0, has_more=False, version=1, layout=''):
    """A page; rows may carry hints and `layout` selects a standard arrangement."""
    page = dict(id=identity, title=title, version=version, items=list(items), actions=list(actions),
        searchEnabled=search_enabled, message=message, messageKind=message_kind, offset=offset, hasMore=has_more)
    if layout != '':
        page['layout'] = layout
    return merge_content(*split_content(page))


def split_content(value):
    """Separate a page from its hints: a strict Content1 page and a presentation."""
    if not isinstance(value, dict):
        raise Fault('InvalidArgument', 'content page fields do not match Content1')
    page = {key: entry for key, entry in value.items() if key != 'layout'}
    layout = value.get('layout', '')
    if layout != '' and layout not in LAYOUTS:
        raise Fault('InvalidArgument', 'unknown content layout')
    hints = {}
    for key in ('items', 'actions'):
        entries = page.get(key)
        if not isinstance(entries, (list, tuple)):
            continue
        pairs = [_split_item(entry) for entry in entries]
        page[key] = [item for item, _ in pairs]
        if key == 'items':
            hints = {item['id']: entry for item, entry in pairs if entry}
        elif any(entry for _, entry in pairs):
            raise Fault('InvalidArgument', 'page controls take no presentation hints')
    presentation = {}
    if layout != '':
        presentation['layout'] = str(layout)
    if hints:
        presentation['items'] = hints
    return validate_content(page), presentation


def clean_presentation(value, page):
    """Keep what a host can use of a received presentation; never reject the page."""
    result = {}
    if not isinstance(value, dict):
        return result
    if value.get('layout') in LAYOUTS:
        result['layout'] = str(value['layout'])
    identities = {item['id'] for item in page['items']}
    hints = {}
    entries = value.get('items')
    for identity, entry in (entries.items() if isinstance(entries, dict) else ()):
        if str(identity) not in identities or not isinstance(entry, dict):
            continue
        kept = {}
        if _image(entry.get('image')):
            kept['image'] = str(entry['image'])
        if entry.get('playback') in PLAYBACK:
            kept['playback'] = str(entry['playback'])
        if kept:
            hints[str(identity)] = kept
    if hints:
        result['items'] = hints
    return result


def merge_content(page, presentation=None):
    """Attach the usable hints of a presentation to a validated page."""
    presentation = clean_presentation(presentation, page)
    hints = presentation.get('items', {})
    result = dict(page, items=[dict(item, **hints.get(item['id'], {})) for item in page['items']])
    if 'layout' in presentation:
        result['layout'] = presentation['layout']
    return result


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
