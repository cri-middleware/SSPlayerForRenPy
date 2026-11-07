#!/usr/bin/env python3
"""Headless regression check for the `.ssab` file-identifier guard.

libssruntime does not validate `.ssab` input — `ss_resource_create_borrow` is
documented UB on crafted/corrupt bytes. Before those
bytes reach Rust, `SsabMeta.__init__` positively identifies the buffer via the
FlatBuffers `file_identifier` "SSAB" (the flatbuffers API
`SsAnimeBinaryBufferHasIdentifier`) and raises a diagnosable `ValueError` on a
miss. It is a positive-id gate, NOT a full structural verifier — Python's
flatbuffers runtime ships no verifier and a complete one is the SDK's (Rust) job,
so an in-range-but-semantically-wrong buffer can still reach Rust.

Plain CPython — no Ren'Py. Uses the deployed `overall/Instance.ssab` as the
positive control.

Usage:  python tools/verify_ssab_guard.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GAME = os.path.join(os.path.dirname(_HERE), "game")
sys.path.insert(0, os.path.join(_GAME, "spritestudio", "python"))

import ss_renpy  # noqa: E402
ss_renpy.bootstrap_paths()

from ss_renpy.ssab_meta import SsabMeta  # noqa: E402


def check_identifier_gate(real: bytes) -> bool:
    ok = True

    def rejects(label: str, data: bytes) -> None:
        nonlocal ok
        try:
            SsabMeta(data)
            print(f"    FAIL: {label} was accepted (expected ValueError)"); ok = False
        except ValueError:
            print(f"    ok:   {label} -> ValueError")
        except Exception as e:  # noqa: BLE001
            print(f"    FAIL: {label} raised {type(e).__name__}, want ValueError: {e}")
            ok = False

    print("identifier gate (SsabMeta rejects non-.ssab):")
    rejects("empty b''", b"")
    rejects("os.urandom(64)", os.urandom(64))
    rejects("truncated (<8 bytes)", real[:6])
    rejects("valid header, wrong magic", b"\x24\x00\x00\x00XXXX" + real[8:])
    # positive control: a real pack constructs and its fields read.
    try:
        m = SsabMeta(real)
        if m.name and m.parts():
            print(f"    ok:   real .ssab accepted (name={m.name!r}, "
                  f"{len(m.parts())} parts)")
        else:
            print("    FAIL: real .ssab parsed empty"); ok = False
    except Exception as e:  # noqa: BLE001
        print(f"    FAIL: real .ssab rejected: {e}"); ok = False
    return ok


def main(argv) -> int:
    target = argv[1] if len(argv) > 1 else os.path.join(
        _GAME, "ss_assets", "overall", "Instance.ssab")
    if not os.path.exists(target):
        print(f"SKIP: {target} not found (run scripts/deploy-examples.* first)")
        return 0
    real = open(target, "rb").read()
    print("== .ssab identifier-guard verification (SDK_UPSTREAM_ISSUES #1) ==\n")
    ok = check_identifier_gate(real)
    print("\n== RESULT:", "ALL PASS" if ok else "FAILURES PRESENT", "==")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
