// Policy viewer (/viewer). web/build.py ships, per recorded race, the racer's ONNX brain and a CPU MuJoCo rollout of
// that brain: per 50 Hz control step the policy input (obs), its output (action) and the body positions. This page
// draws the bodies (no physics runs here) and runs the brain in the browser with onnxruntime-web on each recorded
// observation, checking the result against the recorded action. Tab or the "i" button: diagnostics overlay.
// 30 s without input: demo mode (idle.js) cycles the races with an orbiting camera.
import { createIdleClock, DEMO_DWELL_S } from "./idle.js";

const ORT_URL = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.20.1/dist/ort.wasm.min.mjs";
const $ = (id) => document.getElementById(id);
const canvas = $("view");
const ctx = canvas.getContext("2d");
const css = getComputedStyle(document.documentElement);
const tok = (n) => css.getPropertyValue(n).trim();

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

// ---- recorded races ----
const replays = await getJSON("data/replays.json");
for (const rp of replays) $("replay").add(new Option(rp.label, rp.name));
let rep = null;
let rec = null;
let frame = -1;
let clock = 0;
let playing = true;
const cache = new Map();

async function load(name) {
  const next = replays.find((r) => r.name === name) || replays[0];
  $("replay").value = next.name;
  if (!cache.has(next.name)) cache.set(next.name, getJSON(`data/${next.name}.json`));
  const data = await cache.get(next.name);
  rep = next; // switch the race and its recording together (a step never pairs one brain with another's obs)
  rec = data;
  clock = 0;
  frame = -1;
  latency.length = 0;
  lastDiff = null;
}

// ---- the brain, run in the browser on the recorded observation of each control step ----
let ort = null;
let busy = false;
let inferences = 0;
let lastDiff = null;
let policyError = "";
const latency = [];
const sessions = new Map();
const logged = new Set();

function session(url) {
  if (!sessions.has(url)) {
    sessions.set(
      url,
      (async () => {
        if (!ort) {
          ort = await import(ORT_URL);
          ort.env.wasm.numThreads = 1; // no cross-origin isolation (SharedArrayBuffer) needed
        }
        return ort.InferenceSession.create(url, { executionProviders: ["wasm"] });
      })()
    );
  }
  return sessions.get(url);
}

async function infer(r, data, i) {
  if (busy) return;
  busy = true;
  const name = r.policy.split("/").pop();
  try {
    const s = await session(r.policy);
    const obs = Float32Array.from(data.obs[i]);
    const t0 = performance.now();
    const out = await s.run({ [s.inputNames[0]]: new ort.Tensor("float32", obs, [1, obs.length]) });
    const ms = performance.now() - t0;
    const a = out[s.outputNames[0]].data;
    const want = data.action[i];
    let diff = 0;
    for (let k = 0; k < want.length; k++) diff = Math.max(diff, Math.abs(a[k] - want[k]));
    if (r !== rep) return; // the race changed while this step ran
    latency.push(ms);
    if (latency.length > 60) latency.shift();
    lastDiff = diff;
    policyError = "";
    inferences++;
    if (!logged.has(name) || inferences % 500 === 0) {
      logged.add(name);
      console.info(
        `[policy] ${name} (${r.racer}) inference in the browser (onnxruntime-web 1.20.1, WASM, 1 thread): ` +
          `obs[1,${obs.length}] -> action[1,${a.length}] in ${ms.toFixed(2)} ms, ` +
          `max |action - recorded| = ${diff.toExponential(1)} (step ${i}, ${inferences} inferences)`
      );
    }
    $("policy-status").textContent =
      `${r.racer} · brain ${name} running in your browser · ${ms.toFixed(2)} ms · matches the recording (${diff.toExponential(1)})`;
  } catch (e) {
    policyError = String(e.message || e);
    console.warn(`[policy] ${name}: ${policyError}`);
    $("policy-status").textContent = `${r.racer} · brain ${name} could not run here: ${policyError}`;
  } finally {
    busy = false;
  }
}

// ---- drawing: an orthographic view of the stick figure (bodies to parents, leaf bodies to feet / hands / wheels) ----
let yaw = -Math.PI / 2; // looking from the side: the racer runs left to right
const PITCH = 0.3;
function project(x, y, z, fx, fy, scale, cx, cy) {
  const dx = x - fx;
  const dy = y - fy;
  const u = -dx * Math.sin(yaw) + dy * Math.cos(yaw);
  const v = dx * Math.cos(yaw) + dy * Math.sin(yaw);
  return [cx + u * scale, cy - (z * Math.cos(PITCH) + v * Math.sin(PITCH)) * scale];
}

