import json
import os

import pytest

from kb65he import probe as pr
from kb65he.protocol import build_packets, checksum


def test_only_odd_ids_are_read_commands():
    assert pr.is_read_cmd(0x01) and pr.is_read_cmd(0x3F) and pr.is_read_cmd(0x05)
    for bad in (0, 2, 0x18, 0x30, 0x34, 0x40, 0x41, 0xFF, -1, True, None, "5"):
        assert not pr.is_read_cmd(bad)
        with pytest.raises(pr.UnsafeCommand):
            pr.build_read_request(bad)


def test_default_ids_are_odd_unknown_reads():
    assert pr.DEFAULT_IDS and all(c & 1 for c in pr.DEFAULT_IDS)
    assert not set(pr.DEFAULT_IDS) & pr.KNOWN_READS
    assert 0x03 in pr.DEFAULT_IDS and 0x07 in pr.DEFAULT_IDS and 0x3F in pr.DEFAULT_IDS


def test_parse_ids_rejects_writes():
    assert pr.parse_ids("0x03, 7,0x0B,7") == [3, 7, 0x0B]
    for bad in ("0x02", "3,4", "0x18", "0x41", "0"):
        with pytest.raises(pr.UnsafeCommand):
            pr.parse_ids(bad)
    with pytest.raises(ValueError):
        pr.parse_ids("abc")
    with pytest.raises(ValueError):
        pr.parse_ids(" , ")


def test_read_request_matches_known_capture():
    # same bytes as the captured "get lighting" request in test_protocol.py
    assert pr.build_read_request(0x19).hex() == "0019" + "00" * 61 + "3c"


def test_packet_check_rejects_everything_but_empty_reads():
    good = pr.build_read_request(0x07)
    pr.check_read_only_packet(good)
    # even id with a correct checksum
    even = bytearray(good)
    even[1] = 0x06
    even[63] = checksum(even[:63])
    with pytest.raises(pr.UnsafeCommand):
        pr.check_read_only_packet(bytes(even))
    # payload hidden in an odd command
    payload = build_packets(0x07, b"\x01")[0]
    with pytest.raises(pr.UnsafeCommand):
        pr.check_read_only_packet(payload)
    # multi-packet type, wrong size, report id, bad checksum
    multi = build_packets(0x31, b"", 200)[0]
    for bad in (multi, good[:-1], b"\x00" + good, good[:63] + b"\x00"):
        with pytest.raises(pr.UnsafeCommand):
            pr.check_read_only_packet(bad)


def test_write_packets_never_reach_the_device():
    dev = pr.FakeProbeDevice()
    link = pr.ReadOnlyLink(dev)
    for cmd in (0x00, 0x18, 0x1A, 0x20, 0x30, 0x34, 0x02):
        with pytest.raises(pr.UnsafeCommand):
            link.request(cmd, 0.1)
    # the device layer refuses a hand-made write packet as well
    with pytest.raises(pr.UnsafeCommand):
        dev.exchange(build_packets(0x30, bytes([17, 2, 4, 2]))[0], 0.1)
    assert dev.sent == []


def test_scan_sends_only_odd_ids_and_classifies():
    dev = pr.FakeProbeDevice()
    lines = []
    res = pr.run_scan(pr.ReadOnlyLink(dev), pr.DEFAULT_IDS, sleep=lambda _s: None, log=lines.append,
                      max_timeouts=len(pr.DEFAULT_IDS) + 1)
    assert dev.sent and all((p[1] & 0x3F) & 1 for p in dev.sent)
    assert all(p[1] >> 6 == 0 and p[3] == 0 for p in dev.sent)
    assert len(dev.sent) == len(pr.DEFAULT_IDS) + 2          # control before and after
    by_cmd = {r["cmd"]: r for r in res["results"] if r["role"] == "probe"}
    assert by_cmd[0x0B]["outcome"] == "data" and by_cmd[0x0B]["data"] == "01 02 03 04"
    assert by_cmd[0x07]["outcome"] == "status:NOT_SUPPORTED"
    assert by_cmd[0x03]["outcome"] == "timeout"
    s = res["summary"]
    assert s["interesting"] == ["0x0B"] and s["control_ok_after"]
    assert s["recognised"] == ["0x0B"]                       # NOT_SUPPORTED and timeouts do not count
    assert s["error_status"] == {"0x07": "NOT_SUPPORTED"}
    assert any("<-- DATA" in line for line in lines)
    json.dumps(res)                                           # must be serialisable


