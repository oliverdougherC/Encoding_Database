#!/usr/bin/env python3
"""Build the EncodingDB playable human-review packet (2026-09-20).

Binds each reference clip and encoded artifact to live candidate-API analysis
status JSON, DB hashes, and public corpus entry ids. Emits manifest.json and
index.html into the packet directory. No re-encoding: original bytes only.
"""
import hashlib, json, os, sys

PACKET = "/Users/ofhd/encodingdb-review-packet-20260920"
MEDIA = os.path.join(PACKET, "media")

CLIPS = {  # clipKey -> (filename, db sha256, byteSize)
    "animation-1080p24-final": ("canonical/animation-1080p24-final.mkv",
        "d70c4d9e85e88c4369b6391a21f0388a4a3a7b72e1b89f545e5897b4d5d820ea", 173819800),
    "athletic-action-1080p24-final": ("canonical/athletic-action-1080p24-final.mkv",
        "1e06fe0315d0cb90247a3dae2258327989e657496247ca8974ddd8c2431755de", 139815565),
    "screen-text-1080p24-final": ("canonical/screen-text-1080p24-final.mkv",
        "3c024a4aceb4ad09f8fa8cf51b6a4aba9be68460acb3f6a24a223e287bc05c8c", 35313873),
    "natural-detail-1080p24-final": ("canonical/natural-detail-1080p24-final.mkv",
        "cfcc51d48372138f6f66b3286fec5a533a808650098e40f119011060d8e51225", 283872120),
    "film-grain-1080p24-final": ("canonical/film-grain-1080p24-final.mkv",
        "67d3d2f5a4f8c617f223077e7071aaee625f014950126e0e93a16b27e578d603", 336898554),
}

# runId, clipKey, encodedFileSha, label, host, kind
PAIRS = [
    ("cmu9ho8lr004qo3dw0w7rpury", "athletic-action-1080p24-final",
     "cfe056efd0ddb0cf683de078d52047578af29585519e1d4168a91489f58f89f0",
     "libx264 fast CRF23", "macOS (Apple M4 Pro)", "quality"),
    ("cmu9ktk1s0021l9dw5ud9myo2", "athletic-action-1080p24-final",
     "96bed2cbd77fc887c05a04368ca59f71786be33f340528cd2550eb101f2c68e4",
     "h264_nvenc p4 CQ24", "Windows (Ryzen 9 7950X + RTX 5090)", "quality"),
    ("cmu9hobi7004to3dwfy5jnirz", "screen-text-1080p24-final",
     "3744643e59f905561832f0abb3fcd15434502715293f146574aeeefe0e9ee34c",
     "libx264 fast CRF23", "macOS (Apple M4 Pro)", "quality"),
    ("cmu9ktpka002bl9dwao8e0znm", "screen-text-1080p24-final",
     "dd8af3632ab66a6b47b635493d0ea9aa92febb5d47dfab12e4711875533eebe0",
     "h264_nvenc p4 CQ24", "Windows (Ryzen 9 7950X + RTX 5090)", "quality"),
    ("cmu9i1dlf005fo3dwnqr2gp9n", "natural-detail-1080p24-final",
     "3f251af18a394c9bb7942ce6b19644f10b89b8740a070710606fa89ab1bad0d6",
     "h264_videotoolbox VBR 6000kbps", "macOS (Apple M4 Pro)", "quality"),
    ("cmu9fyjxy000ao3dwk9wuaiub", "film-grain-1080p24-final",
     "e12ddf07e71b27f5546407681be6a038eb14e994706eafe67a46b22a2f766f8e",
     "h264_nvenc p4 VBR 4000kbps", "Linux (Xeon E5-2699 v4 + GTX 1070)", "quality"),
    ("cmua43aoj0029qcdw5norac9s", "animation-1080p24-final",
     "f803df85554b63eb9b222f6800daea9790870e23ff795cedd2c44e1c3208c448",
     "libx264 fast CRF23", "macOS (Apple M4 Pro)", "environment-suspect"),
]

