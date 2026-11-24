"""
Autonomous reader for VOLNIC / HANGZHOU FORWARD UI2058E (LED lamp tester).

Talks to the instrument directly over the serial port, no vendor app needed.
The vendor application must be CLOSED (it holds the COM port exclusively).

Port setup replicates UI2058.exe exactly:
    CreateFile -> SetupComm(4096,1024) -> SetCommMask(0)
    -> SetCommTimeouts(ri=MAXDWORD, rtm=0, rtc=0, wtm=100, wtc=1000)
    -> GetCommState/SetCommState(19200 8N1, flags 0x81/0x00, DTR/RTS disabled)
    -> EscapeCommFunction(CLRRTS/CLRDTR) -> PurgeComm(RXCLEAR)

Protocol (one measurement cycle):
    0x76 'v'  -> 16 B  ASCII "UI2058E V01.00\r\n"
    0x3f '?'  ->  1 B  0x21
    0x32 '2'  ->  1 B  0x00
    0x21 '!'  -> 512 B  waveform A (256 x int16)
    0x21 '!'  -> 512 B  waveform B (256 x int16)
    0x21 '!'  ->  60 B  15 x float32 values (Urms, Irms, P, PF, Freq, ...)
    0x21 '!'  -> 512 B  waveform C (256 x int16)
    0x21 '!'  ->  40 B  block (10 x float32: Ulamp, Ilamp, Pout,
                                IlrmsHi, Efficiency, + 5 service values)

Usage:
    python ui2058_reader.py                     # COM7, until Ctrl+C
    python ui2058_reader.py --list
    python ui2058_reader.py --port COM7 --seconds 30
    python ui2058_reader.py --port COM7 --out lamp.csv --wave
"""
import argparse
import csv
import ctypes
import ctypes.wintypes as wt
import datetime
import os
import struct
import sys
import time

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
PURGE_RXCLEAR = 0x0008
CLRRTS = 4
CLRDTR = 6


class DCB(ctypes.Structure):
    _fields_ = [
        ("DCBlength", wt.DWORD), ("BaudRate", wt.DWORD),
        ("fBinary", wt.DWORD, 1), ("fParity", wt.DWORD, 1),
        ("fOutxCtsFlow", wt.DWORD, 1), ("fOutxDsrFlow", wt.DWORD, 1),
        ("fDtrControl", wt.DWORD, 2), ("fDsrSensitivity", wt.DWORD, 1),
        ("fTXContinueOnXoff", wt.DWORD, 1), ("fOutX", wt.DWORD, 1),
        ("fInX", wt.DWORD, 1), ("fErrorChar", wt.DWORD, 1),
        ("fNull", wt.DWORD, 1), ("fRtsControl", wt.DWORD, 2),
        ("fAbortOnError", wt.DWORD, 1), ("fDummy2", wt.DWORD, 17),
        ("wReserved", wt.WORD), ("XonLim", wt.WORD), ("XoffLim", wt.WORD),
        ("ByteSize", wt.BYTE), ("Parity", wt.BYTE), ("StopBits", wt.BYTE),
        ("XonChar", ctypes.c_char), ("XoffChar", ctypes.c_char),
        ("ErrorChar", ctypes.c_char), ("EofChar", ctypes.c_char),
        ("EvtChar", ctypes.c_char), ("wReserved1", wt.WORD),
    ]


class COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [("ReadIntervalTimeout", wt.DWORD),
                ("ReadTotalTimeoutMultiplier", wt.DWORD),
                ("ReadTotalTimeoutConstant", wt.DWORD),
                ("WriteTotalTimeoutMultiplier", wt.DWORD),
                ("WriteTotalTimeoutConstant", wt.DWORD)]


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wt.HANDLE
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
k32.SetupComm.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD]
k32.SetCommMask.argtypes = [wt.HANDLE, wt.DWORD]
k32.SetCommTimeouts.argtypes = [wt.HANDLE, ctypes.POINTER(COMMTIMEOUTS)]
k32.GetCommState.argtypes = [wt.HANDLE, ctypes.POINTER(DCB)]
k32.SetCommState.argtypes = [wt.HANDLE, ctypes.POINTER(DCB)]
k32.EscapeCommFunction.argtypes = [wt.HANDLE, wt.DWORD]
k32.PurgeComm.argtypes = [wt.HANDLE, wt.DWORD]
k32.WriteFile.argtypes = [wt.HANDLE, wt.LPCVOID, wt.DWORD, ctypes.POINTER(wt.DWORD), wt.LPVOID]
k32.ReadFile.argtypes = [wt.HANDLE, wt.LPVOID, wt.DWORD, ctypes.POINTER(wt.DWORD), wt.LPVOID]
k32.CloseHandle.argtypes = [wt.HANDLE]


