"""
UI2058E live capture (Frida).

Attaches to the running UI2058.exe and intercepts ReadFile()/WriteFile() on
the COM port, so data can be recorded while the vendor app keeps working.
Nothing is sent to the instrument - this is a passive tap.

Usage:
    python capture_live.py            # until Ctrl+C
    python capture_live.py 30         # 30 seconds

Output:
    captures/params_<stamp>.csv   60-byte frames (input values)
    captures/blocks_<stamp>.csv   40-byte frames (driver output values)
    captures/raw_<stamp>.log      every frame in hex, for protocol analysis

Requires: pip install frida
"""
import csv
import datetime
import os
import struct
import sys
import time

import frida

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "captures")
os.makedirs(OUT_DIR, exist_ok=True)

PROC_NAME = "UI2058.exe"

JS = r'''
var mods = ["kernelbase.dll", "kernel32.dll"];
function findExport(name){
  for (var i=0;i<mods.length;i++){
    try { var m = Module.load(mods[i]); var p = m.getExportByName(name); if (p) return p; } catch(e){}
  }
  return null;
}
function hook(name, cb){
  var p = findExport(name);
  if (!p) { send({t:"err", e:"no_export", name:name}); return; }
  Interceptor.attach(p, cb);
}
function toHex(ptr, len){
  try {
    var arr = new Uint8Array(ptr.readByteArray(len));
    var s = [];
    for (var i=0;i<arr.length;i++) s.push(("0"+arr[i].toString(16)).slice(-2));
    return s.join(" ");
  } catch(e){ return "<err>"; }
}
hook("ReadFile", {
  onEnter(args){ this.buf=args[1]; this.np=args[3]; },
  onLeave(retval){
    try {
      if (retval.toInt32() !== 0 && this.np) {
        var n=this.np.readU32();
        if (n>0) send({t:"read", len:n, hex:toHex(this.buf,n)});
      }
    } catch(e){}
  }
});
hook("WriteFile", {
  onEnter(args){
    try { var len=args[2].toInt32(); send({t:"write", len:len, hex:toHex(args[1],len)}); } catch(e){}
  }
});
send({t:"ready"});
'''

VAL_LABELS = ["Urms_V", "Irms_A", "P_W", "PF", "Freq_Hz", "v5", "Irmsw_A", "PFw",
              "CFv", "CFi", "v10", "v11", "v12", "v13", "v14"]
OUT_LABELS = ["Ulamp_V", "Ilamp_A", "Pout_W", "IlrmsHi_A", "Efficiency",
              "t5", "t6", "t7", "t8", "t9"]

stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
csv_path = os.path.join(OUT_DIR, "params_%s.csv" % stamp)
blk_path = os.path.join(OUT_DIR, "blocks_%s.csv" % stamp)
raw_path = os.path.join(OUT_DIR, "raw_%s.log" % stamp)

csv_f = open(csv_path, "w", newline="", encoding="utf-8-sig")
writer = csv.writer(csv_f)
writer.writerow(["time"] + VAL_LABELS)
csv_f.flush()

blk_f = open(blk_path, "w", newline="", encoding="utf-8-sig")
bwriter = csv.writer(blk_f)
bwriter.writerow(["time"] + OUT_LABELS)
blk_f.flush()

raw = open(raw_path, "w", encoding="utf-8")
raw.write("# UI2058E raw serial capture %s\n" % stamp)

stats = {"values": 0, "wave": 0, "block": 0, "ver": 0, "other": 0}


def now():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def handle_read(hexstr):
    data = bytes.fromhex(hexstr)
    n = len(data)
    raw.write("%s READ len=%d: %s\n" % (now(), n, hexstr))
    raw.flush()

    if n == 60:
        vals = struct.unpack("<15f", data)
        stats["values"] += 1
        writer.writerow([now()] + ["%.4f" % v for v in vals])
        csv_f.flush()
        print("[%s] Urms=%8.3f V  P=%8.3f W  PF=%.3f  Freq=%7.3f Hz  CFv=%.3f"
              % (now(), vals[0], vals[2], vals[3], vals[4], vals[8]))
    elif n == 512:
        stats["wave"] += 1
        wv = struct.unpack("<256h", data)
        raw.write("   wave min=%d max=%d\n" % (min(wv), max(wv)))
    elif n == 40:
        stats["block"] += 1
        blk = struct.unpack("<10f", data)
        bwriter.writerow([now()] + ["%.5f" % v for v in blk])
        blk_f.flush()
        raw.write("   block %.5f %.5f %.5f %.5f %.5f\n" % blk[:5])
        print("[%s] Ulamp=%8.2f V  Ilamp=%.5f A  Pout=%7.3f W  Eff=%.4f"
              % (now(), blk[0], blk[1], blk[2], blk[4]))
    elif n == 16:
        stats["ver"] += 1
        raw.write("   version %r\n" % data.decode("ascii", "replace").strip())
    else:
        stats["other"] += 1
        if n <= 4:
            raw.write("   ack %s\n" % hexstr)


def on_message(msg, data):
    if msg.get("type") != "send":
        raw.write("MSG %r\n" % (msg,))
        raw.flush()
        return
    p = msg["payload"]
    t = p.get("t")
    if t == "read":
        handle_read(p["hex"])
    elif t == "write":
        raw.write("%s WRITE len=%d: %s\n" % (now(), p["len"], p["hex"]))
        raw.flush()


def main():
    seconds = 0
    if len(sys.argv) > 1:
        seconds = int(sys.argv[1])

    device = frida.get_local_device()
    proc = device.get_process(PROC_NAME)
    print("attaching to %s (pid %d) ..." % (proc.name, proc.pid))
    session = device.attach(proc.pid)
    script = session.create_script(JS)
    script.on("message", on_message)
    script.load()
    print("capturing. CSV: %s" % csv_path)
    try:
        if seconds:
            t0 = time.time()
            while time.time() - t0 < seconds:
                time.sleep(0.5)
        else:
            print("press Ctrl+C to stop")
            while True:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    session.detach()
    csv_f.close()
    blk_f.close()
    raw.close()
    print("\nframes: values=%d wave=%d block=%d version=%d other=%d"
          % (stats["values"], stats["wave"], stats["block"], stats["ver"], stats["other"]))
    print("CSV  : %s" % csv_path)
    print("block: %s" % blk_path)
    print("raw  : %s" % raw_path)


if __name__ == "__main__":
    main()