def test_scan_stops_when_control_read_fails():
    dev = pr.FakeProbeDevice({0x05: None})
    res = pr.run_scan(pr.ReadOnlyLink(dev), [3, 7], sleep=lambda _s: None, log=lambda _l: None)
    assert len(dev.sent) == 1
    assert res["summary"]["control_ok_after"] is False


def test_scan_warns_when_keyboard_stops_answering():
    state = {"n": 0}

    def control(n):
        return bytes(4) if n == 1 else None                   # second control read fails

    dev = pr.FakeProbeDevice({0x05: control})
    lines = []
    res = pr.run_scan(pr.ReadOnlyLink(dev), [3], sleep=lambda _s: None, log=lines.append)
    assert not res["summary"]["control_ok_after"]
    assert any("replug" in line for line in lines)
    del state


def test_scan_refuses_even_ids_in_api():
    with pytest.raises(pr.UnsafeCommand):
        pr.run_scan(pr.ReadOnlyLink(pr.FakeProbeDevice()), [3, 4])


def test_analyse_bad_checksum_and_error_status():
    err = pr.make_response(0x07, 3, b"")                      # error status keeps a stale checksum
    info = pr.analyse_response(err)
    assert pr.classify(info) == "status:NOT_SUPPORTED"
    bad = bytearray(pr.make_response(0x09, 0, b"\x01"))
    bad[63] ^= 0xFF
    assert pr.classify(pr.analyse_response(bytes(bad))) == "bad-checksum"
    assert pr.classify(pr.analyse_response(pr.make_response(0x09, 0, b""))) == "empty"
    assert pr.classify(pr.analyse_response(b"\x00" * 10)) == "odd"
    assert pr.classify(None) == "timeout"


def test_highlight_changes_marks_bytes():
    assert pr.highlight_changes(b"\x00\x01\x02", b"\x00\x05\x02") == "00 [05] 02"
    assert pr.highlight_changes(None, b"\x01\x02") == "01 02"
    out = pr.highlight_changes(b"\x00\x01", b"\x00\x02", color=True)
    assert "\x1b[1;31m02\x1b[0m" in out and "\x1b[1;31m00" not in out
    # trailing zeros that did not change are dropped, changes there are not
    long_prev = bytes(40)
    long_cur = bytes(39) + b"\x07"
    assert pr.highlight_changes(long_prev, long_cur).endswith("[07]")


def test_repeat_reports_changing_bytes():
    def depth(n):
        return bytes([1, 2, 0, 0]) + bytes([0 if n < 4 else 25, 0])

    dev = pr.FakeProbeDevice({0x0B: depth})
    t = {"now": 0.0}

    def clock():
        return t["now"]

    def sleep(s):
        t["now"] += s

    lines = []
    res = pr.run_repeat(pr.ReadOnlyLink(dev), 0x0B, seconds=1.0, interval=0.1,
                        log=lines.append, clock=clock, sleep=sleep)
    assert res["samples"] in (10, 11)
    assert res["changed_offsets"] == [8]                      # raw offset of payload byte 4
    assert res["value_ranges"]["8"] == {"min": 0, "max": 25, "distinct": 2}
    assert res["verdict"] == "answer changed while polling"
    assert any("[19]" in line for line in lines)              # 25 == 0x19, marked
    assert all((p[1] & 0x3F) == 0x0B for p in dev.sent)
    json.dumps(res)


