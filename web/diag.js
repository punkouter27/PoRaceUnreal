// /diag: every check is probed live from the browser (fetch + latency). Nothing is assumed healthy.
// The check list is diag_checks.json, written by web/build.py from web/diag_checks.json.
// Results are kept 60 s per browser tab and build (sessionStorage, key = version + commit) so reloading /diag does not
// re-download every brain; "Re-check" (?fresh) probes again at once.
(function () {
  "use strict";
  const pageVersion = document.querySelector('meta[name="po-version"]').content;
  const pageCommit = (document.querySelector('meta[name="po-commit"]') || {}).content || "";
  const CACHE_S = 60;
  const cacheKey = "poraceunreal-diag:" + pageVersion + ":" + pageCommit;
  const fresh = new URLSearchParams(location.search).has("fresh");
  const groups = { api: "g-api", data: "g-data", service: "g-service" };

  function row(c) {
    const li = document.createElement("li");
    li.className = "check";
    const parts = [
      ["span", "check__label", c.label],
      ["span", "check__ms", ""],
      ["span", "pill", "Checking"],
      ["span", "check__purpose", c.purpose],
      ["span", "check__detail", ""],
    ];
    for (const [tag, cls, text] of parts) {
      const el = document.createElement(tag);
      el.className = cls;
      el.textContent = text;
      li.appendChild(el);
    }
    li.querySelector(".pill").dataset.s = "Checking";
    document.getElementById(groups[c.group]).appendChild(li);
    return li;
  }

  function show(li, status, ms, detail) {
    const pill = li.querySelector(".pill");
    pill.dataset.s = status;
    pill.textContent = status;
    li.querySelector(".check__ms").textContent = ms == null ? "" : Math.round(ms) + " ms";
    li.querySelector(".check__detail").textContent = detail || "";
  }

  async function timedFetch(url) {
    const t0 = performance.now();
    const res = await fetch(url, { cache: "no-store" });
    const body = await res.arrayBuffer();
    return { res, body, ms: performance.now() - t0 };
  }

  // Files of the deployed bundle: served (200), the size the build wrote, and images decode.
  async function probeFiles(c) {
    let status = "Healthy";
    let total = 0;
    const problems = [];
    for (const f of c.files) {
      try {
        const { res, body, ms } = await timedFetch(f.path);
        total += ms;
        if (!res.ok) {
          status = "Unhealthy";
          problems.push(f.path + " -> HTTP " + res.status);
          continue;
        }
        if (f.bytes != null && body.byteLength !== f.bytes) {
          if (status === "Healthy") status = "Degraded";
          problems.push(f.path + ": " + body.byteLength + " bytes, the build wrote " + f.bytes);
        }
        if (f.type === "image") {
          try {
            const bmp = await createImageBitmap(new Blob([body], { type: res.headers.get("content-type") || "image/png" }));
            if (bmp.close) bmp.close();
          } catch (e) {
            status = "Unhealthy";
            problems.push(f.path + ": does not decode as an image");
          }
        }
      } catch (e) {
        status = "Unhealthy";
        problems.push(f.path + ": " + e.message);
      }
    }
    const detail = problems.length ? problems.join("; ") : c.files.length + " file(s) served";
    return { status, ms: total, detail };
  }

  // version.json carries the build's one stamp; this page must carry the same (else a stale cache or mixed deploy).
  async function probeVersion(c) {
    const { res, body, ms } = await timedFetch(c.path);
    if (!res.ok) return { status: "Unhealthy", ms, detail: c.path + " -> HTTP " + res.status };
    const j = JSON.parse(new TextDecoder().decode(body));
    if (j.version !== pageVersion || (pageCommit && j.commit !== pageCommit))
      return { status: "Degraded", ms, detail: "server says " + j.version + " " + j.commit + ", this page is " + pageVersion + " " + pageCommit };
    return { status: "Healthy", ms, detail: j.version + " · X-Commit " + (j.commit || "unknown").slice(0, 7) };
  }

  // onnxruntime-web from the CDN the viewer uses; one brain run on its first recorded observation must reproduce the
  // recorded action (the same check the viewer makes every step).
  async function probeInference(c) {
    const t0 = performance.now();
    const ort = await import(c.url);
    ort.env.wasm.numThreads = 1;
    const tLoad = performance.now() - t0;
    const data = await (await fetch(c.data)).json();
    const s = await ort.InferenceSession.create(c.policy, { executionProviders: ["wasm"] });
    const obs = Float32Array.from(data.obs[0]);
    const t1 = performance.now();
    const out = await s.run({ [s.inputNames[0]]: new ort.Tensor("float32", obs, [1, obs.length]) });
    const runMs = performance.now() - t1;
    const a = out[s.outputNames[0]].data;
    let diff = 0;
    for (let k = 0; k < data.action[0].length; k++) diff = Math.max(diff, Math.abs(a[k] - data.action[0][k]));
    const detail = c.policy.split("/").pop() + ": obs[1," + obs.length + "] -> action[1," + a.length + "] in " +
      runMs.toFixed(2) + " ms (WASM, this device), max |action - recorded| " + diff.toExponential(1) +
      "; runtime loaded in " + Math.round(tLoad) + " ms";
    return { status: diff < 1e-4 ? "Healthy" : "Unhealthy", ms: performance.now() - t0, detail };
  }

  function finish(results, t0, cachedAt) {
    const bad = results.filter((r) => r.status === "Unhealthy");
    const deg = results.filter((r) => r.status === "Degraded");
    const b = document.getElementById("banner");
    if (bad.length) {
      b.dataset.state = "bad";
      b.textContent = "Not working: " + bad.map((r) => r.label).join(", ");
    } else if (deg.length) {
      b.dataset.state = "degraded";
      b.textContent = "Working, with " + deg.length + " thing" + (deg.length > 1 ? "s" : "") + " degraded";
    } else {
      b.dataset.state = "ok";
      b.textContent = "Everything is working";
    }
    const checked = document.getElementById("checked");
    if (cachedAt) {
      checked.textContent = "Checked " + new Date(cachedAt).toISOString().replace("T", " ").slice(0, 19) +
        " UTC from your browser, cached " + Math.round((Date.now() - cachedAt) / 1000) + " s ago (kept " + CACHE_S + " s). ";
    } else {
      checked.textContent = "Checked " + new Date().toISOString().replace("T", " ").slice(0, 19) +
        " UTC from your browser in " + Math.round(performance.now() - t0) + " ms. ";
    }
    const again = document.createElement("a");
    again.href = "/diag?fresh=1";
    again.textContent = "Re-check";
    checked.appendChild(again);
    document.body.dataset.diagDone = cachedAt ? "cached" : "1";
  }

  function fromCache() {
    if (fresh) return false;
    let saved = null;
    try {
      saved = JSON.parse(sessionStorage.getItem(cacheKey) || "null");
    } catch (e) {
      return false;
    }
    if (!saved || Date.now() - saved.at > CACHE_S * 1000) return false;
    for (const r of saved.rows) show(row(r), r.status, r.ms, r.detail);
    finish(saved.results, performance.now(), saved.at);
    return true;
  }

  function save(rows, results) {
    try {
      sessionStorage.setItem(cacheKey, JSON.stringify({ at: Date.now(), rows, results }));
    } catch (e) {
      /* private mode or storage full: no cache, probe every time */
    }
  }

  async function run() {
    if (fromCache()) return;
    const t0 = performance.now();
    const rows = [];
    const listRow = row({ group: "data", label: "Check list", purpose: "diag_checks.json: what this page probes" });
    let list;
    try {
      const { res, body, ms } = await timedFetch("/diag_checks.json");
      if (!res.ok) throw new Error("HTTP " + res.status);
      list = JSON.parse(new TextDecoder().decode(body));
      show(listRow, "Healthy", ms, list.checks.length + " checks");
      rows.push({ group: "data", label: "Check list", purpose: "diag_checks.json: what this page probes", status: "Healthy", ms, detail: list.checks.length + " checks" });
    } catch (e) {
      show(listRow, "Unhealthy", null, "diag_checks.json: " + e.message);
      finish([{ label: "Check list", status: "Unhealthy" }], t0);
      return;
    }
    const results = [{ label: "Check list", status: "Healthy" }];
    await Promise.all(
      list.checks.map(async (c) => {
        const li = row(c);
        if (c.kind === "none") {
          // switched off on purpose: neutral "Off", never counted toward the banner
          show(li, "Off", null, c.detail);
          rows.push({ group: c.group, label: c.label, purpose: c.purpose, status: "Off", ms: null, detail: c.detail });
          return;
        }
        let r;
        try {
          r = c.kind === "version" ? await probeVersion(c) : c.kind === "inference" ? await probeInference(c) : await probeFiles(c);
        } catch (e) {
          r = { status: "Unhealthy", ms: null, detail: e.message };
        }
        show(li, r.status, r.ms, r.detail);
        rows.push({ group: c.group, label: c.label, purpose: c.purpose, status: r.status, ms: r.ms, detail: r.detail });
        results.push({ label: c.label, status: r.status });
      })
    );
    save(rows, results);
    finish(results, t0);
  }

  run();
})();
