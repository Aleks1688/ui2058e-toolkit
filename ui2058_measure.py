"""
UI2058E - one-shot measurement with metadata, saved to CSV/XLSX.

Reads N full measurement cycles from the instrument (vendor app must be closed),
computes voltage/current harmonics from the captured waveforms, writes:
    data/records/<date>_<article>_<sample>_<test>.csv   per-cycle archive
    data/master.csv                                     one summary row per run
    data/master.xlsx                                    same, ready for Excel
and prints a JSON summary (for the GUI).

CLI:
    python ui2058_measure.py --article LED-A60 --sample 1 --test 1 --cycles 3 --json
"""
import argparse
import csv
import datetime
import json
import math
import os
import re
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ui2058_reader import open_port, read_cycle, k32, wave_stats  # noqa: E402

DATA = os.path.join(HERE, "data")
RECORDS = os.path.join(DATA, "records")
WAVES = os.path.join(DATA, "waves")


def set_out_dir(path):
    """Куда писать замеры. По умолчанию data рядом со скриптом."""
    global DATA, RECORDS, WAVES
    DATA = os.path.abspath(path)
    RECORDS = os.path.join(DATA, "records")
    WAVES = os.path.join(DATA, "waves")

N = 256
HARM = [2, 3, 5, 7, 9, 11]
_COS = {k: [math.cos(2 * math.pi * k * n / N) for n in range(N)] for k in range(1, 41)}
_SIN = {k: [math.sin(2 * math.pi * k * n / N) for n in range(N)] for k in range(1, 41)}


def harmonics(wave):
    """THD and harmonic percentages from a 512-byte int16 waveform."""
    v = struct.unpack("<256h", wave)
    amps = {}
    for k in range(1, 41):
        c, s = _COS[k], _SIN[k]
        re = 0.0
        im = 0.0
        for n in range(N):
            re += v[n] * c[n]
            im += v[n] * s[n]
        amps[k] = math.hypot(re, im) * 2.0 / N
    base = amps[1]
    if base < 10:
        return {"fund": base, "thd": None, "h": {k: None for k in HARM}}
    thd = math.sqrt(sum(amps[k] ** 2 for k in range(2, 41))) / base * 100.0
    return {"fund": base, "thd": thd,
            "h": {k: amps[k] / base * 100.0 for k in HARM}}


def detect_port():
    """Номер COM-порта адаптера FTDI (USB Serial Converter VID_0403)."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
        items = {}
        i = 0
        while True:
            try:
                name, val, _ = winreg.EnumValue(k, i)
            except OSError:
                break
            items[name] = val
            i += 1
        winreg.CloseKey(k)
        for pref in ("VCP", "FTSER2K"):
            for name, val in items.items():
                if pref.lower() in name.lower():
                    return val
    except Exception:
        pass
    return "COM7"


def port_present(port):
    """Есть ли такой COM-порт в системе (адаптер подключён и включён)."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
        names = []
        i = 0
        while True:
            try:
                _, val, _ = winreg.EnumValue(k, i)
            except OSError:
                break
            names.append(str(val).upper())
            i += 1
        winreg.CloseKey(k)
        return port.upper() in names
    except Exception:
        return True  # не смогли проверить - не мешаем


def sanitize(s, default="x"):
    s = (s or "").strip()
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or default


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def fmt(x, nd=3):
    if x is None:
        return ""
    return ("%." + str(nd) + "f") % x


VAL_COLS = ["Urms, В", "Irms, А", "P, Вт", "PF", "Freq, Гц", "v5", "Irmsw, А", "PFw",
            "CFv", "CFi", "v10", "v11", "v12", "v13", "v14"]

# выход драйвера (40-байтный кадр, первые 5 float)
OUT_COLS = ["Ulamp, В", "Ilamp, А", "Pout, Вт", "IlrmsHi, А", "КПД, %"]

HARM_COLS = ["H2 U, %", "H3 U, %", "H5 U, %", "H7 U, %", "H9 U, %", "H11 U, %",
             "H2 I, %", "H3 I, %", "H5 I, %", "H7 I, %", "H9 I, %", "H11 I, %"]

MASTER_HEADER = (["Дата и время", "Артикул", "Образец", "Тест №", "Оператор", "Комментарий",
                  "Циклов"] + VAL_COLS + ["THDU, %", "THDI, %"] + HARM_COLS
                 + OUT_COLS + ["Разброс Urms, В"])

REC_HEADER = (["Цикл", "Время", "Артикул", "Образец", "Тест №", "Оператор", "Комментарий"]
              + VAL_COLS + ["THDU, %", "THDI, %"] + HARM_COLS + OUT_COLS
              + ["U мин", "U макс", "U rms", "I мин", "I макс", "I rms"])


