"""Store of paired peers, keyed by their pairing identifier.

PairSetup learns the other peer's long-term Ed25519 key; PairVerify looks it
up by identifier when checking that peer's signature. xcertplay's
``airplay/PairingStore.kt`` keeps this in memory and fires a callback, which is
what makes it possible to persist without the store knowing about a file.
"""

import json


class PairingStore(object):
    """Identifier -> long-term public key, with an optional save hook."""

    __slots__ = ("_entries", "_on_save")

    def __init__(self, on_save=None):
        self._entries = {}
        self._on_save = on_save

    def save(self, identifier, long_term_public_key):
        """Remember a peer. Keys are copied so later mutation cannot leak."""
        identifier = _utf8_text(identifier)
        key = bytes(long_term_public_key)
        self._entries[identifier] = key
        if self._on_save is not None:
            self._on_save(identifier, key)

    def get(self, identifier):
        key = self._entries.get(_utf8_text(identifier))
        return None if key is None else bytes(key)

    def discard(self, identifier):
        return self._entries.pop(_utf8_text(identifier), None)

    def clear(self):
        self._entries.clear()

    def identifiers(self):
        return tuple(sorted(self._entries))

    def __len__(self):
        return len(self._entries)

    def __contains__(self, identifier):
        return _utf8_text(identifier) in self._entries

    def to_json(self):
        """The store as JSON text: identifier -> hex public key."""
        return json.dumps(
            dict((identifier, key.hex())
                 for identifier, key in sorted(self._entries.items())),
            indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, data, on_save=None):
        """Build a store from ``to_json`` output."""
        raw = data.decode("utf-8") if isinstance(data, bytes) else data
        entries = json.loads(raw)
        store = cls(on_save=on_save)
        for identifier, key in entries.items():
            store.save(identifier, bytes.fromhex(key))
        return store


def _utf8_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise TypeError("identifier must be str or bytes, got {!r}".format(type(value)))
