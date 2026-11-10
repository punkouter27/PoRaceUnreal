"""Dump TensorBoard scalars of runs to JSON for reports: python tb_dump.py out.json run1 [run2 ...] (runs/<run>/tb)."""
import json, struct, sys
from pathlib import Path

TAGS = ["eval/episode_reward", "eval/avg_episode_length", "eval/episode_reward/tracking_lin_vel", "eval/episode_reward/tracking_ang_vel"]


def _read_varint(buf, pos):
  val = 0; shift = 0
  while True:
    b = buf[pos]; pos += 1
    val |= (b & 0x7f) << shift
    if not (b & 0x80): return val, pos
    shift += 7


def _parse_proto(buf):
  pos = 0; n = len(buf); out = {}
  while pos < n:
    tag_wire, pos = _read_varint(buf, pos)
    field, wire = tag_wire >> 3, tag_wire & 7
    if wire == 0: val, pos = _read_varint(buf, pos)
    elif wire == 1: val = struct.unpack("<d", buf[pos:pos + 8])[0]; pos += 8
    elif wire == 2:
      ln, pos = _read_varint(buf, pos)
      val = buf[pos:pos + ln]; pos += ln
    elif wire == 5: val = struct.unpack("<f", buf[pos:pos + 4])[0]; pos += 4
    else: break
    out.setdefault(field, []).append(val)
  return out


def _load_scalars(tb_dir: Path):
  try:
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    ea = EventAccumulator(str(tb_dir), size_guidance={"scalars": 0}); ea.Reload()
    have = ea.Tags().get("scalars", [])
    extra = [t for t in have if t.startswith("episode/") and (t.endswith("loss") or t == "episode/length")]
    return {t: [[e.step, e.value] for e in ea.Scalars(t)] for t in TAGS + extra if t in have}
  except ImportError:
    all_scalars = {}
    for fp in sorted(tb_dir.glob("events.out.tfevents.*")):
      data = fp.read_bytes(); pos = 0
      while pos + 12 <= len(data):
        ln = struct.unpack("<Q", data[pos:pos + 8])[0]
        if pos + 16 + ln > len(data): break
        rec = data[pos + 12:pos + 12 + ln]; pos += 16 + ln
        ev = _parse_proto(rec)
        step = ev.get(2, [0])[0]
        for s_bytes in ev.get(5, []):
          s = _parse_proto(s_bytes)
          for v_bytes in s.get(1, []):
            v = _parse_proto(v_bytes)
            if 1 in v and 2 in v:
              tag = v[1][0].decode("utf-8", "ignore")
              sval = v[2][0]
              if isinstance(sval, float):
                all_scalars.setdefault(tag, []).append([step, sval])
    have = list(all_scalars.keys())
    extra = [t for t in have if t.startswith("episode/") and (t.endswith("loss") or t == "episode/length")]
    return {t: all_scalars[t] for t in TAGS + extra if t in all_scalars}


root = Path(__file__).resolve().parent
out = {}
for run in sys.argv[2:]:
  tb_dir = root / "runs" / run / "tb"
  if tb_dir.exists():
    out[run] = _load_scalars(tb_dir)
Path(sys.argv[1]).write_text(json.dumps(out))
print({r: {t: len(v) for t, v in d.items()} for r, d in out.items()})