def append_master(row):
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, "master.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(MASTER_HEADER)
        w.writerow(row)
    return path


def append_master_xlsx(row):
    try:
        from openpyxl import Workbook, load_workbook
        from openpyxl.styles import Font
    except ImportError:
        return None
    path = os.path.join(DATA, "master.xlsx")
    if os.path.exists(path):
        wb = load_workbook(path)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Замеры"
        ws.append(MASTER_HEADER)
        for c in ws[1]:
            c.font = Font(bold=True)
        ws.freeze_panes = "A2"
    out = []
    for i, v in enumerate(row):
        # числами пишем всё, кроме даты, артикула, оператора и комментария
        numeric = i >= 6 or i in (2, 3)
        try:
            out.append(float(v) if (v not in ("", None) and numeric) else v)
        except (TypeError, ValueError):
            out.append(v)
    ws.append(out)
    for col, width in (("A", 19), ("B", 18), ("C", 10), ("D", 8), ("E", 16), ("F", 26)):
        ws.column_dimensions[col].width = width
    wb.save(path)
    return path


def save_waves(tag, cycles):
    os.makedirs(WAVES, exist_ok=True)
    for idx, fr in enumerate(cycles, 1):
        for key, name in (("waveA", "U"), ("waveB", "I")):
            w = struct.unpack("<256h", fr[key])
            p = os.path.join(WAVES, "%s_c%d_%s.csv" % (tag, idx, name))
            with open(p, "w", newline="", encoding="utf-8") as f:
                wr = csv.writer(f)
                wr.writerow(["sample", "value"])
                for i, x in enumerate(w):
                    wr.writerow([i, x])


