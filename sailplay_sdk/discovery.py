"""Read an application's SDK declaration from an installed desktop file."""
import configparser
import os
import re

from .contract import API_VERSION, APP_PATH


SERVICE_NAME = re.compile(r'[A-Za-z_-][A-Za-z0-9_-]*(?:\.[A-Za-z_-][A-Za-z0-9_-]*)+\Z')
OBJECT_PATH = re.compile(r'(?:/[A-Za-z0-9_]+)+\Z')


class ApplicationDeclaration:
    def __init__(self, application_id, name, service, path, capabilities, presentation):
        self.application_id = application_id
        self.name = name
        self.service = service
        self.path = path
        self.capabilities = tuple(capabilities)
        self.presentation = presentation

    @property
    def navigation_template(self):
        return self.presentation == 'template' and 'navigation' in self.capabilities


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
        if not include_hidden and any(entry.get(key, '').lower() == 'true' for key in ('Hidden', 'NoDisplay')):
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
        capabilities = tuple(value for value in entry.get('X-Sailplay-Capabilities', '').split(';') if value)
        if any(not re.fullmatch(r'[a-z][a-z0-9.-]*', value) for value in capabilities):
            return None
        application_id = os.path.basename(os.fspath(path))[:-len('.desktop')]
        if not application_id or not str(path).endswith('.desktop'):
            return None
        return ApplicationDeclaration(application_id, entry.get('Name', application_id),
                                      service, object_path, capabilities, presentation)
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
