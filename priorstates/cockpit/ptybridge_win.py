#!/usr/bin/env python3
"""Windows PTY bridge for the cockpit terminal.

Mirrors ptybridge.py's wire contract so the cockpit server (server.py) treats
both bridges identically. Runs argv[1:] (or a shell) attached to a real
pseudo-console and relays:
  pty output      -> this process's stdout (binary)   (cockpit -> browser via SSE)
  framed control  <- this process's stdin              (cockpit -> input/resize)

Control frames on stdin: [4-byte big-endian length][1 type byte][payload]
  b'i' input bytes -> written to the pty
  b'r' "cols,rows" -> resize

Three tiers, best-first:
  1. pywinpty -- a real ConPTY (with a helper agent) that gives the child CONSOLE
     std handles even though this bridge's own handles are pipes. This is the only
     tier that yields a true TTY for interactive CLIs (codex etc.); installed by
     the Windows installer / `pip install priorstates[winterm]`.
  2. raw ctypes ConPTY -- stdlib-only; renders ANSI nicely but can't present a
     true TTY when the bridge's handles are pipes (the common cockpit case).
  3. plain piped shell -- always works for simple, non-interactive commands.
"""
import os
import struct
import subprocess
import sys
import threading
import time


def _binary_stdio():
    """Stop the CRT from translating CRLF on the byte streams we relay."""
    if os.name == "nt":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)


def _read_exact(stream, n):
    buf = b""
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _frames(stream):
    """Yield (type_byte, payload) control frames sent by the cockpit."""
    while True:
        hdr = _read_exact(stream, 4)
        if hdr is None:
            return
        (n,) = struct.unpack(">I", hdr)
        body = _read_exact(stream, n) if n else b""
        if body is None:
            return
        yield body[:1], body[1:]


