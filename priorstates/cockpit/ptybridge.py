#!/usr/bin/env python3
"""PTY bridge for the cockpit's embedded terminal — stdlib only.

The Node cockpit spawns this and pipes to it. It runs argv[1:] (or $SHELL) inside
a real pseudo-terminal and relays:
  • pty output      → this process's stdout   (Node forwards to the browser via SSE)
  • framed control  ← this process's stdin     (Node writes input/resize here)

Control frames on stdin:  [4-byte big-endian length][1 type byte][payload]
  type b'i'  input bytes      → written to the pty
  type b'r'  "cols,rows"       → TIOCSWINSZ on the pty
"""
import fcntl
import os
import pty
import select
import struct
import sys
import termios


def _set_winsize(fd, rows, cols):
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def main():
    cmd = sys.argv[1:] or [os.environ.get("SHELL", "/bin/bash")]
    pid, master = pty.fork()
    if pid == 0:                       # child → the shell/agent, attached to the pty
        os.execvp(cmd[0], cmd)
        os._exit(127)
    out = os.fdopen(sys.stdout.fileno(), "wb", buffering=0)
    in_fd = sys.stdin.fileno()
    buf = b""
    while True:
        try:
            r, _, _ = select.select([master, in_fd], [], [])
        except (OSError, ValueError):
            break
        if master in r:
            try:
                data = os.read(master, 65536)
            except OSError:
                data = b""
            if not data:
                break
            out.write(data)
        if in_fd in r:
            try:
                chunk = os.read(in_fd, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            buf += chunk
            while len(buf) >= 4:
                n = struct.unpack(">I", buf[:4])[0]
                if len(buf) < 4 + n:
                    break
                frame, buf = buf[4:4 + n], buf[4 + n:]
                typ, payload = frame[:1], frame[1:]
                if typ == b"i":
                    try:
                        os.write(master, payload)
                    except OSError:
                        pass
                elif typ == b"r":
                    try:
                        cols, rows = payload.decode("ascii", "replace").split(",")
                        _set_winsize(master, int(rows), int(cols))
                    except Exception:
                        pass
    try:
        os.waitpid(pid, 0)
    except OSError:
        pass


if __name__ == "__main__":
    main()
