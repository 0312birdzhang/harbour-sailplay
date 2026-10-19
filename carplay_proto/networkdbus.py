"""Bounded network RPCs which survive a ConnMan/supplicant owner replacement."""

class BoundedInterface:
    def __init__(self, interface, timeout=3):
        self.interface, self.timeout = interface, timeout

    def __getattr__(self, name):
        method = getattr(self.interface, name)
        def call(*args, **kwargs):
            kwargs.setdefault('timeout', self.timeout)
            return method(*args, **kwargs)
        return call


def network_object(bus, name, path, **kwargs):
    # Avoid implicit Introspect RPCs and caching a daemon's old unique bus name.
    kwargs.update(introspect=False, follow_name_owner_changes=True)
    return bus.get_object(name, path, **kwargs)


def network_interface(obj, name):
    import dbus
    return BoundedInterface(dbus.Interface(obj, name))


def transient_error(error):
    name = getattr(error, 'get_dbus_name', lambda: '')()
    return name in ('org.freedesktop.DBus.Error.ServiceUnknown',
                    'org.freedesktop.DBus.Error.NameHasNoOwner',
                    'org.freedesktop.DBus.Error.NoReply',
                    'org.freedesktop.DBus.Error.Disconnected',
                    'org.freedesktop.DBus.Error.UnknownObject',
                    'net.connman.Error.NotAvailable')
