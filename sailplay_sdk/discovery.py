"""Read an application's SDK declaration from an installed desktop file."""
import configparser
import os
import re

from .contract import API_VERSION, APP_PATH


SERVICE_NAME = re.compile(r'[A-Za-z_-][A-Za-z0-9_-]*(?:\.[A-Za-z_-][A-Za-z0-9_-]*)+\Z')
OBJECT_PATH = re.compile(r'(?:/[A-Za-z0-9_]+)+\Z')
DESKTOP_ID = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*\Z')


class ApplicationDeclaration:
    def __init__(self, application_id, name, service, path, capabilities, presentation, desktop_id=None,
                 renderer_desktop=None, renderer_executable=None):
        self.application_id = application_id
        self.desktop_id = application_id if desktop_id is None else desktop_id
        self.name = name
        self.service = service
        self.path = path
        self.capabilities = tuple(capabilities)
        self.presentation = presentation
        self.renderer_desktop = renderer_desktop
        self.renderer_executable = renderer_executable

    @property
    def navigation_template(self):
        return self.presentation == 'template' and 'navigation' in self.capabilities

    @property
    def content_template(self):
        return self.presentation == 'template' and 'content' in self.capabilities


def read_declaration(path, include_hidden=False):
    """Malformed and unsupported declarations leave ordinary app discovery intact."""
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        with open(path, encoding='utf-8') as source:
            parser.read_file(source)
        entry = parser['Desktop Entry']
        if entry.get('Type') != 'Application' or entry.get('X-Sailplay-ApiVersion') != str(API_VERSION):
            return None
        if not include_hidden:
            if entry.get('Hidden', '').lower() == 'true':
                return None
            if entry.get('NoDisplay', '').lower() == 'true' and entry.get('X-Sailplay-CarOnly', '').lower() != 'true':
                return None
        service = entry.get('X-Sailplay-Service', '')
        object_path = entry.get('X-Sailplay-ObjectPath', APP_PATH)
        if len(service) > 255 or not SERVICE_NAME.fullmatch(service):
            return None
        if not OBJECT_PATH.fullmatch(object_path) or 'v1' not in object_path.split('/'):
            return None
        presentation = entry.get('X-Sailplay-Presentation', 'template')
        if presentation not in ('template', 'renderer'):
            return None
        renderer_desktop = entry.get('X-Sailplay-RendererDesktop', '')
        renderer_executable = None
        if presentation == 'renderer':
            if not DESKTOP_ID.fullmatch(renderer_desktop):
                return None
            renderer = configparser.ConfigParser(interpolation=None, strict=True)
            renderer.optionxform = str
            with open(os.path.join(os.path.dirname(path), renderer_desktop + '.desktop'), encoding='utf-8') as source:
                renderer.read_file(source)
            jail = renderer['X-Sailjail']
            identity = jail.get('OrganizationName', '') + '.' + jail.get('ApplicationName', '')
            renderer_executable = renderer['Desktop Entry'].get('Exec', '')
            if (renderer['Desktop Entry'].get('Type') != 'Application' or not SERVICE_NAME.fullmatch(identity)
                    or jail.get('Sandboxing') == 'Disabled'
                    or not re.fullmatch(r'/usr/bin/[A-Za-z0-9_.-]+', renderer_executable)):
                return None
        capabilities = tuple(value for value in entry.get('X-Sailplay-Capabilities', '').split(';') if value)
        if any(not re.fullmatch(r'[a-z][a-z0-9.-]*', value) for value in capabilities):
            return None
        desktop_id = os.path.basename(os.fspath(path))[:-len('.desktop')]
        application_id = entry.get('X-Sailplay-ApplicationId', desktop_id)
        if any(char in application_id for char in ('/', '\\', '\0')) or application_id in ('.', '..'):
            return None
        if not application_id or not desktop_id or not str(path).endswith('.desktop'):
            return None
        return ApplicationDeclaration(application_id, entry.get('Name', application_id),
                                      service, object_path, capabilities, presentation, desktop_id,
                                      renderer_desktop or None, renderer_executable)
    except (OSError, UnicodeError, configparser.Error, KeyError):
        return None


def discover(directory='/usr/share/applications'):
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    return [declaration for declaration in
            (read_declaration(os.path.join(directory, name)) for name in names if name.endswith('.desktop'))
            if declaration is not None]
