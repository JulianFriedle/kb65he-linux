from kb65he.device import KB65HE, FakeTransport, Lighting, NUM_KEYS
from kb65he.layout import KEYS, NAME_TO_INDEX, WIDTH_U
from kb65he.protocol import build_packets, checksum, choose_type, parse_response


def test_checksum_of_real_packet():
    # captured from a real keyboard: GET serial request
    pkt = bytes.fromhex("000d" + "00" * 61 + "48")
    assert checksum(pkt[:63]) == pkt[63]


def test_light_request_matches_capture():
    assert build_packets(0x19, b"", 26)[0].hex() == "0019" + "00" * 61 + "3c"


def test_packet_types():
    assert choose_type(2) == (0, 1)
    assert choose_type(59) == (0, 1)
    assert choose_type(60) == (1, 2)
    assert choose_type(276) == (1, 5)
    assert choose_type(58 * 15 + 1)[0] == 2


def test_multipacket_header_and_reassembly():
    payload = bytes(range(200))
    pkts = build_packets(0x30, payload)
    assert len(pkts) == 4
    assert pkts[0][1] >> 6 == 1
    assert pkts[2][4] == (4 << 4) | 2
    joined = b"".join(parse_response(p).data for p in pkts)
    assert joined == payload


def test_lighting_roundtrip():
    li = Lighting(on=True, effect=3, brightness=7, speed=1, color_index=2)
    assert Lighting.from_bytes(li.to_bytes()) == li
    assert len(li.to_bytes()) == Lighting.SIZE


def test_actuation_roundtrip_with_fake_device():
    kb = KB65HE(FakeTransport())
    assert len(kb.read_actuation()) == NUM_KEYS
    kb.write_actuation({k: 2.5 for k in range(NUM_KEYS)})
    assert set(kb.read_actuation().values()) == {2.5}
    # second byte must be preserved
    assert {b for _, b in kb.read_trigger().values()} == {2}


def test_layout_is_complete():
    assert sorted(k.index for k in KEYS) == list(range(NUM_KEYS))
    for row in range(5):
        width = sum(k.w for k in KEYS if k.y == row)
        if row == 1:
            width += 1.5  # ISO enter top part
        assert width == WIDTH_U
    assert NAME_TO_INDEX["W"] == 17


def test_rapid_trigger_write_keeps_actuation():
    kb = KB65HE(FakeTransport())
    kb.write_actuation({5: 1.5})
    kb.write_rapid_trigger({5: 0.3})
    assert kb.read_trigger()[5] == (15, 3)
    kb.write_trigger({6: (2.0, 4.0)})
    assert kb.read_trigger()[6] == (20, 40)
