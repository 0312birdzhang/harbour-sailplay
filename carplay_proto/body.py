"""Schema-aware CSM body builder and reader."""

from . import types
from .wire import Frame, Parameter, ProtocolError, encode_params, parse_params


class Field(object):
    """One declared endpoint field.

    GROUP children use their own paramId space starting at 0.
    """

    __slots__ = ("id", "name", "type", "required", "repeatable", "children")

    def __init__(self, id, name, type, required=False, repeatable=False, children=()):
        if not 0 <= id <= 0xffff:
            raise ProtocolError("field id out of range: {}".format(id))
        self.id = id
        self.name = name
        self.type = type
        self.required = required
        self.repeatable = repeatable
        self.children = tuple(children)

    def __repr__(self):
        return "Field(0x{:04x}, {}, {})".format(self.id, self.name, self.type)


class SchemaError(ProtocolError):
    pass


class BodyBuilder(object):
    """Ordered builder preserving insertion order and repeated ids."""

    def __init__(self, fields=(), message_id=None, validate=False):
        self._fields = tuple(fields)
        self._message_id = message_id
        self._validate = validate
        self._entries = []

    def _add(self, param_id, payload, wire_type):
        self._entries.append((Parameter(param_id, payload), wire_type))
        return self

    def void(self, id):
        return self._add(id, b"", types.VOID)

    def u8(self, id, value):
        return self._add(id, types.encode(value, types.U8), types.U8)

    def bool(self, id, value):
        return self._add(id, types.encode(value, types.BOOL), types.BOOL)

    def i8(self, id, value):
        return self._add(id, types.encode(value, types.I8), types.I8)

    def u16(self, id, value):
        return self._add(id, types.encode(value, types.U16), types.U16)

    def i16(self, id, value):
        return self._add(id, types.encode(value, types.I16), types.I16)

    def u32(self, id, value):
        return self._add(id, types.encode(value, types.U32), types.U32)

    def i32(self, id, value):
        return self._add(id, types.encode(value, types.I32), types.I32)

    def u64(self, id, value):
        return self._add(id, types.encode(value, types.U64), types.U64)

    def bytes(self, id, value):
        return self._add(id, types.encode(value, types.BYTES), types.BYTES)

    def string(self, id, value):
        return self._add(id, types.encode(value, types.STRING), types.STRING)

    def strings(self, id, values):
        return self._add(id, types.encode(values, types.STRING_LIST), types.STRING_LIST)

    def u16list(self, id, values):
        return self._add(id, types.encode(values, types.U16_LIST), types.U16_LIST)

    def raw(self, id, value):
        return self._add(id, bytes(value), types.OPAQUE)

    def group(self, id, block):
        spec = self._field(id)
        child = BodyBuilder(
            fields=spec.children if spec is not None else (),
            message_id=None,
            validate=self._validate,
        )
        block(child)
        return self._add(id, child._encode(), types.GROUP)

    def optional_u8(self, id, value):
        if value is not None:
            return self.u8(id, value)
        return self

    def optional_i8(self, id, value):
        if value is not None:
            return self.i8(id, value)
        return self

    def optional_u16(self, id, value):
        if value is not None:
            return self.u16(id, value)
        return self

    def optional_i16(self, id, value):
        if value is not None:
            return self.i16(id, value)
        return self

    def optional_u32(self, id, value):
        if value is not None:
            return self.u32(id, value)
        return self

    def optional_i32(self, id, value):
        if value is not None:
            return self.i32(id, value)
        return self

    def optional_u64(self, id, value):
        if value is not None:
            return self.u64(id, value)
        return self

    def optional_bytes(self, id, value):
        if value is not None:
            return self.bytes(id, value)
        return self

    def optional_string(self, id, value):
        if value is not None:
            return self.string(id, value)
        return self

    def optional_void(self, id, present):
        if present:
            return self.void(id)
        return self

    def build(self, message_id=None):
        target = message_id if message_id is not None else self._message_id
        if target is None:
            raise SchemaError("a raw body builder needs an explicit message id")
        return Frame(target, self._encode())

    def _encode(self):
        if self._validate:
            self._check(self._fields)
        return encode_params([param for param, _ in self._entries])

    def _field(self, param_id):
        for spec in self._fields:
            if spec.id == param_id:
                return spec
        return None

    def _check(self, specs):
        by_id = dict((spec.id, spec) for spec in specs)
        counts = {}
        for param, wire_type in self._entries:
            counts[param.id] = counts.get(param.id, 0) + 1
            spec = by_id.get(param.id)
            if spec is None:
                raise SchemaError(
                    "unknown body parameter 0x{0:04x}".format(param.id))
            if spec.type != types.OPAQUE and spec.type != wire_type:
                raise SchemaError(
                    "parameter 0x{0:04x} expected {1}, got {2}".format(
                        spec.id, spec.type, wire_type))
            if not spec.repeatable and counts[param.id] > 1:
                raise SchemaError(
                    "parameter 0x{0:04x} is not repeatable".format(spec.id))
        for spec in specs:
            if spec.required and not counts.get(spec.id):
                raise SchemaError(
                    "missing required parameter 0x{0:04x} ({1})".format(
                        spec.id, spec.name))


