from carplay_proto import endpoints as ep
from carplay_proto.body import BodyReader


def test_every_declared_endpoint_id_is_unique():
    ids = [endpoint.id for endpoint in ep.ALL]
    assert len(ids) == len(set(ids))


def test_by_id_index_covers_all():
    assert set(ep.BY_ID) == set(endpoint.id for endpoint in ep.ALL)


def test_send_and_recv_ids_are_disjoint():
    assert not set(ep.send_ids()) & set(ep.recv_ids())


def test_send_ids_are_md_direction():
    for id in ep.send_ids():
        assert ep.BY_ID[id].direction == ep.IPHONE_TO_ACCESSORY


def test_recv_ids_are_hu_direction():
    for id in ep.recv_ids():
        assert ep.BY_ID[id].direction == ep.ACCESSORY_TO_IPHONE


def test_send_and_recv_partition_all():
    assert sorted(ep.send_ids() + ep.recv_ids()) == sorted(
        endpoint.id for endpoint in ep.ALL)


def test_declared_schemas_are_internally_consistent():
    for endpoint in ep.ALL:
        ids = set()
        for field in endpoint.fields:
            assert 0 <= field.id <= 0xffff
            assert field.id not in ids, field.name
            ids.add(field.id)
            child_ids = set()
            for child in field.children:
                assert 0 <= child.id <= 0xffff
                assert child.id not in child_ids, child.name
                child_ids.add(child.id)


def test_endpoint_metadata_is_populated():
    for endpoint in ep.ALL:
        assert endpoint.id
        assert endpoint.name
        assert endpoint.group
        assert endpoint.direction in (ep.IPHONE_TO_ACCESSORY,
                                      ep.ACCESSORY_TO_IPHONE,
                                      ep.BIDIRECTIONAL)


def test_wireless_carplay_availability_uses_boolean_semantics():
    body = ep.builder(ep.WIRELESS_CARPLAY_UPDATE, validate=False)\
        .u8(0, 0).build()
    assert BodyReader.of(body).bool(0) is False
    body = ep.builder(ep.WIRELESS_CARPLAY_UPDATE, validate=False)\
        .u8(0, 1).build()
    assert BodyReader.of(body).bool(0) is True


def test_availability_requires_availability_field():
    try:
        ep.builder(ep.WIRELESS_CARPLAY_UPDATE).u8(9, 1).build()
        assert False, "expected SchemaError"
    except Exception as error:
        assert type(error).__name__ == "SchemaError"


def test_start_session_roundtrip_matches_reference_vector():
    body = ep.builder(ep.CARPLAY_START_SESSION, validate=False)\
        .u8(8, 1).u32(2, 7000).build()
    reader = BodyReader.of(body)
    assert reader.u32(2) == 7000
    assert reader.bool(8) is True


def test_start_session_full_reference_vector():
    builder = ep.builder(ep.CARPLAY_START_SESSION, validate=True)
    body = (builder
            .group(0, lambda b: b.string(0, "fe80::2").u32(1, 3))
            .group(1, lambda b: (b.string(0, "LIVI")
                                 .string(1, "secret")
                                 .u8(2, 36)
                                 .string(3, "192.168.1.1")
                                 .string(3, "192.168.1.2")
                                 .u8(4, 3)))
            .u32(2, 7000)
            .string(3, "dev-1")
            .string(4, "pub")
            .string(5, "1.0")
            .string(6, "27.0")
            .group(7, lambda b: b.string(0, "cluster").u32(1, 4))
            .u8(8, 1).build())

    reader = BodyReader.of(body)
    wired = reader.group(0)
    wireless = reader.group(1)

    assert wired.string(0) == "fe80::2"
    assert wired.u32(1) == 3
    assert wireless.string(0) == "LIVI"
    assert len(wireless.all(3)) == 2
    assert wireless.string(3) == "192.168.1.1"
    assert [p.payload for p in wireless.all(3)] == [
        b"192.168.1.1\x00", b"192.168.1.2\x00"]
    assert reader.u32(2) == 7000
    assert reader.string(3) == "dev-1"
    assert reader.string(4) == "pub"
    assert reader.string(5) == "1.0"
    assert reader.string(6) == "27.0"
    assert reader.group(7).string(0) == "cluster"
    assert reader.group(7).u32(1) == 4
    assert reader.u8(8) == 1
    assert body.message_id == 0x4301


def test_start_session_rejects_undeclared_field():
    try:
        ep.builder(ep.CARPLAY_START_SESSION, validate=True)\
            .u8(99, 1).build()
        assert False, "expected SchemaError"
    except Exception as error:
        assert type(error).__name__ == "SchemaError"


def test_start_session_rejects_non_repeatable_field():
    try:
        builder = ep.builder(ep.CARPLAY_START_SESSION, validate=True)
        builder.u32(2, 1).u32(2, 2).build()
        assert False, "expected SchemaError"
    except Exception as error:
        assert type(error).__name__ == "SchemaError"