function draw() {
  const w = canvas.width;
  const h = canvas.height;
  ctx.fillStyle = tok("--bg");
  ctx.fillRect(0, 0, w, h);
  if (!rec || frame < 0) return;
  const p = rec.frames[frame];
  const fx = p[0];
  const fy = p[1];
  let top = 0.3;
  for (let k = 2; k < rec.frames[0].length; k += 3) top = Math.max(top, rec.frames[0][k]);
  const view = Math.max(top * 2, 1.2); // metres of world shown top to bottom (a Go2 is 0.4 m tall, Matt 1.8 m)
  const scale = Math.min((h * 0.8) / view, w / (view * 1.5));
  const cx = w / 2;
  const cy = h * 0.72;
  // ground: a 0.5 m grid around the racer, fixed to the world so it slides by as the racer moves
  ctx.strokeStyle = tok("--line");
  ctx.lineWidth = Math.max(1, devicePixelRatio);
  const g0x = Math.floor(fx / 0.5) * 0.5;
  const g0y = Math.floor(fy / 0.5) * 0.5;
  ctx.beginPath();
  for (let k = -8; k <= 8; k++) {
    const a = project(g0x + k * 0.5, g0y - 4, 0, fx, fy, scale, cx, cy);
    const b = project(g0x + k * 0.5, g0y + 4, 0, fx, fy, scale, cx, cy);
    const c = project(g0x - 4, g0y + k * 0.5, 0, fx, fy, scale, cx, cy);
    const d = project(g0x + 4, g0y + k * 0.5, 0, fx, fy, scale, cx, cy);
    ctx.moveTo(a[0], a[1]);
    ctx.lineTo(b[0], b[1]);
    ctx.moveTo(c[0], c[1]);
    ctx.lineTo(d[0], d[1]);
  }
  ctx.stroke();
  const pt = (i) => project(p[i * 3], p[i * 3 + 1], p[i * 3 + 2], fx, fy, scale, cx, cy);
  const [r, g, b] = rep.color.map((c) => Math.round(c * 255));
  ctx.strokeStyle = `rgb(${r},${g},${b})`;
  ctx.lineCap = "round";
  ctx.lineWidth = Math.max(3, scale * 0.035);
  ctx.beginPath();
  for (const [i, j] of rec.segments) {
    const a = pt(i);
    const c = pt(j);
    ctx.moveTo(a[0], a[1]);
    ctx.lineTo(c[0], c[1]);
  }
  ctx.stroke();
  ctx.fillStyle = tok("--text");
  const n = p.length / 3;
  for (let i = 0; i < n; i++) {
    const a = pt(i);
    ctx.beginPath();
    ctx.arc(a[0], a[1], Math.max(2, scale * 0.012), 0, Math.PI * 2);
    ctx.fill();
  }
}

function resize() {
  const r = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(r.width * devicePixelRatio));
  canvas.height = Math.max(1, Math.round(r.height * devicePixelRatio));
}
addEventListener("resize", resize);

// ---- diagnostics overlay ----
let fps = 0;
let fpsFrames = 0;
let fpsT0 = performance.now();
function toggleOverlay() {
  const o = $("overlay");
  o.hidden = !o.hidden;
  $("overlayBtn").setAttribute("aria-expanded", String(!o.hidden));
  updateOverlay();
}
function updateOverlay() {
  if ($("overlay").hidden || !rep) return;
  const avg = latency.length ? latency.reduce((a, b) => a + b, 0) / latency.length : null;
  $("ov-fps").textContent = fps.toFixed(0);
  $("ov-latency").textContent = policyError
    ? `error: ${policyError}`
    : avg == null
      ? "loading the brain…"
      : `${avg.toFixed(2)} ms (mean of ${latency.length})`;
  $("ov-check").textContent = lastDiff == null ? "–" : `${lastDiff.toExponential(1)} (build, CPU: ${rep.pyMaxDiff.toExponential(1)})`;
  const f = rec && frame >= 0 ? rec.frames[frame] : null;
  $("ov-reward").textContent = f ? `proxy: ${(f[0] - rec.frames[0][0]).toFixed(2)} m travelled (no reward recorded)` : "–";
  $("ov-stage").textContent = rep.stage;
  $("ov-mode").textContent = idle.demo ? "Demo (30 s without input)" : "Manual";
}

// ---- controls and demo mode ----
const idle = createIdleClock();
let dwell = 0;
function onInput() {
  if (idle.input() === "stop") {
    document.body.classList.remove("demo");
    yaw = -Math.PI / 2;
  }
}
for (const ev of ["keydown", "pointerdown", "wheel", "touchstart"]) {
  addEventListener(ev, onInput, { capture: true, passive: true });
}
function gamepadPressed() {
  for (const pad of navigator.getGamepads?.() || []) {
    if (pad && (pad.buttons.some((b) => b.pressed) || pad.axes.some((a) => Math.abs(a) > 0.3))) return true;
  }
  return false;
}
addEventListener("keydown", (e) => {
  if (e.code === "Tab" && !e.shiftKey && !e.altKey && !e.ctrlKey) {
    e.preventDefault();
    toggleOverlay();
  } else if (e.code === "Space" && e.target === document.body) {
    e.preventDefault();
    $("play").click();
  }
});
$("overlayBtn").onclick = toggleOverlay;
$("play").onclick = () => {
  playing = !playing;
  $("play").textContent = playing ? "Pause" : "Play";
};
$("replay").onchange = (e) => load(e.target.value);

let last = performance.now();
function tick(now) {
  const rawDt = (now - last) / 1000;
  const dt = Math.min(0.1, Math.max(0, rawDt));
  last = now;
  if (gamepadPressed()) onInput();
  if (idle.frame(rawDt) === "start") {
    document.body.classList.add("demo");
    playing = true;
    $("play").textContent = "Pause";
    dwell = 0;
  }
  if (idle.demo) {
    yaw += dt * 0.3;
    dwell += dt;
    if (dwell >= DEMO_DWELL_S) {
      dwell = 0;
      load(replays[(replays.indexOf(rep) + 1) % replays.length].name);
    }
  }
  if (rec) {
    if (playing) clock += dt;
    const i = Math.floor(clock / rep.frameTime) % rec.frames.length;
    if (i !== frame) {
      frame = i;
      infer(rep, rec, i);
    }
  }
  draw();
  fpsFrames++;
  if (now - fpsT0 >= 500) {
    fps = (fpsFrames * 1000) / (now - fpsT0);
    fpsFrames = 0;
    fpsT0 = now;
    updateOverlay();
  }
  requestAnimationFrame(tick);
}

resize();
await load(new URLSearchParams(location.search).get("race") || replays[0].name);
if (new URLSearchParams(location.search).has("overlay")) toggleOverlay();
requestAnimationFrame(tick);