class BodyReader(object):
    """Typed reader over an ordered CSM body.

    Unknown and repeated parameters are preserved; use ``all`` or ``first``
    rather than converting to a dict.
    """

    def __init__(self, parameters):
        self._params = tuple(parameters)

    @classmethod
    def of(cls, frame):
        return cls(frame.parameters())

    @classmethod
    def of_body(cls, body):
        return cls(parse_params(body))

    def __len__(self):
        return len(self._params)

    def __iter__(self):
        return iter(self._params)

    def is_empty(self):
        return not self._params

    def has(self, id):
        return self.first(id) is not None

    def first(self, id):
        for param in self._params:
            if param.id == id:
                return param
        return None

    def all(self, id):
        return [param for param in self._params if param.id == id]

    def require(self, id):
        param = self.first(id)
        if param is None:
            raise ProtocolError("missing parameter 0x{0:04x}".format(id))
        return param

    def _size(self, param, id, expected):
        if len(param.payload) != expected:
            raise ProtocolError(
                "parameter 0x{0:04x} must be {1} bytes, got {2}".format(
                    id, expected, len(param.payload)))

    def raw(self, id):
        return self.require(id).payload

    def optional_raw(self, id):
        param = self.first(id)
        return None if param is None else param.payload

    def void(self, id):
        param = self.require(id)
        if param.payload:
            raise ProtocolError(
                "parameter 0x{0:04x} must be empty".format(id))
        return True

    def optional_void(self, id):
        param = self.first(id)
        if param is None:
            return False
        if param.payload:
            raise ProtocolError(
                "parameter 0x{0:04x} must be empty".format(id))
        return True

    def u8(self, id):
        param = self.require(id)
        self._size(param, id, 1)
        return types.decode(param.payload, types.U8)

    def optional_u8(self, id):
        param = self.first(id)
        if param is None:
            return None
        self._size(param, id, 1)
        return types.decode(param.payload, types.U8)

    def i8(self, id):
        param = self.require(id)
        self._size(param, id, 1)
        return types.decode(param.payload, types.I8)

    def optional_i8(self, id):
        param = self.first(id)
        if param is None:
            return None
        self._size(param, id, 1)
        return types.decode(param.payload, types.I8)

    def bool(self, id):
        return self.u8(id) != 0

    def optional_bool(self, id):
        value = self.optional_u8(id)
        return None if value is None else value != 0

    def u16(self, id):
        param = self.require(id)
        self._size(param, id, 2)
        return types.decode(param.payload, types.U16)

    def optional_u16(self, id):
        param = self.first(id)
        if param is None:
            return None
        self._size(param, id, 2)
        return types.decode(param.payload, types.U16)

    def i16(self, id):
        param = self.require(id)
        self._size(param, id, 2)
        return types.decode(param.payload, types.I16)

    def optional_i16(self, id):
        param = self.first(id)
        if param is None:
            return None
        self._size(param, id, 2)
        return types.decode(param.payload, types.I16)

    def u32(self, id):
        param = self.require(id)
        self._size(param, id, 4)
        return types.decode(param.payload, types.U32)

    def optional_u32(self, id):
        param = self.first(id)
        if param is None:
            return None
        self._size(param, id, 4)
        return types.decode(param.payload, types.U32)

    def i32(self, id):
        param = self.require(id)
        self._size(param, id, 4)
        return types.decode(param.payload, types.I32)

    def optional_i32(self, id):
        param = self.first(id)
        if param is None:
            return None
        self._size(param, id, 4)
        return types.decode(param.payload, types.I32)

    def u64(self, id):
        param = self.require(id)
        self._size(param, id, 8)
        return types.decode(param.payload, types.U64)

    def optional_u64(self, id):
        param = self.first(id)
        if param is None:
            return None
        self._size(param, id, 8)
        return types.decode(param.payload, types.U64)

    def string(self, id):
        return types.decode(self.raw(id), types.STRING)

    def optional_string(self, id):
        payload = self.optional_raw(id)
        return None if payload is None else types.decode(payload, types.STRING)

    def strings(self, id):
        return types.decode(self.raw(id), types.STRING_LIST)

    def u16list(self, id):
        return types.decode(self.raw(id), types.U16_LIST)

    def group(self, id):
        return BodyReader.of_body(self.raw(id))

    def optional_group(self, id):
        payload = self.optional_raw(id)
        if payload is None:
            return None
        return BodyReader.of_body(payload)