def open_port(port):
    h = k32.CreateFileW("\\\\.\\" + port, GENERIC_READ | GENERIC_WRITE, 0,
                        None, OPEN_EXISTING, 0, None)
    if not h or h == wt.HANDLE(-1).value:
        err = ctypes.get_last_error()
        raise OSError("CreateFile(%s) failed: %s" % (port, ctypes.FormatError(err)))

    k32.SetupComm(h, 4096, 1024)
    k32.SetCommMask(h, 0)

    to = COMMTIMEOUTS()
    to.ReadIntervalTimeout = 0xFFFFFFFF
    to.ReadTotalTimeoutMultiplier = 0
    to.ReadTotalTimeoutConstant = 0
    to.WriteTotalTimeoutMultiplier = 100
    to.WriteTotalTimeoutConstant = 1000
    k32.SetCommTimeouts(h, ctypes.byref(to))

    dcb = DCB()
    dcb.DCBlength = ctypes.sizeof(DCB)
    k32.GetCommState(h, ctypes.byref(dcb))
    dcb.BaudRate = 19200
    dcb.ByteSize = 8
    dcb.Parity = 0
    dcb.StopBits = 0
    dcb.fBinary = 1
    dcb.fParity = 0
    dcb.fOutxCtsFlow = 0
    dcb.fOutxDsrFlow = 0
    dcb.fDtrControl = 0
    dcb.fDsrSensitivity = 0
    dcb.fTXContinueOnXoff = 1
    dcb.fOutX = 0
    dcb.fInX = 0
    dcb.fErrorChar = 0
    dcb.fNull = 0
    dcb.fRtsControl = 0
    dcb.fAbortOnError = 0
    if not k32.SetCommState(h, ctypes.byref(dcb)):
        raise OSError("SetCommState failed: %s" % ctypes.FormatError(ctypes.get_last_error()))
    k32.EscapeCommFunction(h, CLRRTS)
    k32.EscapeCommFunction(h, CLRDTR)
    k32.PurgeComm(h, PURGE_RXCLEAR)
    k32.PurgeComm(h, PURGE_RXCLEAR)
    return h


def wf(h, data):
    n = wt.DWORD(0)
    if not k32.WriteFile(h, data, len(data), ctypes.byref(n), None):
        raise OSError("WriteFile failed: %s" % ctypes.FormatError(ctypes.get_last_error()))
    return n.value


def read_n(h, n, timeout=1.0):
    buf = ctypes.create_string_buffer(n)
    got = bytearray()
    deadline = time.time() + timeout
    while len(got) < n and time.time() < deadline:
        rd = wt.DWORD(0)
        if k32.ReadFile(h, buf, n - len(got), ctypes.byref(rd), None) and rd.value:
            got += buf.raw[:rd.value]
        else:
            time.sleep(0.002)
    return bytes(got)


def drain(h, quiet=0.15):
    """Throw away pending bytes."""
    last = time.time()
    while time.time() - last < quiet:
        b = read_n(h, 4096, 0.03)
        if b:
            last = time.time()