corpus = json.load(open(os.path.join(PACKET, "api", "corpus-full.json")))

def corpus_entry_for(clip_key, recipe_encoder, preset):
    for e in corpus:
        p = e["id"].split("::")
        if p[1] == clip_key and e["encoderName"] == recipe_encoder and e.get("preset") == preset:
            return e
    return None

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

entries = []
for run_id, clip_key, enc_sha, label, host, kind in PAIRS:
    status = json.load(open(os.path.join(PACKET, "api", f"{run_id}.analysis-status.json")))
    analyses = status["analyses"]
    complete = [a for a in analyses if a["status"] == "COMPLETE"]
    a = complete[0] if complete else analyses[0]
    ref_rel, ref_sha, ref_bytes = CLIPS[clip_key]
    enc_path = os.path.join(MEDIA, enc_sha)
    enc_bytes = os.path.getsize(enc_path)
    enc_actual = sha256_file(enc_path)
    if enc_actual != enc_sha:
        sys.exit(f"HASH MISMATCH {run_id}: {enc_actual}")
    ref_actual = sha256_file(os.path.join(MEDIA, ref_rel))
    if ref_actual != ref_sha:
        sys.exit(f"REF HASH MISMATCH {clip_key}: {ref_actual}")
    encname = label.split()[0]
    preset = "fast" if "libx264" in label else ("p4" if "nvenc" in label else "default")
    ce = corpus_entry_for(clip_key, encname, preset)
    entries.append({
        "benchmarkRunId": run_id,
        "contentClass": clip_key,
        "label": label,
        "encodeHost": host,
        "class": kind,
        "reference": {"path": "media/" + ref_rel, "sha256": ref_sha, "bytes": ref_bytes,
                      "container": "matroska"},
        "encoded": {"path": "media/" + enc_sha, "sha256": enc_sha, "bytes": enc_bytes,
                    "container": "mp4",
                    "artifactId": status["artifactId"],
                    "artifactStorageState": status["artifactStorageState"],
                    "benchmarkRunStatus": status["benchmarkRunStatus"],
                    "benchmarkRunStatusReason": status.get("benchmarkRunStatusReason")},
        "analysis": {"id": a["id"], "status": a["status"],
                     "metricModelId": a["metricModelId"],
                     "analysisWorkerVersion": a["analysisWorkerVersion"],
                     "vmafMean": a.get("vmafMean"), "xpsnr": a.get("xpsnr"),
                     "ssim": a.get("ssim"), "psnr": a.get("psnr")},
        "publicCorpusEntry": ({"id": ce["id"], "scoring": ce["status"]["scoring"],
                               "evidenceTier": ce["status"]["evidenceTier"],
                               "plTotal": ce["pl"]["total"],
                               "eligibleForDefaultRecommendation":
                                   ce["status"]["eligibleForDefaultRecommendation"]}
                              if ce else None),
    })