def test_availability_schema_shape():
    wired = ep.CARPLAY_AVAILABILITY.fields[0]
    wireless = ep.CARPLAY_AVAILABILITY.fields[1]
    themes = ep.CARPLAY_AVAILABILITY.fields[2]
    assert (wired.name, wireless.name, themes.name) == (
        "wired", "wireless", "themeAssets")
    assert wired.children[0].name == "wiredAvailable"
    assert wired.children[0].type == "U8"
    assert wired.children[1].name == "usbIdentifier"
    assert wireless.children[0].name == "wirelessAvailable"
    assert wireless.children[1].name == "bluetoothIdentifier"
    assert themes.children[0].name == "themeAssetsAvailable"


def test_identification_information_declares_capability_lists():
    fields = dict((field.name, field) for field in
                  ep.IDENTIFICATION_INFORMATION.fields)
    assert fields["MessagesSentByAccessory"].id == 6
    assert fields["MessagesSentByAccessory"].required
    assert fields["MessagesSentByAccessory"].type == "U16_LIST"
    assert fields["MessagesReceivedFromDevice"].id == 7
    assert fields["MessagesReceivedFromDevice"].required
    assert fields["supportedLanguages"].type == "STRING_LIST"
    assert fields["name"].required
    assert fields["firmwareVersion"].required


def test_identification_information_group_children():
    fields = dict((field.name, field) for field in
                  ep.IDENTIFICATION_INFORMATION.fields)
    usb = fields["USBHostTransport"]
    assert usb.type == "GROUP"
    assert [child.name for child in usb.children] == [
        "componentID", "name", "isSupported", "interfaceNumber",
        "isAvailable"]
    bt = fields["BluetoothTransport"]
    assert "bluetoothMAC" in [child.name for child in bt.children]
    wireless = fields["WirelessCarPlayTransport"]
    assert wireless.children[1].name == "SSID"


def test_device_time_update_field_types():
    fields = ep.DEVICE_TIME_UPDATE.fields
    assert [field.type for field in fields] == ["U64", "I16", "I8"]
    assert [field.name for field in fields] == [
        "secondsSinceReferenceDate", "timeZoneOffsetMinutes",
        "daylightSavingsOffsetMinutes"]


def test_wifi_information_status_is_required():
    fields = ep.WIFI_INFORMATION.fields
    assert fields[0].required and fields[0].type == "U8"
    assert [field.name for field in fields] == [
        "status", "securityType", "SSID", "passphrase"]


def test_transport_identifier_fields():
    fields = ep.DEVICE_TRANSPORT_IDENTIFIER.fields
    assert [field.name for field in fields] == [
        "bluetoothMAC", "usbTransportIdentifier"]


def test_device_uuid_update_is_a_single_string():
    fields = ep.DEVICE_UUID_UPDATE.fields
    assert len(fields) == 1
    assert fields[0].type == "STRING"
    body = ep.builder(ep.DEVICE_UUID_UPDATE, validate=False)\
        .string(0, "deadbeef").build()
    assert BodyReader.of(body).string(0) == "deadbeef"


def test_device_information_update_roundtrip():
    body = ep.builder(ep.DEVICE_INFORMATION_UPDATE, validate=False)\
        .string(0, "sailplay").build()
    assert BodyReader.of(body).string(0) == "sailplay"
    assert body.message_id == 0x4e09


def test_authentication_endpoints_are_symmetric_bytes():
    body = ep.builder(ep.AUTHENTICATION_RESPONSE, validate=False)\
        .bytes(0, b"\xde\xad").build()
    assert BodyReader.of(body).raw(0) == b"\xde\xad"


def test_required_fields_are_enforced():
    try:
        ep.builder(ep.WIFI_INFORMATION, validate=True)\
            .string(2, "ssid").build()
        assert False, "expected SchemaError"
    except Exception as error:
        assert type(error).__name__ == "SchemaError"
    body = (ep.builder(ep.WIFI_INFORMATION, validate=True)
            .string(2, "ssid").u8(0, 0).build())
    assert BodyReader.of(body).u8(0) == 0


def test_builder_message_id_comes_from_the_endpoint():
    body = ep.builder(ep.WIFI_INFORMATION, validate=False).u8(0, 0).build()
    assert body.message_id == 0x5701


def test_raw_builder_is_unvalidated():
    body = ep.raw_builder(0x6801).raw(0, b"\xde\xad\xbe\xef").build()
    assert body.message_id == 0x6801
    assert BodyReader.of(body).raw(0) == b"\xde\xad\xbe\xef"


def test_raw_builder_rejects_empty_message_id():
    try:
        ep.raw_builder(None).build()
        assert False, "expected SchemaError"
    except Exception as error:
        assert type(error).__name__ == "SchemaError"
