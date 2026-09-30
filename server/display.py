"""Whether this session's display is on (T4.6, ADR 0020).

`/ping` answering means somebody is logged in (invariant 2). It does not mean
anybody is looking: a PC left logged in with its monitor asleep still answers,
and the panel beside it used to stay lit all night. This module is the second
half of the signal. `/ping` carries what it reports, and the phone sleeps on
"off" exactly as it does when the PC is gone.

The answer is only readable because of invariant 2. This process runs inside
the owner's graphical session, so it can ask that session about its own
display. A system service could not: it has no display to ask about.

**"unknown" is the safe answer, and every failure lands there.** The phone
treats only "off" as idle, so a probe that cannot tell -- a platform with no
reader, an API that moved, a compositor this does not know -- leaves the panel
behaving exactly as it did before this module existed. Being wrong in that
direction costs a lit screen. Being wrong the other way would put the panel
dark in front of somebody using the PC, which is the one thing it must not do.

Standard library only (server/CLAUDE.md): the three readers are `ctypes` into
the platform's own libraries, or a subprocess to a tool the desktop ships.
"""
import ctypes
import ctypes.util
import re
import shutil
import subprocess
import sys
import threading
import time

ON = "on"
OFF = "off"
UNKNOWN = "unknown"

# The Windows power-setting GUID for the console session's display, and its
# payload: 0 off, 1 on, 2 dimmed. Dimmed is on -- the owner can still see it.
# https://learn.microsoft.com/windows/win32/power/power-setting-guids
GUID_CONSOLE_DISPLAY_STATE = "6fe69556-704a-47a0-8f24-c28d936fda47"
WM_POWERBROADCAST = 0x0218
PBT_POWERSETTINGCHANGE = 0x8013

# How often a subprocess-backed reader runs. The phone asks every two seconds,
# so a reading this old is never staler than the ping before it, and it is one
# fork a second and a half however many phones ask.
PERIOD_S = 1.5

# A reader that takes longer than this has answered "unknown".
SUBPROCESS_TIMEOUT_S = 1.0


def windows_state(value):
    """Pure: GUID_CONSOLE_DISPLAY_STATE's payload -> ON/OFF/UNKNOWN."""
    if value == 0:
        return OFF
    if value in (1, 2):
        return ON
    return UNKNOWN


def mutter_state(output):
    """Pure: `gdbus call ... PowerSaveMode` stdout -> ON/OFF/UNKNOWN.

    GNOME's Mutter answers `(<0>,)` for on and 1, 2 or 3 for the three DPMS
    levels of off; -1 is its own "unknown".
    """
    found = re.search(r"(-?\d+)>", output)
    if not found:
        return UNKNOWN
    mode = int(found.group(1))
    if mode == 0:
        return ON
    if mode in (1, 2, 3):
        return OFF
    return UNKNOWN


def xset_state(output):
    """Pure: `xset q` stdout -> ON/OFF/UNKNOWN.

    Reads the DPMS line, `Monitor is On` / `Off` / `in Standby` /
    `in Suspend`. DPMS disabled prints no such line, and that is "unknown":
    the monitor is then under nobody's control this server can see.
    """
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Monitor is"):
            return ON if line == "Monitor is On" else OFF
    return UNKNOWN


def macos_state(asleep_flags):
    """Pure: one CGDisplayIsAsleep per online display -> ON/OFF/UNKNOWN.

    Off only when *every* display sleeps. A laptop with its lid open beside a
    sleeping monitor is a person at a screen.
    """
    if not asleep_flags:
        return UNKNOWN
    return OFF if all(asleep_flags) else ON


class Fixed:
    """A reader that always answers the same, for `follow_display = false`,
    platforms with no reader, and tests."""

    def __init__(self, value=UNKNOWN):
        self.value = value

    def state(self):
        return self.value


