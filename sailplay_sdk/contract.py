"""Read wire signatures from the XML shipped with the SDK."""
import os
import functools
import xml.etree.ElementTree as ET


API_VERSION = 1
APP_INTERFACE = 'org.sailplay.App1'
SESSION_INTERFACE = 'org.sailplay.Session1'
NAVIGATION_INTERFACE = 'org.sailplay.Navigation1'
APP_PATH = '/org/sailplay/v1/App'
ERROR_PREFIX = 'org.sailplay.Error1.'
INTERFACES = os.path.join(os.path.dirname(__file__), 'interfaces')


def interface_xml(name):
    if name not in (APP_INTERFACE, SESSION_INTERFACE, NAVIGATION_INTERFACE):
        raise ValueError('unsupported SDK interface')
    with open(os.path.join(INTERFACES, name + '.xml'), encoding='utf-8') as stream:
        return stream.read()


_CONTRACTS = {name: ET.fromstring(interface_xml(name)).find('interface')
              for name in (APP_INTERFACE, SESSION_INTERFACE, NAVIGATION_INTERFACE)}


def signatures(interface, member, kind='method'):
    element = _CONTRACTS[interface].find("{}[@name='{}']".format(kind, member))
    if element is None:
        raise ValueError('unknown SDK member ' + member)
    incoming, outgoing = [], []
    for argument in element.findall('arg'):
        direction = argument.get('direction', 'out' if kind == 'signal' else 'in')
        (incoming if direction == 'in' else outgoing).append(argument.attrib['type'])
    return ''.join(incoming), ''.join(outgoing)


def method(interface, member, **keywords):
    import dbus
    import dbus.service
    incoming, outgoing = signatures(interface, member)
    keywords['message_keyword'] = 'message'

    def decorate(function):
        @functools.wraps(function)
        def checked(self, *arguments, **values):
            if values['message'].get_signature() != incoming:
                raise dbus.exceptions.DBusException('method arguments do not match the SDK XML',
                    name='org.freedesktop.DBus.Error.InvalidArgs')
            return function(self, *arguments, **values)

        return dbus.service.method(interface, in_signature=incoming,
                                   out_signature=outgoing, **keywords)(checked)

    return decorate
