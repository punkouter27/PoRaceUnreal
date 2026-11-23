"""Build the static showcase site into web/dist (what the workflow deploys to the Static Web App).

    python web/build.py            # writes web/dist
    python web/build.py --check    # build into a temp dir and validate only (nothing written in the repo)

The policy viewer (/viewer): for each entry of site.json "replays" this script ships the brain's ONNX (dist/policies/)
and a recorded CPU MuJoCo rollout of that brain (docs/parity/*.json: per 50 Hz control step the policy input `obs`, its
output `action`, and the body positions from forward kinematics of the recorded qpos) as dist/data/<name>.json. The page
runs the ONNX in the browser (onnxruntime-web) on each recorded obs and compares the result with the recorded action;
no physics runs in the page. The build checks the same with onnxruntime on CPU (`pyMaxDiff`) and stops above 1e-4.

Version: ONE stamp, computed here once and injected into index.html, diag.html and version.json: "v" + the UTC
yyMMdd of the HEAD commit's committer date (falls back to today, UTC, outside a git checkout). Unreal's Build.cs
uses the same rule, so the game's build stamp and the site's agree for the same commit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
STATIC = ["style.css", "diag.js", "viewer.js", "idle.js", "favicon.svg"]
GROUPS = ("api", "data", "service")
KINDS = ("files", "version", "none", "inference")
ORT_URL = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.20.1/dist/ort.wasm.min.mjs"  # the viewer's import (viewer.js)
MAX_POLICY_DIFF = 1e-4


def version_stamp() -> tuple[str, str]:
    """('vYYMMDD', commit sha or '') from the HEAD commit time in UTC."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%ct %H"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
        when = dt.datetime.fromtimestamp(int(out[0]), tz=dt.UTC)
        return "v" + when.strftime("%y%m%d"), out[1]
    except (OSError, subprocess.CalledProcessError, IndexError, ValueError):
        return "v" + dt.datetime.now(dt.UTC).strftime("%y%m%d"), ""


def render_content(site: dict, shots: list[dict]) -> str:
    e = html.escape
    # the title is shown once, in the top bar; the page heading is the tagline
    parts = [f"<h1>{e(site['tagline'])}</h1>", '<div class="prose">']
    parts += [f"<p>{e(p)}</p>" for p in site["intro"]]
    parts.append("</div>")
    parts.append('<ul class="facts">')
    parts += [f"<li><b>{e(k)}</b>{e(v)}</li>" for k, v in site["facts"]]
    parts.append("</ul>")
    parts.append(
        "<h2>Watch a brain run</h2><p>The racers&rsquo; trained brains run in your browser on recorded races: "
        '<a class="cta" href="/viewer">Open the policy viewer</a></p>'
    )
    parts.append('<h2 id="screenshots">Screenshots</h2><div class="shots">')
    for s in shots:
        parts.append(
            f'<figure><img src="{e(s["url"])}" width="{s["width"]}" height="{s["height"]}" loading="lazy" '
            f'alt="{e(s["caption"])}"><figcaption>{e(s["caption"])}</figcaption></figure>'
        )
    parts.append("</div>")
    parts.append(
        f'<h2>Source</h2><p><a class="cta" href="{e(site["repo"])}" rel="noopener">View the repository</a></p>'
    )
    return "\n".join(parts)


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path}: not a PNG")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def expand_checks(spec: dict, dist: Path, shot_urls: list[str], policy_urls: list[str]) -> dict:
    out = []
    names = set()
    for c in spec["checks"]:
        for key in ("name", "group", "kind", "label", "purpose"):
            if not c.get(key):
                raise SystemExit(f"diag_checks.json: check {c} has no {key}")
        if c["group"] not in GROUPS or c["kind"] not in KINDS:
            raise SystemExit(f"diag_checks.json: {c['name']}: group must be {GROUPS}, kind {KINDS}")
        if c["name"] in names:
            raise SystemExit(f"diag_checks.json: duplicate check {c['name']}")
        names.add(c["name"])
        item = {k: c[k] for k in ("name", "group", "kind", "label", "purpose")}
        if c["kind"] == "files":
            lists = {"@screenshots": shot_urls, "@policies": policy_urls}
            paths = lists[c["files"]] if isinstance(c["files"], str) else c["files"]
            files = []
            for p in paths:
                f = dist / p.lstrip("/")
                if not f.is_file():
                    raise SystemExit(f"diag_checks.json: {c['name']}: {p} is not in the build")
                kind = "image" if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") else "file"
                files.append({"path": "/" + p.lstrip("/"), "bytes": f.stat().st_size, "type": kind})
            item["files"] = files
        elif c["kind"] == "inference":
            # load onnxruntime-web from the CDN the viewer uses, run the first replay's policy on its first recorded
            # observation and compare with the recorded action
            if c["url"] != ORT_URL or ORT_URL not in (WEB / "viewer.js").read_text(encoding="utf-8"):
                raise SystemExit(f"diag_checks.json: {c['name']}: {c['url']} is not what viewer.js imports ({ORT_URL})")
            first = json.loads((dist / "data" / "replays.json").read_text(encoding="utf-8"))[0]
            item.update(url=c["url"], policy="/" + first["policy"], data=f"/data/{first['name']}.json")
        elif c["kind"] == "version":
            if not (dist / c["path"].lstrip("/")).is_file():
                raise SystemExit(f"diag_checks.json: {c['path']} is not in the build")
            item["path"] = c["path"]
        else:
            item["detail"] = c["detail"]
        out.append(item)
    groups = {c["group"] for c in out}
    if groups != set(GROUPS):
        raise SystemExit(f"diag_checks.json: every section needs a check, missing {set(GROUPS) - groups}")
    return {"checks": out}