manifest = {
    "title": "EncodingDB playable human-review packet",
    "generatedAt": "2026-09-20T13:30:00Z",
    "candidateCommit": "b3ef24abb020bc6af5b5fe6b849ba3eae8314be2",
    "rebuildCommit": "a350d45",
    "metricModel": "vmaf-v1-sdr-1080p",
    "suiteFingerprint": "d40bbf563dead0e78003af90b2626003bd80afcc12220ab86bc6d44b8c83b6e",
    "plStatus": "inactive / provisional - every public corpus entry reports "
                "scoring=UNSCORED_NO_PUBLIC_DERIVED_RESULT, evidenceTier=PROVISIONAL, "
                "pl.total=null, eligibleForDefaultRecommendation=false",
    "playability": "Served over loopback HTTP with Range support (206 Partial Content); "
                   "encodes are browser-native MP4, references are Matroska (Chrome plays "
                   "H.264 in Matroska). Original bytes; no remux or re-encode.",
    "entryPoint": "http://127.0.0.1:8777/index.html",
    "apiSnapshot": "api/corpus-full.json = live GET /corpus?limit=100&skip=0 (X-Total-Count: 56) "
                   "from candidate server on 100.99.6.59 (127.0.0.1:3091); per-run "
                   "api/<runId>.analysis-status.json = live GET "
                   "/v7/benchmark-runs/<id>/artifacts/ENCODED/analysis-status",
    "comparisonNote": "Reference MKV is the frozen canonical suite source at full bitrate; "
                      "the encode MP4 is the exact stored artifact from the candidate artifact "
                      "volume (sha256 == storage key == manifest value).",
    "items": entries,
}
with open(os.path.join(PACKET, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=1)

rows = []
for it in entries:
    susp = it["class"] == "environment-suspect"
    banner = ("<div class='suspect'>SUSPECT — environment-flagged run. Excluded from any "
              "quality judgment; shown to demonstrate that suspect data is separated, not "
              "silently mixed in.</div>") if susp else ""
    ce = it.get("publicCorpusEntry")
    ce_txt = (f"public corpus entry {ce['id']} → {ce['scoring']} / {ce['evidenceTier']} "
              f"/ PL={ce['plTotal']}") if ce else "public corpus entry: (not materialized)"
    rows.append(f"""
<section>
  <h2>{it['contentClass']} — {it['label']} <span class="host">[{it['encodeHost']}]</span></h2>
  {banner}
  <div class="pair">
    <figure><figcaption>Reference (canonical suite, full-bitrate)</figcaption>
      <video src="{it['reference']['path']}" controls preload="metadata"></video></figure>
    <figure><figcaption>Encoded artifact</figcaption>
      <video src="{it['encoded']['path']}" controls preload="metadata"></video></figure>
  </div>
  <details><summary>bindings</summary><pre>run {it['benchmarkRunId']}
artifact {it['encoded']['artifactId']} sha256={it['encoded']['sha256']} ({it['encoded']['artifactStorageState']}, run {it['encoded']['benchmarkRunStatus']})
analysis {it['analysis']['id']} ({it['analysis']['status']}, {it['analysis']['metricModelId']}, {it['analysis']['analysisWorkerVersion']})
  VMAF mean={it['analysis']['vmafMean']} xPSNR={it['analysis']['xpsnr']} SSIM={it['analysis']['ssim']} PSNR={it['analysis']['psnr']}
reference sha256={it['reference']['sha256']}
{ce_txt}</pre></details>
</section>""")

html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>EncodingDB playable review packet — 2026-09-20</title>
<style>
body{{font-family:system-ui;margin:2rem auto;max-width:1500px;padding:0 1rem;background:#111;color:#ddd}}
.pair{{display:flex;gap:1rem;flex-wrap:wrap}} figure{{flex:1;min-width:420px;margin:0}}
video{{width:100%;background:#000}} h2{{font-size:1.05rem}} .host{{color:#8ab4f8;font-weight:normal}}
.suspect{{background:#5c1a1a;padding:.5rem;border-radius:4px}}
pre{{white-space:pre-wrap;font-size:.75rem;color:#aaa}} summary{{cursor:pointer;color:#8ab4f8}}
</style></head><body>
<h1>EncodingDB playable human-review packet</h1>
<p>Candidate <code>b3ef24a</code> (rebuild <code>a350d45</code> for GUI acceptance). PL is
<b>inactive / provisional</b>: all listed public corpus entries report
<code>UNSCORED_NO_PUBLIC_DERIVED_RESULT</code> / <code>PROVISIONAL</code>, <code>pl.total=null</code>.
Play each pair to judge perceived quality; leave verdicts blank until Oliver reviews.
Reference and encode play independently; open both and press play for A/B.</p>
{''.join(rows)}
<p><a href="manifest.json">manifest.json</a></p></body></html>"""
with open(os.path.join(PACKET, "index.html"), "w") as f:
    f.write(html)
print("wrote manifest.json + index.html;", len(entries), "items")
