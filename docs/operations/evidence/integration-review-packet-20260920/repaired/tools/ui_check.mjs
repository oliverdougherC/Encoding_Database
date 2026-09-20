// Headless-Chrome functional check of the review worksheet UI on index.html.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const BASE = process.env.PACKET_BASE || "http://127.0.0.1:8777";
const TEST = `(async () => {
  const q = s => document.querySelectorAll(s);
  const out = {};
  out.judgeBlocks = q('.judge').length;                       // 7
  out.radios = q('.judge input[type=radio]').length;          // 28
  out.textareas = q('.judge textarea').length;                // 7
  const c7acc = document.querySelector('input[name=dC7][value=accept]');
  const c7rej = document.querySelector('input[name=dC7][value=reject]');
  const c7ed  = document.querySelector('input[name=dC7][value=expect-disagreement]');
  out.c7LockedOut = c7acc.disabled && c7rej.disabled;
  out.c7Allowed = !c7ed.disabled && !document.querySelector('input[name=dC7][value=investigate]').disabled;
  exportJson();
  out.gateOnBlank = /Missing decision\\/rationale/.test(statusEl.textContent) && /C1/.test(statusEl.textContent);
  // fill all 7 and export
  reviewer.value = 'UITEST';
  for (const c of ['C1','C2','C3','C4','C5','C6']) {
    document.querySelector('input[name=d'+c+'][value=accept]').checked = true;
    document.getElementById('r'+c).value = 'UITEST rationale ' + c;
  }
  c7ed.checked = true; document.getElementById('rC7').value = 'UITEST rationale C7';
  for (const el of q('.judge input, .judge textarea')) el.dispatchEvent(new Event('input', { bubbles: true }));
  const pl = JSON.parse(JSON.stringify(payload()));
  out.payloadCases = pl && Object.keys(pl.cases).length;
  out.payloadC7 = pl && pl.cases.C7.decision;
  exportJson();
  out.exportDone = /Downloaded/.test(statusEl.textContent);
  out.localStorageSaved = !!localStorage.getItem('packet-judgments-20260920');
  return out;
})()`;

async function main() {
  const udd = mkdtempSync(join(tmpdir(), "packet-ui-"));
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--no-first-run",
    `--user-data-dir=${udd}`, "--remote-debugging-port=0", "about:blank"], { stdio: "ignore" });
  try {
    let port = null;
    for (let i = 0; i < 100 && !port; i++) {
      await new Promise(r => setTimeout(r, 100));
      try { port = readFileSync(join(udd, "DevToolsActivePort"), "utf8").split("\n")[0]; } catch {}
    }
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    const target = targets.find(t => t.type === "page") || targets[0];
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.addEventListener("open", res, { once: true }); ws.addEventListener("error", rej, { once: true }); });
    let id = 0; const pend = new Map();
    ws.addEventListener("message", m => { const p = JSON.parse(m.data); if (p.id && pend.has(p.id)) { pend.get(p.id)(p); pend.delete(p.id); } });
    const send = (method, params = {}) => new Promise((res, rej) => {
      const mid = ++id; pend.set(mid, p => p.error ? rej(new Error(method + ":" + JSON.stringify(p.error))) : res(p.result));
      ws.send(JSON.stringify({ id: mid, method, params }));
    });
    await send("Page.enable");
    await send("Page.navigate", { url: `${BASE}/index.html` });
    // wait until the packet page (not about:blank) is live
    for (let i = 0; i < 60; i++) {
      const p = await send("Runtime.evaluate", { expression: "typeof exportJson + '|' + document.querySelectorAll('.judge').length", returnByValue: true });
      if (p.result.value === "function|7") break;
      await new Promise(r => setTimeout(r, 150));
    }
    // silence the blob download in headless (URL.createObjectURL works; download is harmless)
    const r = await send("Runtime.evaluate", { expression: TEST, awaitPromise: true, returnByValue: true, timeout: 20000 });
    console.log(JSON.stringify(r.result.value, null, 1));
    const v = r.result.value;
    const ok = v.judgeBlocks === 7 && v.radios === 28 && v.textareas === 7 && v.c7LockedOut && v.c7Allowed &&
      v.gateOnBlank && v.payloadCases === 7 && v.payloadC7 === "expect-disagreement" && v.exportDone && v.localStorageSaved;
    console.log("UI_ALL_PASS=" + ok);
    process.exitCode = ok ? 0 : 1;
  } finally { chrome.kill("SIGKILL"); }
}
main();