def test_repeat_constant_answer_and_rate_limit():
    dev = pr.FakeProbeDevice({0x05: bytes(4)})
    t = {"now": 0.0}

    def sleep(s):
        t["now"] += s

    res = pr.run_repeat(pr.ReadOnlyLink(dev), 0x05, seconds=1.0, interval=0.0,
                        log=lambda _l: None, clock=lambda: t["now"], sleep=sleep)
    assert res["verdict"] == "answer never changed"
    assert res["interval_s"] == 0.02 and len(dev.sent) <= 51   # capped at 50 requests per second
    with pytest.raises(pr.UnsafeCommand):
        pr.run_repeat(pr.ReadOnlyLink(dev), 0x30, seconds=1)


def test_repeat_gives_up_without_answers():
    dev = pr.FakeProbeDevice({0x0B: None})
    res = pr.run_repeat(pr.ReadOnlyLink(dev), 0x0B, seconds=5.0, log=lambda _l: None,
                        clock=lambda: 0.0, sleep=lambda _s: None)
    assert res["verdict"] == "no answers" and len(dev.sent) == 5


def test_descriptor_summary():
    desc = bytes.fromhex(
        "06 01 ff 09 01 a1 01 85 04 15 00 26 ff 00 75 08 95 3f 09 02 81 02 c0")
    s = pr.summarise_descriptor(desc)
    assert s["usage_pages"] == ["0xFF01"]
    assert s["report_ids"] == [4]
    assert s["input_bytes_per_report_id"] == {"4": 63}
    plain = pr.summarise_descriptor(bytes.fromhex("06 01 ff 09 01 a1 01 75 08 95 40 81 02 c0"))
    assert plain["report_ids"] == [] and plain["input_bytes_per_report_id"] == {"0": 64}


def test_describe_report():
    ev = bytes([4, 0x96, 0, 7]) + bytes(60)
    assert pr.describe_report(ev).startswith("EVENT 0x96: brightness")
    assert "unknown code 0xA5" in pr.describe_report(bytes([4, 0xA5, 0, 0]))
    assert pr.describe_report(pr.make_response(0x05, 0, b"\x01")).startswith("config packet cmd=0x05")
    assert pr.describe_report(bytes(8)) == ""


def test_watch_reads_without_writing(tmp_path):
    r, w = os.pipe()
    os.set_blocking(r, False)
    os.write(w, bytes([4, 0x97, 0, 2]) + bytes(60))
    node = pr.HidNode("/dev/fake0", 0x5035, b"\x06\x01\xff")
    lines = []
    t = {"now": 0.0}

    def clock():
        t["now"] += 0.2
        return t["now"]

    res = pr.run_watch([node], 1.0, log=lines.append, clock=clock, opener=lambda _p: r)
    os.close(w)
    assert res["report_count"] == 1
    assert res["reports"][0]["label"].startswith("EVENT 0x97")
    assert res["events_seen"] and any("EVENT 0x97" in line for line in lines)
    out = pr.write_report({"watch": res}, str(tmp_path / "r.json"))
    assert json.load(open(out))["watch"]["report_count"] == 1


def test_report_file_contains_no_serial_and_is_valid_json(tmp_path):
    dev = pr.FakeProbeDevice({0x05: bytes(4), 0x0D: b"SECRET-SERIAL"})
    node = pr.HidNode("/dev/hidraw9", 0x5035, bytes.fromhex("06 01 ff 09 01 a1 01 c0"))
    rep = pr.new_report("scan", [node])
    rep["scan"] = pr.run_scan(pr.ReadOnlyLink(dev), [3], sleep=lambda _s: None, log=lambda _l: None)
    path = pr.write_report(rep, str(tmp_path / "probe.json"))
    text = open(path).read()
    assert "SECRET" not in text and 0x0D not in [p[1] & 0x3F for p in dev.sent]
    data = json.loads(text)
    assert data["mode"] == "scan" and data["nodes"][0]["vendor_interface"] is True
    assert data["scan"]["summary"]["control_ok_after"] is True