class Sampled:
    """Runs a slow reader on a thread of its own, every `period_s`, and
    answers `state()` from the last reading without waiting.

    **Never in the request path.** `/ping` is the login signal, and the phone
    gives it 1500 ms before calling the PC gone (PcPoller.TIMEOUT_MS). A reader
    that forks `gdbus` and then `xset`, each allowed a second, would turn a slow
    desktop into a logout. So the request reads a variable and the fork happens
    here, off to the side, where being slow costs only freshness.

    A daemon thread, like the request threads: nothing here may keep the
    process alive after the session has gone (invariant 2). `start=False` is
    for tests, which call `sample()` by hand.
    """

    def __init__(self, read, period_s=PERIOD_S, start=True):
        self._read = read
        self._period_s = period_s
        self._value = UNKNOWN
        if start:
            threading.Thread(target=self._loop, name="display-sampler", daemon=True).start()

    def state(self):
        return self._value

    def sample(self):
        """One reading; every failure is "unknown"."""
        try:
            self._value = self._read()
        except Exception:  # noqa: BLE001 - every failure is "unknown"
            self._value = UNKNOWN
        return self._value

    def _loop(self):
        while True:
            self.sample()
            time.sleep(self._period_s)


def _run(argv):
    """A reader's subprocess: stdout, or None for anything but a clean exit."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True,
                              timeout=SUBPROCESS_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def read_linux(run=_run, which=shutil.which):
    """GNOME's Mutter first (X11 or Wayland), then X11 DPMS, else unknown.

    Other Wayland compositors -- KDE's KWin, sway -- keep their display power
    state behind their own interfaces, and this does not guess at them. They
    answer "unknown", which leaves the panel as it always behaved.
    """
    if which("gdbus"):
        out = run(["gdbus", "call", "--session",
                   "--dest", "org.gnome.Mutter.DisplayConfig",
                   "--object-path", "/org/gnome/Mutter/DisplayConfig",
                   "--method", "org.freedesktop.DBus.Properties.Get",
                   "org.gnome.Mutter.DisplayConfig", "PowerSaveMode"])
        if out is not None:
            state = mutter_state(out)
            if state != UNKNOWN:
                return state
    if which("xset"):
        out = run(["xset", "q"])
        if out is not None:
            return xset_state(out)
    return UNKNOWN


def _core_graphics():
    """CoreGraphics, loaded and typed once per process."""
    global _CG
    if _CG is None:
        cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cg.CGGetOnlineDisplayList.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
        cg.CGGetOnlineDisplayList.restype = ctypes.c_int32
        cg.CGDisplayIsAsleep.argtypes = [ctypes.c_uint32]
        cg.CGDisplayIsAsleep.restype = ctypes.c_uint32
        _CG = cg
    return _CG


_CG = None


def read_macos():
    """Every online display, asked through CoreGraphics.

    Measured on the owner's Mac on 2026-09-30: `pmset displaysleepnow` turned
    CGDisplayIsAsleep to 1 within half a second, and user activity turned it
    back. The call is in-process and costs microseconds, so it is not sampled
    on a thread like Linux's: it is asked on each /ping.
    """
    cg = _core_graphics()
    ids = (ctypes.c_uint32 * 16)()
    count = ctypes.c_uint32()
    if cg.CGGetOnlineDisplayList(16, ids, ctypes.byref(count)) != 0:
        return UNKNOWN
    return macos_state([bool(cg.CGDisplayIsAsleep(ids[i])) for i in range(count.value)])


class _MacOS:
    """The CoreGraphics reader with its failures folded into UNKNOWN."""

    def state(self):
        try:
            return read_macos()
        except Exception:  # noqa: BLE001 - every failure is "unknown"
            return UNKNOWN


class WindowsWatcher:
    """Listens for GUID_CONSOLE_DISPLAY_STATE on a hidden window of its own.

    Windows does not answer "is the monitor on?" as a query; it announces
    changes. `RegisterPowerSettingNotification` sends the current value once,
    at registration, and every change after it, as WM_POWERBROADCAST to a
    window. So this owns a thread with a hidden top-level window and a
    message loop, and `state()` reads the last value it was told. A top-level
    window rather than a message-only one: message-only windows do not
    receive broadcasts, and it costs nothing to not find out whether that
    includes this one.

    A daemon thread, like the request threads (Server.daemon_threads): nothing
    here may keep the process alive after the session has gone (invariant 2).
    """

    def __init__(self):
        self._value = UNKNOWN
        self._ready = threading.Event()
        self._proc = None  # kept alive for as long as the window exists
        threading.Thread(target=self._loop, name="display-watcher", daemon=True).start()
        # Registration delivers the current value synchronously; waiting for
        # it briefly means the first /ping after a start is not "unknown".
        self._ready.wait(2.0)

    def state(self):
        return self._value

    def on_message(self, msg, wparam, lparam):
        """The part of the window procedure worth testing: decode one message.

        Returns True if it was a display-state notification. `lparam` points
        at a POWERBROADCAST_SETTING, which is read through ctypes and never
        trusted further than its own DataLength.
        """
        if msg != WM_POWERBROADCAST or wparam != PBT_POWERSETTINGCHANGE or not lparam:
            return False
        setting = ctypes.cast(lparam, ctypes.POINTER(PowerBroadcastSetting)).contents
        if str(setting.PowerSetting) != GUID_CONSOLE_DISPLAY_STATE or setting.DataLength < 1:
            return False
        self._value = windows_state(setting.Data[0])
        self._ready.set()
        return True

    def _loop(self):
        try:
            self._run_window()
        except Exception as exc:  # noqa: BLE001 - the panel must not depend on this
            print(f"display: watcher stopped, reporting unknown: {exc}", file=sys.stderr)
            self._value = UNKNOWN
            self._ready.set()

    def _run_window(self):
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        lresult = ctypes.c_ssize_t
        wndproc_t = ctypes.WINFUNCTYPE(
            lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WndClass(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", wndproc_t),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        user32.DefWindowProcW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = lresult
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.RegisterPowerSettingNotification.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(Guid), wintypes.DWORD]
        user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        def proc(hwnd, msg, wparam, lparam):
            if self.on_message(msg, wparam, lparam):
                return 1
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc = wndproc_t(proc)
        instance = kernel32.GetModuleHandleW(None)
        wc = WndClass(lpfnWndProc=self._proc, hInstance=instance,
                      lpszClassName="DeskPanelDisplayWatcher")
        if not user32.RegisterClassW(ctypes.byref(wc)):
            raise OSError(f"RegisterClassW failed: {ctypes.get_last_error()}")
        # No WS_VISIBLE: the window exists to receive messages and is never shown.
        hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "desk-panel", 0,
                                      0, 0, 0, 0, None, None, instance, None)
        if not hwnd:
            raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")
        guid = Guid.parse(GUID_CONSOLE_DISPLAY_STATE)
        if not user32.RegisterPowerSettingNotification(hwnd, ctypes.byref(guid), 0):
            raise OSError(f"RegisterPowerSettingNotification failed: {ctypes.get_last_error()}")
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


class Guid(ctypes.Structure):
    """A Win32 GUID. Plain ctypes, so the decoding is testable off Windows."""

    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_uint8 * 8)]

    @classmethod
    def parse(cls, text):
        hexes = text.replace("-", "")
        tail = bytes.fromhex(hexes[16:])
        return cls(int(hexes[0:8], 16), int(hexes[8:12], 16), int(hexes[12:16], 16),
                   (ctypes.c_uint8 * 8)(*tail))

    def __str__(self):
        tail = bytes(self.Data4).hex()
        return f"{self.Data1:08x}-{self.Data2:04x}-{self.Data3:04x}-{tail[:4]}-{tail[4:]}"


class PowerBroadcastSetting(ctypes.Structure):
    """POWERBROADCAST_SETTING: a GUID, a length, and the first byte of the data."""

    _fields_ = [("PowerSetting", Guid), ("DataLength", ctypes.c_uint32),
                ("Data", ctypes.c_uint8 * 1)]


def watcher(config, platform=None):
    """The reader for this platform, or a Fixed(UNKNOWN) when there is none.

    `follow_display = false` in config.toml turns the whole feature off: the
    panel then follows the login alone, as it did before T4.6.
    """
    if not config.get("follow_display", True):
        return Fixed(UNKNOWN)
    platform = platform or sys.platform
    try:
        if platform == "win32":
            return WindowsWatcher()
        if platform == "darwin":
            return _MacOS()
        if platform.startswith("linux"):
            return Sampled(read_linux)
    except Exception as exc:  # noqa: BLE001 - the panel must not depend on this
        print(f"display: no reader, reporting unknown: {exc}", file=sys.stderr)
    return Fixed(UNKNOWN)
