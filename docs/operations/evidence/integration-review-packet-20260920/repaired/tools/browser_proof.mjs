// Real-browser playback/seek proof for the review packet, via headless Chrome
// over CDP using only Node built-ins (global fetch/WebSocket). No new deps.
// For each clip: real metadata, wall-clock playback advance, browser-decoded
// frame count (getVideoPlaybackQuality), keyframe-accurate seek, and a
// same-origin canvas pixel sample proving frames actually decoded.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const BASE = process.env.PACKET_BASE || "http://127.0.0.1:8777";

const TARGETS = [
  // [label, url, seekTo]
  ["REF athletic-action LOSSLESS H.264 preview", "/media/previews/athletic-action-1080p24-final-lossless-h264-preview.mp4", 6.0],
  ["ENC athletic-action libx264 CRF23 artifact", "/media/cfe056efd0ddb0cf683de078d52047578af29585519e1d4168a91489f58f89f0.mp4", 6.0],
  ["REF film-grain LOSSLESS H.264 preview", "/media/previews/film-grain-1080p24-final-lossless-h264-preview.mp4", 6.0],
  ["REF natural-detail LOSSLESS H.264 preview", "/media/previews/natural-detail-1080p24-final-lossless-h264-preview.mp4", 6.0],
  ["REF screen-text LOSSLESS H.264 preview", "/media/previews/screen-text-1080p24-final-lossless-h264-preview.mp4", 6.0],
  ["REF animation LOSSLESS H.264 preview", "/media/previews/animation-1080p24-final-lossless-h264-preview.mp4", 5.0],
  ["ENC natural-detail videotoolbox artifact", "/media/3f251af18a394c9bb7942ce6b19644f10b89b8740a070710606fa89ab1bad0d6.mp4", 6.0],
];

// In-page harness: full playback+seek+pixels test per video, resolves JSON.
const HARNESS = `(async (url, seekTo) => {
  const v = document.createElement('video');
  v.muted = true; v.playsInline = true; v.preload = 'auto';
  v.src = url; document.body.appendChild(v);
  const wait = (ev, to = 15000) => new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error('timeout waiting ' + ev)), to);
    v.addEventListener(ev, () => { clearTimeout(t); res(); }, { once: true });
  });
  const out = { url };
  try {
    await wait('loadedmetadata');
    out.metadata = { w: v.videoWidth, h: v.videoHeight, dur: +v.duration.toFixed(3),
                     readyState: v.readyState };
    const q0 = v.getVideoPlaybackQuality();
    const t0 = performance.now();
    v.play();
    const start = v.currentTime;
    await new Promise((res, rej) => {
      const iv = setInterval(() => {
        if (v.currentTime - start > 0.5) { clearInterval(iv); res(); }
      }, 50);
      setTimeout(() => { clearInterval(iv); rej(new Error('playback did not advance')); }, 8000);
    });
    const wallMs = performance.now() - t0;
    v.pause();
    const q1 = v.getVideoPlaybackQuality();
    out.playback = { advancedBySec: +(v.currentTime - start).toFixed(3),
                     wallMs: Math.round(wallMs),
                     decodedFramesDelta: q1.totalVideoFrames - q0.totalVideoFrames,
                     droppedFramesDelta: q1.droppedVideoFrames - q0.droppedVideoFrames };
    v.currentTime = seekTo;                    // keyframe-accurate target
    await wait('seeked');
    await new Promise(r => setTimeout(r, 150)); // let the frame present
    out.seek = { target: seekTo, landed: +v.currentTime.toFixed(3),
                 delta: +(v.currentTime - seekTo).toFixed(3),
                 readyState: v.readyState, decodedTotal: v.getVideoPlaybackQuality().totalVideoFrames };
    const c = document.createElement('canvas');
    c.width = 320; c.height = 180;
    c.getContext('2d').drawImage(v, 0, 0, 320, 180);
    const d = c.getContext('2d').getImageData(0, 0, 320, 180).data; // throws if tainted
    let s = 0, s2 = 0, n = 0;
    for (let i = 0; i < d.length; i += 4) { const p = d[i] + d[i+1] + d[i+2]; s += p; s2 += p*p; n++; }
    const mean = s / n;
    out.pixels = { samples: n, meanLumaSum: +mean.toFixed(1), stdev: +Math.sqrt(s2/n - mean*mean).toFixed(1) };
    out.error = v.error ? v.error.code + ':' + v.error.message : null;
  } catch (e) { out.fatal = String(e); out.error = v.error ? v.error.code : null; }
  return out;
})`;

function cdp(ws) {
  let id = 0; const pending = new Map();
  ws.addEventListener("message", (m) => {
    const p = JSON.parse(m.data);
    if (p.id && pending.has(p.id)) { pending.get(p.id)(p); pending.delete(p.id); }
  });
  return (method, params = {}) => new Promise((res, rej) => {
    const mid = ++id;
    pending.set(mid, (p) => (p.error ? rej(new Error(method + ": " + JSON.stringify(p.error))) : res(p.result)));
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const udd = mkdtempSync(join(tmpdir(), "packet-chrome-"));
  const chrome = spawn(CHROME, [
    "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
    "--autoplay-policy=no-user-gesture-required",
    `--user-data-dir=${udd}`, "--remote-debugging-port=0", "about:blank",
  ], { stdio: "ignore" });
  try {
    let port = null;
    for (let i = 0; i < 100 && !port; i++) {
      await sleep(100);
      try { port = readFileSync(join(udd, "DevToolsActivePort"), "utf8").split("\n")[0]; } catch {}
    }
    if (!port) throw new Error("chrome devtools port never appeared");
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    const page = targets.find((t) => t.type === "page");
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.addEventListener("open", res, { once: true }); ws.addEventListener("error", rej, { once: true }); });
    const send = cdp(ws);
    await send("Runtime.enable");
    await send("Page.enable");
    await send("Page.navigate", { url: `${BASE}/index.html` }); // packet origin, same-origin canvas
    await sleep(800);
    const results = [];
    for (const [label, path, seekTo] of TARGETS) {
      const r = await send("Runtime.evaluate", {
        expression: `${HARNESS}(${JSON.stringify(BASE + path)}, ${seekTo})`,
        awaitPromise: true, returnByValue: true, timeout: 40000,
      });
      const out = r.result.value || { fatal: JSON.stringify(r) };
      results.push({ label, ...out });
      console.log(label.padEnd(45), JSON.stringify(out));
    }
    const pass = (t) => t.metadata?.w === 1920 && t.metadata?.h === 1080 &&
      t.playback?.advancedBySec > 0.4 && t.playback?.decodedFramesDelta > 5 &&
      t.seek && Math.abs(t.seek.delta) <= 0.15 && t.pixels?.stdev > 1 && !t.error && !t.fatal;
    const allPass = results.every(pass);
    const report = { generatedAt: new Date().toISOString(), browser: "headless Chrome (--headless=new --disable-gpu software decode)",
      entryOrigin: `${BASE}/index.html`, targets: results.map((t) => ({ ...t, PASS: pass(t) })), allPass };
    writeFileSync(new URL("./evidence/browser-proof.json", import.meta.url), JSON.stringify(report, null, 1));
    console.log("ALL_PASS=" + allPass);
    process.exitCode = allPass ? 0 : 1;
  } finally {
    chrome.kill("SIGKILL");
  }
}
main();