def test_cli_probe_demo_and_rejects_writes(tmp_path, capsys):
    from kb65he import cli
    out = tmp_path / "demo.json"
    cli.main(["--demo", "probe", "-y", "--out", str(out)])
    assert json.load(open(out))["scan"]["summary"]["interesting"] == ["0x0B"]
    with pytest.raises(SystemExit):
        cli.main(["--demo", "probe", "--ids", "0x30", "--out", str(tmp_path / "no.json")])
    with pytest.raises(SystemExit):
        cli.main(["--demo", "probe", "--repeat", "0x18", "--out", str(tmp_path / "no.json")])
    assert not (tmp_path / "no.json").exists()
    capsys.readouterr()


def test_hidraw_device_exchange_over_socketpair():
    import socket
    import threading

    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    dev = pr.HidrawProbeDevice.__new__(pr.HidrawProbeDevice)
    dev.path, dev.verbose = "socket", False
    dev.fd = os.dup(a.fileno())
    os.set_blocking(dev.fd, False)
    seen = []

    def keyboard():
        req = b.recv(256)
        seen.append(req)
        b.send(bytes([4, 0x96, 0, 5]) + bytes(60))              # pushed event first
        b.send(pr.make_response(req[2] & 0x3F, 0, b"\x07\x08"))  # then the answer

    th = threading.Thread(target=keyboard)
    th.start()
    ex = dev.exchange(pr.build_read_request(0x0B), 1.0)
    th.join()
    assert len(seen[0]) == 65 and seen[0][0] == 0 and seen[0][2] & 0x3F == 0x0B
    assert pr.analyse_response(ex.response)["data"] == "07 08"
    assert [s[1] for s in ex.stray] == [0x96]
    # no answer -> None after the timeout, no exception
    ex = dev.exchange(pr.build_read_request(0x0D), 0.05)
    assert ex.response is None
    with pytest.raises(pr.UnsafeCommand):
        dev.exchange(build_packets(0x30, b"\x01\x02\x03\x04")[0], 0.05)
    assert b.recv(256, socket.MSG_DONTWAIT)[2] & 0x3F == 0x0D   # the 0x0D request ...
    with pytest.raises(BlockingIOError):                         # ... and nothing after it
        b.recv(256, socket.MSG_DONTWAIT)
    dev.close()
    a.close()
    b.close()


def test_scan_stops_after_three_unanswered_requests():
    # real fw: ~24 unanswered requests made the keyboard drop off the bus
    dev = pr.FakeProbeDevice()
    lines = []
    res = pr.run_scan(pr.ReadOnlyLink(dev), [0x03, 0x09, 0x0F, 0x11, 0x13], sleep=lambda _s: None,
                      log=lines.append)
    probes = [r for r in res["results"] if r["role"] == "probe"]
    assert [r["cmd"] for r in probes] == [0x03, 0x09, 0x0F]
    assert res["summary"]["stopped_early"] == "3 unanswered requests in a row"
    assert res["results"][-1]["role"] == "control-after"
    assert any("stopping early" in line for line in lines)


def test_scan_handles_device_disappearing():
    class Gone(pr.FakeProbeDevice):
        def exchange(self, packet, timeout):
            if packet[1] & 0x3F == 0x09:
                raise OSError(5, "Input/output error")
            return super().exchange(packet, timeout)

    res = pr.run_scan(pr.ReadOnlyLink(Gone()), [0x03, 0x09, 0x0B], sleep=lambda _s: None, log=lambda _l: None)
    assert res["results"][-1]["outcome"] == "device_lost"
    assert res["summary"]["stopped_early"] == "device_lost"
    assert not res["summary"]["control_ok_after"]
    json.dumps(res)