def build_replays(site: dict, dist: Path) -> list[dict]:
    """dist/policies/<brain>.onnx + dist/data/<name>.json per replay, and the list the viewer loads (data/replays.json)."""
    import mujoco
    import numpy as np
    import onnxruntime as ort

    (dist / "data").mkdir(parents=True, exist_ok=True)
    (dist / "policies").mkdir(exist_ok=True)
    index = []
    for rp in site["replays"]:
        rec = json.loads((ROOT / rp["recording"]).read_text(encoding="utf-8"))
        char = json.loads((ROOT / "training" / "characters" / f"{rp['character']}.json").read_text(encoding="utf-8"))
        onnx = ROOT / "training" / "models" / "brains" / f"{rp['brain']}.onnx"
        frames = rec["frames"]
        obs = np.array([f["obs"] for f in frames], np.float32)
        act = np.array([f["action"] for f in frames], np.float32)
        sess = ort.InferenceSession(str(onnx), providers=["CPUExecutionProvider"])
        inp = sess.get_inputs()[0]
        if inp.shape[1] != obs.shape[1]:
            raise SystemExit(f"{rp['name']}: {onnx.name} takes {inp.shape[1]} obs, the recording has {obs.shape[1]}")
        out = np.concatenate([sess.run(None, {inp.name: o[None]})[0] for o in obs])
        diff = float(np.abs(out - act).max())
        if diff > MAX_POLICY_DIFF:
            raise SystemExit(f"{rp['name']}: {onnx.name} does not reproduce {rp['recording']} (max diff {diff:.2e})")
        m = mujoco.MjModel.from_xml_path(str(ROOT / rp["model"]))
        d = mujoco.MjData(m)
        root = m.body(char["rootBody"]).id
        bodies = [b for b in range(1, m.nbody) if m.body_rootid[b] == m.body_rootid[root]]
        # stick figure: each body to its parent, and each leaf body to its farthest geom (foot, hand, wheel)
        segs, tips = [], []
        for b in bodies:
            if b != root and m.body_parentid[b] in bodies:
                segs.append([bodies.index(b), bodies.index(m.body_parentid[b])])
            geoms = [g for g in range(m.ngeom) if m.geom_bodyid[g] == b]
            if geoms and b not in m.body_parentid[bodies]:
                far = max(geoms, key=lambda g: float(np.linalg.norm(m.geom_pos[g])))
                tips.append(far)
                segs.append([len(bodies) + len(tips) - 1, bodies.index(b)])
        pts = []
        for f in frames:
            q = np.asarray(f["qpos"], np.float64)
            if q.size != m.nq:
                raise SystemExit(f"{rp['name']}: qpos has {q.size} values, {rp['model']} needs {m.nq}")
            d.qpos[:] = q
            mujoco.mj_kinematics(m, d)
            xyz = np.vstack([d.xpos[bodies], d.geom_xpos[tips]]) if tips else d.xpos[bodies]
            if not np.isfinite(xyz).all():
                raise SystemExit(f"{rp['name']}: non-finite body positions")
            pts.append([round(float(v), 3) for v in xyz.ravel()])
        name = rp["name"]
        data = {
            "segments": segs,
            "frames": pts,
            "obs": [[round(float(v), 6) for v in o] for o in obs],
            "action": [[round(float(v), 6) for v in a] for a in act],
        }
        (dist / "data" / f"{name}.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        shutil.copyfile(onnx, dist / "policies" / onnx.name)
        stage = next((s["stage"] for s in reversed(STAGES) if s["stage"] in rp["brain"]), None)
        index.append(
            {
                "name": name,
                "label": rp["label"],
                "racer": char["racerName"],
                "color": char["racerColor"],
                "policy": f"policies/{onnx.name}",
                "brain": rp["brain"],
                "stage": f"{stage} ({rp['brain']})" if stage else f"{rp['brain']} (no curriculum stage in its name)",
                "command": rec.get("command"),
                "frameTime": float(rec["ctrl_dt"]),
                "frames": len(pts),
                "obsDim": int(obs.shape[1]),
                "actionDim": int(act.shape[1]),
                "pyMaxDiff": diff,
            }
        )
    (dist / "data" / "replays.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    return index


STAGES = json.loads((ROOT / "training" / "reward_config.json").read_text(encoding="utf-8"))["curriculum"]


def build(dist: Path) -> str:
    site = json.loads((WEB / "site.json").read_text(encoding="utf-8"))
    version, commit = version_stamp()
    if dist.exists():
        shutil.rmtree(dist)
    (dist / "screenshots").mkdir(parents=True)
    shots = []
    for s in site["screenshots"]:
        src = ROOT / s["src"]
        if not src.is_file():
            raise SystemExit(f"site.json: screenshot {s['src']} does not exist")
        dst = dist / "screenshots" / src.name
        shutil.copyfile(src, dst)
        w, h = png_size(src)
        shots.append({"url": f"screenshots/{src.name}", "caption": s["caption"], "width": w, "height": h})
    for name in STATIC:
        shutil.copyfile(WEB / name, dist / name)
    replays = build_replays(site, dist)
    # X-Commit on every response: the workflow (and anyone) can confirm which commit is live.
    swa = json.loads((WEB / "staticwebapp.config.json").read_text(encoding="utf-8"))
    swa.setdefault("globalHeaders", {})["x-commit"] = commit or "unknown"
    (dist / "staticwebapp.config.json").write_text(json.dumps(swa, indent=1) + "\n", encoding="utf-8")
    for name in site.get("extra_files", []):
        shutil.copyfile(ROOT / name, dist / Path(name).name)
    subs = {
        "%%TITLE%%": html.escape(site["title"]),
        "%%TAGLINE%%": html.escape(site["tagline"]),
        "%%REPO%%": html.escape(site["repo"]),
        "%%VERSION%%": version,
        "%%COMMIT%%": commit,
        "%%CONTENT%%": render_content(site, shots),
    }
    for page in ("index.html", "diag.html", "viewer.html"):
        text = (WEB / page).read_text(encoding="utf-8")
        for k, v in subs.items():
            text = text.replace(k, v)
        if "%%" in text:
            raise SystemExit(f"{page}: unreplaced placeholder")
        (dist / page).write_text(text, encoding="utf-8", newline="\n")
    (dist / "version.json").write_text(json.dumps({"version": version, "commit": commit}) + "\n", encoding="utf-8")
    spec = json.loads((WEB / "diag_checks.json").read_text(encoding="utf-8"))
    policy_urls = sorted({r["policy"] for r in replays} | {f"data/{r['name']}.json" for r in replays})
    checks = expand_checks(spec, dist, [s["url"] for s in shots], policy_urls + ["data/replays.json"])
    (dist / "diag_checks.json").write_text(json.dumps(checks, indent=1) + "\n", encoding="utf-8")
    return version


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="build into a temp dir and validate; write nothing")
    a = ap.parse_args()
    if a.check:
        with tempfile.TemporaryDirectory() as tmp:
            v = build(Path(tmp) / "dist")
        print(f"web build OK ({v})")
    else:
        v = build(WEB / "dist")
        print(f"built web/dist ({v})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