# --------------------------------------------------------------------------- #
# ConPTY (preferred): a real pseudo-console via the Win32 API through ctypes.
# --------------------------------------------------------------------------- #
def run_conpty(cmd) -> bool:
    """Returns True if it ran a ConPTY session to completion, False if ConPTY is
    unavailable / setup failed (so the caller falls back to a piped shell)."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not hasattr(k32, "CreatePseudoConsole"):
        return False                       # pre-1809 Windows

    HPCON = wintypes.HANDLE
    LPVOID = ctypes.c_void_p
    SIZE_T = ctypes.c_size_t
    ULONG_PTR = ctypes.c_size_t

    class COORD(ctypes.Structure):
        _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
            ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", LPVOID)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    k32.CreatePipe.argtypes = [ctypes.POINTER(wintypes.HANDLE),
                               ctypes.POINTER(wintypes.HANDLE), LPVOID, wintypes.DWORD]
    k32.CreatePipe.restype = wintypes.BOOL
    k32.CreatePseudoConsole.argtypes = [COORD, wintypes.HANDLE, wintypes.HANDLE,
                                        wintypes.DWORD, ctypes.POINTER(HPCON)]
    k32.CreatePseudoConsole.restype = ctypes.c_long      # HRESULT
    k32.ResizePseudoConsole.argtypes = [HPCON, COORD]
    k32.ResizePseudoConsole.restype = ctypes.c_long
    k32.ClosePseudoConsole.argtypes = [HPCON]
    k32.ClosePseudoConsole.restype = None
    k32.InitializeProcThreadAttributeList.argtypes = [
        LPVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(SIZE_T)]
    k32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    k32.UpdateProcThreadAttribute.argtypes = [
        LPVOID, wintypes.DWORD, ULONG_PTR, LPVOID, SIZE_T, LPVOID, ctypes.POINTER(SIZE_T)]
    k32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    k32.DeleteProcThreadAttributeList.argtypes = [LPVOID]
    k32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, LPVOID, LPVOID, wintypes.BOOL,
        wintypes.DWORD, LPVOID, wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOEXW), ctypes.POINTER(PROCESS_INFORMATION)]
    k32.CreateProcessW.restype = wintypes.BOOL
    k32.ReadFile.argtypes = [wintypes.HANDLE, LPVOID, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD), LPVOID]
    k32.ReadFile.restype = wintypes.BOOL
    k32.WriteFile.argtypes = [wintypes.HANDLE, LPVOID, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), LPVOID]
    k32.WriteFile.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]

    PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
    EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    INFINITE = 0xFFFFFFFF

    # 1) two pipes: we write input to inW (ConPTY reads inR); ConPTY writes
    #    output to outW (we read outR).
    inR, inW = wintypes.HANDLE(), wintypes.HANDLE()
    outR, outW = wintypes.HANDLE(), wintypes.HANDLE()
    if not k32.CreatePipe(ctypes.byref(inR), ctypes.byref(inW), None, 0):
        return False
    if not k32.CreatePipe(ctypes.byref(outR), ctypes.byref(outW), None, 0):
        return False

    # 2) the pseudo console wired to those pipe ends
    hPC = HPCON()
    if k32.CreatePseudoConsole(COORD(80, 24), inR, outW, 0, ctypes.byref(hPC)) != 0:
        return False

    # 3) STARTUPINFOEX carrying the pseudoconsole as a process attribute
    si = STARTUPINFOEXW()
    si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
    needed = SIZE_T(0)
    k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(needed))  # sizing call
    attr_buf = (ctypes.c_byte * needed.value)()
    si.lpAttributeList = ctypes.cast(attr_buf, LPVOID)
    if not k32.InitializeProcThreadAttributeList(si.lpAttributeList, 1, 0, ctypes.byref(needed)):
        return False
    if not k32.UpdateProcThreadAttribute(
            si.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
            hPC, ctypes.sizeof(HPCON), None, None):
        return False

    # 4) launch the child attached to the pseudo console
    cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(cmd))
    pi = PROCESS_INFORMATION()
    ok = k32.CreateProcessW(None, cmdline, None, None, False,
                            EXTENDED_STARTUPINFO_PRESENT, None, None,
                            ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        return False
    # the parent doesn't need the ends ConPTY now owns
    k32.CloseHandle(inR)
    k32.CloseHandle(outW)

    out_handle, in_handle = outR, inW

    def reader():                          # ConPTY output -> our stdout
        buf = (ctypes.c_char * 65536)()
        nread = wintypes.DWORD(0)
        out = sys.stdout.buffer
        while True:
            if not k32.ReadFile(out_handle, buf, 65536, ctypes.byref(nread), None) or nread.value == 0:
                break
            try:
                out.write(buf.raw[:nread.value]); out.flush()
            except Exception:
                break
        os._exit(0)                        # child output closed -> end the bridge

    def waiter():                          # child exit -> close console, unblock reader
        k32.WaitForSingleObject(pi.hProcess, INFINITE)
        try:
            k32.ClosePseudoConsole(hPC)
        except Exception:
            pass

    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=waiter, daemon=True).start()

    nwrote = wintypes.DWORD(0)
    for typ, payload in _frames(sys.stdin.buffer):
        if typ == b"i" and payload:
            b = (ctypes.c_char * len(payload)).from_buffer_copy(payload)
            k32.WriteFile(in_handle, b, len(payload), ctypes.byref(nwrote), None)
        elif typ == b"r":
            try:
                cols, rows = payload.decode("ascii", "replace").split(",")
                k32.ResizePseudoConsole(hPC, COORD(int(cols), int(rows)))
            except Exception:
                pass
    # cockpit closed our stdin -> tear the session down
    try:
        k32.ClosePseudoConsole(hPC)
        k32.TerminateProcess(pi.hProcess, 0)
    except Exception:
        pass
    return True


# --------------------------------------------------------------------------- #
# Fallback: a piped shell (no real PTY -- cursor addressing won't render).
# --------------------------------------------------------------------------- #
def run_pipe_fallback(cmd):
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, bufsize=0)

    def reader():
        out = sys.stdout.buffer
        while True:
            d = p.stdout.read(65536)
            if not d:
                break
            try:
                out.write(d); out.flush()
            except Exception:
                break
        os._exit(0)

    threading.Thread(target=reader, daemon=True).start()
    for typ, payload in _frames(sys.stdin.buffer):
        if typ == b"i" and payload:
            try:
                p.stdin.write(payload); p.stdin.flush()
            except Exception:
                break
        # 'r' resize: a plain pipe has no window size -> ignored
    try:
        p.terminate()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Preferred: pywinpty (a real ConPTY with a helper agent). It correctly gives
# the child CONSOLE std handles even though this bridge process itself has piped
# std handles -- the edge case raw ctypes ConPTY can't handle, and the reason
# interactive CLIs (codex, etc.) otherwise report "stdin is not a terminal".
# --------------------------------------------------------------------------- #
def run_winpty(cmd) -> bool:
    import winpty   # raises ImportError if not installed -> caller falls through
    proc = winpty.PtyProcess.spawn(list(cmd), cwd=os.getcwd(),
                                   env=dict(os.environ), dimensions=(24, 80))

    def reader():
        out = sys.stdout.buffer
        while True:
            try:
                data = proc.read(65536)        # str (utf-8); ConPTY emits utf-8
            except EOFError:
                break
            except Exception:
                break
            if data:
                try:
                    out.write(data.encode("utf-8", "replace") if isinstance(data, str) else data)
                    out.flush()
                except Exception:
                    break
            else:
                if not proc.isalive():
                    break
                time.sleep(0.01)        # in case read() is non-blocking
        os._exit(0)

    threading.Thread(target=reader, daemon=True).start()
    for typ, payload in _frames(sys.stdin.buffer):
        if typ == b"i" and payload:
            try:
                proc.write(payload.decode("utf-8", "replace"))
            except Exception:
                break
        elif typ == b"r":
            try:
                cols, rows = payload.decode("ascii", "replace").split(",")
                proc.setwinsize(int(rows), int(cols))
            except Exception:
                pass
    try:
        proc.terminate(force=True)
    except Exception:
        pass
    return True


def main():
    _binary_stdio()
    cmd = sys.argv[1:] or [os.environ.get("COMSPEC", "cmd.exe")]
    # 1) pywinpty -- a real TTY (handles this bridge's piped std handles).
    try:
        if run_winpty(cmd):
            return
    except Exception:
        pass
    # 2) raw ctypes ConPTY -- nice ANSI rendering, but not a true TTY when the
    #    bridge's own handles are pipes (so interactive TUI CLIs may complain).
    try:
        if run_conpty(cmd):
            return
    except Exception:
        pass
    # 3) plain piped shell -- always works for simple commands.
    run_pipe_fallback(cmd)


if __name__ == "__main__":
    main()
