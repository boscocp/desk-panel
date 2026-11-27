#!/usr/bin/env python3
"""Fail if the phone on adb has a setting on that stops the panel working.

Developer options -> "Stay awake" keeps the screen on whenever the phone is
charging, and the phone on this desk is always charging. With it on, the app
does everything right -- `state=idle`, `screen=sleep`, `FLAG_KEEP_SCREEN_ON`
released -- and the screen stays lit anyway, dimmed, on the lock screen. No
error appears anywhere, in the app or the system.

ADR 0005 and docs/INSTALL-PHONE.md said it must be off. On 2026-11-26 it was on
(`stay_on_while_plugged_in=7`, all three power sources), and the panel stayed
lit for 85 minutes in front of a PC whose monitor had gone to sleep. Nothing in
the repository sets it; `scrcpy --stay-awake` sets exactly 7, but whether that
was the cause is not confirmed. A sentence in a document did not hold, so it is
a command now (T4.16), run by `make install-phone` and `make e2e`.

It does not fix anything. Turning it off is one command, printed on failure.

Exit codes: 0 every setting holds, 1 one does not, 2 adb could not read it.
"""

import subprocess
import sys

# (namespace, key, wanted value, why, how to fix)
SETTINGS = (
    (
        "global",
        "stay_on_while_plugged_in",
        "0",
        'Developer options -> "Stay awake" is on: the screen never sleeps while '
        "charging, so the panel cannot follow the PC (ADR 0005)",
        "adb shell settings put global stay_on_while_plugged_in 0",
    ),
)


def verdicts(read):
    """Return one failure line per setting that does not hold.

    `read(namespace, key)` returns the value as `settings get` prints it, and
    raises ConnectionError when adb could not be asked. An unset key prints
    "null", which is not the wanted value: an unknown state is not a passing one.
    """
    failures = []
    for namespace, key, wanted, why, fix in SETTINGS:
        value = read(namespace, key)
        if value != wanted:
            failures.append(f"{namespace} {key}={value}, wanted {wanted}: {why}\n  fix: {fix}")
    return failures


def adb_read(namespace, key):
    try:
        result = subprocess.run(
            ["adb", "shell", "settings", "get", namespace, key],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ConnectionError(f"adb: {error}") from error
    if result.returncode != 0:
        # adb's own words: "no devices", "more than one device", "unauthorized".
        raise ConnectionError(f"adb: {result.stderr.strip() or 'exit ' + str(result.returncode)}")
    return result.stdout.strip()


SELF_TEST_CASES = (
    ("off holds", {"stay_on_while_plugged_in": "0"}, 0),
    ("ac+usb+wireless fails", {"stay_on_while_plugged_in": "7"}, 1),
    ("usb only fails", {"stay_on_while_plugged_in": "2"}, 1),
    ("unset is not a pass", {"stay_on_while_plugged_in": "null"}, 1),
)


def self_test(stream=sys.stdout):
    failures = 0
    for name, values, expected in SELF_TEST_CASES:
        got = len(verdicts(lambda _ns, key, v=values: v[key]))
        ok = got == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {got} failure(s), expected {expected}", file=stream)
    try:
        def unreachable(_ns, _key):
            raise ConnectionError("adb: no devices/emulators found")
        verdicts(unreachable)
        print("FAIL adb unreachable: no error raised", file=stream)
        failures += 1
    except ConnectionError:
        print("ok   adb unreachable raises", file=stream)
    total = len(SELF_TEST_CASES) + 1
    print(f"{total - failures}/{total} self-test cases passed", file=stream)
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv[1:]:
        return self_test()
    if argv[1:]:
        print(f"check_phone_settings: unknown arguments {argv[1:]}", file=sys.stderr)
        return 2
    try:
        failures = verdicts(adb_read)
    except ConnectionError as error:
        print(f"check_phone_settings: could not read the phone ({error})", file=sys.stderr)
        return 2
    for line in failures:
        print(f"check_phone_settings: {line}", file=sys.stderr)
    if failures:
        return 1
    print("check_phone_settings: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