def run(args):
    os.makedirs(RECORDS, exist_ok=True)
    h = open_port(args.port)

    cycles = []
    try:
        for i in range(args.cycles):
            fr = read_cycle(h)
            if not fr:
                raise RuntimeError("прибор не ответил (цикл %d из %d)" % (i + 1, args.cycles))
            cycles.append(fr)
    finally:
        k32.CloseHandle(h)

    stamp = datetime.datetime.now()
    tag = "%s_%s_%s_%s" % (stamp.strftime("%Y-%m-%d_%H%M%S"),
                           sanitize(args.article), sanitize(args.sample), sanitize(args.test))

    per_cycle = []
    for idx, fr in enumerate(cycles, 1):
        v = struct.unpack("<15f", fr["values"])
        bo = struct.unpack("<10f", fr["block"])
        hu = harmonics(fr["waveA"])
        hi = harmonics(fr["waveB"])
        su = wave_stats(fr["waveA"])
        si = wave_stats(fr["waveB"])
        per_cycle.append({"idx": idx, "v": v, "bo": bo, "hu": hu, "hi": hi,
                          "su": su, "si": si,
                          "time": datetime.datetime.now().strftime("%H:%M:%S")})

    avg = [mean([c["v"][i] for c in per_cycle]) for i in range(15)]
    # Ulamp, Ilamp, Pout, IlrmsHi, Efficiency (доля 0..1)
    oavg = [mean([c["bo"][i] for c in per_cycle]) for i in range(5)]
    eff_pct = None if oavg[4] is None else oavg[4] * 100.0
    thdu = mean([c["hu"]["thd"] for c in per_cycle])
    thdi = mean([c["hi"]["thd"] for c in per_cycle])
    hU = {k: mean([c["hu"]["h"][k] for c in per_cycle]) for k in HARM}
    hI = {k: mean([c["hi"]["h"][k] for c in per_cycle]) for k in HARM}
    spread = max(c["v"][0] for c in per_cycle) - min(c["v"][0] for c in per_cycle)

    rec_path = os.path.join(RECORDS, tag + ".csv")
    with open(rec_path, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(REC_HEADER)
        for c in per_cycle:
            v = c["v"]
            wr.writerow([c["idx"], c["time"], args.article, args.sample, args.test,
                         args.operator, args.comment]
                        + [fmt(x, 4) for x in v]
                        + [fmt(c["hu"]["thd"], 2), fmt(c["hi"]["thd"], 2)]
                        + [fmt(c["hu"]["h"][k], 2) for k in HARM]
                        + [fmt(c["hi"]["h"][k], 2) for k in HARM]
                        + [fmt(c["bo"][0], 2), fmt(c["bo"][1], 5), fmt(c["bo"][2], 3),
                           fmt(c["bo"][3], 4), fmt(c["bo"][4] * 100.0, 1)]
                        + ["%d" % c["su"][0], "%d" % c["su"][1], fmt(c["su"][2], 1),
                           "%d" % c["si"][0], "%d" % c["si"][1], fmt(c["si"][2], 1)])

    master_row = ([stamp.strftime("%Y-%m-%d %H:%M:%S"), args.article, args.sample, args.test,
                   args.operator, args.comment, str(args.cycles)]
                  + [fmt(x, 4) for x in avg]
                  + [fmt(thdu, 2), fmt(thdi, 2)]
                  + [fmt(hU[k], 2) for k in HARM] + [fmt(hI[k], 2) for k in HARM]
                  + [fmt(oavg[0], 2), fmt(oavg[1], 5), fmt(oavg[2], 3),
                     fmt(oavg[3], 4), fmt(eff_pct, 1)]
                  + [fmt(spread, 3)])
    master_csv = append_master(master_row)
    master_xlsx = append_master_xlsx(master_row)

    if args.wave:
        save_waves(tag, cycles)

    return {
        "ok": True,
        "port": args.port,
        "article": args.article,
        "sample": args.sample,
        "test": args.test,
        "operator": args.operator,
        "cycles": args.cycles,
        "version": cycles[0].get("version", ""),
        "values": {
            "Urms_V": round(avg[0], 3), "Irms_A": round(avg[1], 4), "P_W": round(avg[2], 3),
            "PF": round(avg[3], 4), "Freq_Hz": round(avg[4], 3), "v5": round(avg[5], 4),
            "Irmsw_A": round(avg[6], 4), "PFw": round(avg[7], 4),
            "CFv": round(avg[8], 3), "CFi": round(avg[9], 3),
        },
        "output": {
            "Ulamp_V": round(oavg[0], 2), "Ilamp_A": round(oavg[1], 5),
            "Pout_W": round(oavg[2], 3), "IlrmsHi_A": round(oavg[3], 4),
            "efficiency": round(oavg[4], 4),
            "efficiency_pct": None if eff_pct is None else round(eff_pct, 1),
        },
        "thdu": None if thdu is None else round(thdu, 2),
        "thdi": None if thdi is None else round(thdi, 2),
        "harmonics_u": {("H%d" % k): (None if hU[k] is None else round(hU[k], 2)) for k in HARM},
        "harmonics_i": {("H%d" % k): (None if hI[k] is None else round(hI[k], 2)) for k in HARM},
        "spread_urms": round(spread, 3),
        "record": rec_path,
        "master_csv": master_csv,
        "master_xlsx": master_xlsx,
        "out_dir": DATA,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="", help="по умолчанию определяется автоматически (FTDI)")
    ap.add_argument("--article", required=True)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--test", required=True)
    ap.add_argument("--operator", default="")
    ap.add_argument("--comment", default="")
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--out-dir", default="", help="куда писать замеры (по умолчанию data рядом со скриптом)")
    ap.add_argument("--wave", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--json-out", default="", help="write JSON result to this file (UTF-8)")
    args = ap.parse_args()
    if args.cycles < 1:
        args.cycles = 1
    if args.cycles > 20:
        args.cycles = 20
    if not args.port:
        args.port = detect_port()
    if args.out_dir:
        set_out_dir(args.out_dir)
    else:
        set_out_dir(DATA)

    if not port_present(args.port):
        msg = ("порт %s не найден: прибор не подключён или USB-адаптер отключён "
               "в диспетчере устройств." % args.port)
        out = {"ok": False, "error": msg}
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
        print(json.dumps(out, ensure_ascii=False) if args.json else "ОШИБКА: " + msg)
        sys.exit(1)

    try:
        res = run(args)
    except Exception as e:
        msg = str(e)
        if "CreateFile" in msg or "Access" in msg or "Отказано" in msg:
            msg = "порт %s занят. Закройте программу UI2058.exe и повторите." % args.port
        out = {"ok": False, "error": msg}
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
        print(json.dumps(out, ensure_ascii=False) if args.json else "ОШИБКА: " + msg)
        sys.exit(1)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        v = res["values"]
        print("Urms %.3f В  Irms %.4f А  P %.3f Вт  PF %.3f  Freq %.3f Гц"
              % (v["Urms_V"], v["Irms_A"], v["P_W"], v["PF"], v["Freq_Hz"]))
        o = res["output"]
        print("ВЫХОД: Ulamp %.2f В  Ilamp %.5f А  Pout %.3f Вт  IlrmsHi %.4f А  КПД %.1f %%"
              % (o["Ulamp_V"], o["Ilamp_A"], o["Pout_W"], o["IlrmsHi_A"], o["efficiency_pct"] or 0.0))
        print("THDU %s %%  THDI %s %%" % (res["thdu"], res["thdi"]))
        print("запись: " + res["record"])
        print("таблица: " + res["master_csv"])


if __name__ == "__main__":
    main()