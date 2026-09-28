"""BlackShark V2 Pro (2020), receiver 1532:0528.

This receiver uses 64-byte feature reports with report ID 0xFF on the
0xFF00 vendor collection. The request was captured from Synapse in
https://github.com/openrazer/openrazer/issues/1280 and also documented at
https://github.com/Modzeleczek/RazerNariBatteryLevel .
It must not be sent through the 2023 model's PA transport.
"""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

import hid

from .base import hexdump

PID = 0x0528
CABLE_PID = 0x052E
REPORT_ID = 0xFF
REPORT_LEN = 64
REQUEST = bytes.fromhex("ff 0a 00 fd 04 12 f1 02 05").ljust(REPORT_LEN, b"\x00")
REPLY_PREFIX = bytes.fromhex("ff 0f 05 fe 12 04 1f 08 05")
# With no new response from the headset, the receiver retains the old payload
# under this header. Never use its stale battery or charging bytes.
NO_REPLY_PREFIX = bytes.fromhex("ff 01 00 fe 12 04 1f 08 05")


def is_candidate(info: dict) -> bool:
    return info.get("usage_page") == 0xFF00 and info.get("usage") == 0x01


def parse_reply(data) -> Optional[Tuple[int, int, int]]:
    """Return (power state, millivolts, reported level byte) for a complete reply.

    Keep the report ID: unlike the generic Razer protocol, it is part of the
    64-byte frame. Do not accept a request echo or an unrelated feature reply.
    """
    data = bytes(data or [])
    if len(data) != REPORT_LEN or not data.startswith(REPLY_PREFIX):
        return None
    state = data[11]
    voltage = int.from_bytes(data[12:14], "big")
    return state, voltage, data[14]


def read_battery(path: bytes, diag: List[str]) -> Tuple[str, Optional[int], bool]:
    """Return ('ok'|'offline'|'fail', level or None, charging).

    Byte 14 remained 0x50 through extended charging, then changed to 0x64
    with state 0x06 when headset LED indicated a full charge.
    The same byte remained 100 after unplugging, with state 0x01.
    """
    dev = hid.device()
    try:
        dev.open_path(path)
        written = dev.send_feature_report(REQUEST)
        if written != REPORT_LEN:
            diag.append(f"    [2020] short feature write: {written}")
            return "fail", None, False
        # Synapse waits about 100 ms between SET_REPORT and GET_REPORT.
        # A bounded retry also accommodates a reply that is not ready yet.
        deadline = time.monotonic() + 0.5
        while True:
            time.sleep(0.1)
            data = dev.get_feature_report(REPORT_ID, REPORT_LEN)
            diag.append(f"    [2020] feature ff: {hexdump(data, 16)}")
            result = parse_reply(data)
            if result is not None:
                state, voltage, raw14 = result
                diag.append(f"    [2020] power={state:02x} voltage={voltage}mV "
                            f"byte14={raw14:02x}")
                if voltage == 0:
                    return "offline", None, False
                if state not in (0x01, 0x06, 0x09):
                    diag.append(f"    [2020] unknown power state: {state:02x}")
                    return "fail", None, False
                level = raw14 if 0 <= raw14 <= 100 else None
                diag.append(f"    [2020] device-reported level={level}")
                return "ok", level, state == 0x09
            if time.monotonic() >= deadline:
                if len(data) == REPORT_LEN and bytes(data).startswith(NO_REPLY_PREFIX):
                    diag.append("    [2020] no fresh headset reply (off / out of range)")
                    return "offline", None, False
                diag.append("    [2020] no valid battery reply")
                return "fail", None, False
    except (OSError, ValueError) as e:
        diag.append(f"    [2020] HID: {e}")
        return "fail", None, False
    finally:
        try:
            dev.close()
        except OSError:
            pass