def read_cycle(h, tries=3):
    """Return dict with frames or None."""
    for attempt in range(tries):
        drain(h)
        k32.PurgeComm(h, PURGE_RXCLEAR)

        wf(h, b"\x76")
        ver = read_n(h, 16, 1.0)
        if not ver.startswith(b"UI2058"):
            continue
        wf(h, b"\x3f")
        if read_n(h, 1, 1.0) != b"\x21":
            continue
        wf(h, b"\x32")
        if read_n(h, 1, 1.0) != b"\x00":
            continue

        frames = {}
        ok = True
        for name, n in (("waveA", 512), ("waveB", 512), ("values", 60),
                        ("waveC", 512), ("waveD", 512), ("block", 40)):
            wf(h, b"\x21")
            b = read_n(h, n, 1.5)
            if len(b) != n:
                ok = False
                break
            frames[name] = b
        if ok:
            frames["version"] = ver.strip().decode("ascii", "replace")
            return frames
    return None


LABELS = ["Urms_V", "Irms_A", "P_W", "PF", "Freq_Hz", "v5", "Irmsw_A", "PFw",
          "CFv", "CFi", "v10", "v11", "v12", "v13", "v14"]

OUT_LABELS = ["Ulamp_V", "Ilamp_A", "Pout_W", "IlrmsHi_A", "Efficiency",
              "t1", "t2", "t3", "t4", "t5"]


def wave_stats(b):
    if len(b) != 512:
        return (0, 0, 0.0)
    v = struct.unpack("<256h", b)
    peak = max(max(v), -min(v))
    rms = (sum(x * x for x in v) / len(v)) ** 0.5
    return (min(v), max(v), rms)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM7")
    ap.add_argument("--seconds", type=int, default=0, help="0 = until Ctrl+C")
    ap.add_argument("--out", default="")
    ap.add_argument("--wave", action="store_true", help="also store waveform stats")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        try:
            from serial.tools import list_ports
            for p in list_ports.comports():
                print("%s  %s  [%s]" % (p.device, p.description, p.hwid))
        except ImportError:
            print("pyserial not installed; look in Device Manager")
        return

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = args.out or os.path.join("captures", "auto_%s.csv" % stamp)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    csv_f = open(out, "w", newline="", encoding="utf-8-sig")
    wr = csv.writer(csv_f)
    header = ["time"] + LABELS + OUT_LABELS
    if args.wave:
        header += ["waveA_min", "waveA_max", "waveA_rms",
                   "waveB_min", "waveB_max", "waveB_rms",
                   "waveC_min", "waveC_max", "waveC_rms"]
    wr.writerow(header)
    csv_f.flush()

    try:
        h = open_port(args.port)
    except OSError as e:
        sys.exit("%s\n--- close UI2058.exe first: it holds the port exclusively." % e)

    print("open %s @19200 8N1 -> %s" % (args.port, out))
    print("Ctrl+C to stop" if not args.seconds else "running %d s" % args.seconds)

    t0 = time.time()
    good = bad = 0
    try:
        while True:
            if args.seconds and time.time() - t0 >= args.seconds:
                break
            frames = read_cycle(h)
            if not frames:
                bad += 1
                print("  cycle failed (retry)")
                time.sleep(0.3)
                continue
            good += 1
            v = struct.unpack("<15f", frames["values"])
            blk = struct.unpack("<10f", frames["block"])
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            row = [ts] + ["%.4f" % x for x in v] + ["%.4f" % x for x in blk]
            if args.wave:
                for key in ("waveA", "waveB", "waveC"):
                    row += ["%d" % x for x in wave_stats(frames[key])]
            wr.writerow(row)
            csv_f.flush()
            print("[%s] Urms=%.3f V  Irms=%.4f A  P=%.3f W  PF=%.3f  Freq=%.3f Hz  CFv=%.3f"
                  % (ts, v[0], v[1], v[2], v[3], v[4], v[8]))
            print("      Ulamp=%.2f V  Ilamp=%.5f A  Pout=%.3f W  IlrmsHi=%.4f  Eff=%.3f"
                  % (blk[0], blk[1], blk[2], blk[3], blk[4]))
    except KeyboardInterrupt:
        pass
    finally:
        k32.CloseHandle(h)
        csv_f.close()

    print("cycles ok=%d failed=%d -> %s" % (good, bad, out))


if __name__ == "__main__":
    main()