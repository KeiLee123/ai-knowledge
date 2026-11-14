#!/usr/bin/env python3
"""KB03 Issue #97: source-pinned client reading modes, offline-only contracts.

Node (when present) evaluates the PURE UI helpers against synthetic evidence.
Neither Python nor JS calls a model, DB, network, Production or feedback store.
Do not mistake helper checks for a real browser/quote-preview UAT.
"""
import os
import shutil
import subprocess
from pathlib import Path

HTML = Path(__file__).with_name("beta_private_ui_staging_v1.html")
APP149_SHA = "a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8"
BEGIN = "// BEGIN ISSUE97 PURE READING HELPERS."
END = "// END ISSUE97 PURE READING HELPERS."


def helpers(html):
    assert html.count(BEGIN) == 1
    assert html.count(END) == 1
    return html[html.index(BEGIN):html.index(END) + len(END)]


def test_static_ui_security_and_original_rank_contract():
    html = HTML.read_text(encoding="utf-8")
    assert APP149_SHA in html
    assert '"119": 1' in html and '"120": 1' in html
    assert '"121": 2' in html and '"122": 2' in html
    assert '"123": 3' in html and '"124": 4' in html
    assert '"125": 5' in html and '"126": 5' in html
    assert 'matches[0].sha256 !== APP149_READING_SHA256' in html
    assert 'coverage.complete_index_coverage !== true' in html
    assert 'Object.keys(seen).length === 8' in html
    assert 'readingSelect.value = "original"' in html
    assert '"原始檢索排名（預設）"' in html
    assert '"APP149 正文優先' in html and '"APP149 通知表格優先' in html
    assert 'if (readingAllowed)' in html
    assert 'rankCardsForReading(evidenceCards, readingSelect.value)' in html
    assert 'evidenceHost.appendChild(record.card);' in html
    assert 'evidenceCards.push({ item: item, originalIndex: originalIndex, card: card });' in html
    assert '原始排名 " + (originalIndex + 1)' in html
    # Exact browser-supplied global S-ID still goes to guarded server-side
    # request->source-local-evidence ID / PDF verification, never reindexed.
    assert 'evidence_id: item.id' in html
    assert 'source: data.source.source_id' in html
    assert 'lastRequest.request_id !== rid' in html
    assert 'quoteField.value = "";' in html
    assert 'checkButton.disabled = length < 16 || length > 1500;' in html
    assert '"CURRENTNESS_UNVERIFIED_ABSTAIN"' in html
    assert 'results.appendChild(status);' in html
    assert '"尚未評估' not in helpers(html)  # no fabricated semantic evaluation
    assert 'var evidenceCards = [];' in html
    for dangerous in ("innerHTML", "localStorage", "sessionStorage",
                      "eval(", "new Function(", "https://"):
        assert dangerous not in html, dangerous
    assert '<script nonce="__NONCE__">' in html
    assert 'fetch("/api/reading-mode"' not in html


def test_synthetic_js_reading_modes():
    node = shutil.which("node")
    if not node:
        if os.environ.get("KB03_REQUIRE_NODE") == "1":
            raise AssertionError("Node required in GitHub CI for real JS helper checks")
        print("Node unavailable: synthetic JS evaluation SKIPPED (static checks still apply)")
        return
    js = helpers(HTML.read_text(encoding="utf-8"))
    # Standalone synthetic JS: no DOM / browser / credentials / filesystem.
    trial = r'''"use strict";
const assert = require("node:assert/strict");
const sha = "a5b4d5a1af5f4a32b43973db33d95436f9390e8e2da77747ee666015077bb1a8";
const chunkPages = {
  119:1,120:1,121:2,122:2,123:3,124:4,125:5,126:5
};
const chunks = [123,119,125,126,120,121,112,115,124,122,111,113,114,116,117,118];
const evidence = chunks.map((chunk, i) => ({
  id:"S"+(i+1),
  source_id:chunk>=119?"BD_PNAP_APP149":"BD_PNAP_APP145",
  chunk_id:chunk,
  page:chunkPages[chunk]||1
}));
const app149 = {
  source_id:"BD_PNAP_APP149",
  sha256:sha,
  coverage:{indexed_chunks:8,retrieved_unique_chunks:8,complete_index_coverage:true}
};
const data = {
  sources:[{source_id:"BD_PNAP_APP145"},app149],
  coverage:{complete_index_coverage:true},
  evidence
};
assert.equal(app149ReadingAllowed(data),true);
const records = evidence.map((item,originalIndex) => ({item,originalIndex,card:{id:item.id}}));
const snapshot = JSON.stringify(data);
const identity = rankCardsForReading(records,"original");
const originalIDs = identity.map(r=>r.item.id);
assert.deepEqual(originalIDs,records.map(r=>r.item.id));
const body = rankCardsForReading(records,"body");
assert.deepEqual(body.slice(0,5).map(r=>r.item.chunk_id),[123,119,120,121,122]);
const forms = rankCardsForReading(records,"forms");
assert.deepEqual(forms.slice(0,3).map(r=>r.item.chunk_id),[125,126,124]);
assert.equal(forms[0].item.id,"S3");
assert.equal(forms[2].item.id,"S9");
assert.equal(body[3].item.id,"S6");
assert.equal(rankCardsForReading(records,"unexpected")[0].item.id,"S1");
assert.equal(new Set(body.map(r=>r.item.id)).size,16);
assert.equal(new Set(forms.map(r=>r.item.id)).size,16);
assert.equal(JSON.stringify(data),snapshot);
const clone = () => JSON.parse(JSON.stringify(data));
let tampered = clone(); tampered.sources[1].sha256 = "0".repeat(64);
assert.equal(app149ReadingAllowed(tampered),false);
tampered = clone(); tampered.coverage.complete_index_coverage = false;
assert.equal(app149ReadingAllowed(tampered),false);
tampered = clone(); tampered.evidence[5].page = 3;
assert.equal(app149ReadingAllowed(tampered),false);
tampered = clone(); tampered.evidence[5].chunk_id = 123;
assert.equal(app149ReadingAllowed(tampered),false);
tampered = clone(); tampered.evidence[0].id = "S99";
assert.equal(app149ReadingAllowed(tampered),false);
tampered = clone(); tampered.evidence = tampered.evidence.filter(r=>r.chunk_id!==121);
assert.equal(app149ReadingAllowed(tampered),false);
tampered = clone(); tampered.sources = tampered.sources.filter(r=>r.source_id!=="BD_PNAP_APP149");
assert.equal(app149ReadingAllowed(tampered),false);
tampered = clone(); tampered.sources[1].coverage.retrieved_unique_chunks = 7;
assert.equal(app149ReadingAllowed(tampered),false);
tampered = clone(); tampered.sources.push(app149);
assert.equal(app149ReadingAllowed(tampered),false);
console.log("READING MODES SYNTHETIC JS PASS");
'''
    run = subprocess.run([node, "-e", js + "\n" + trial],
                         capture_output=True, text=True, timeout=15, check=False)
    assert run.returncode == 0, run.stderr[-2500:]
    assert "READING MODES SYNTHETIC JS PASS" in run.stdout


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name + ": PASS")
    print("KB03 ISSUE97 READING MODES OFFLINE CONTRACT: PASS")


if __name__ == "__main__":
    main()
