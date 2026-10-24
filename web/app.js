const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { page: location.hash.slice(1) || "overview", overview: null, runs: [], selectedRun: "", selectedEvidenceScan: "", events: [] };
const labels = { overview: "Overview", dataset: "Dataset", integrity: "Integrity", evidence: "Real evidence", carve: "Carving lab", results: "Results", log: "Activity log" };

function esc(value = "") {
  return String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}
function pretty(value) { return Number(value || 0).toLocaleString("en-US"); }
function percent(value, digits = 0) { return `${(Number(value || 0) * 100).toFixed(digits)}%`; }
function fileType(filename = "") {
  const ext = String(filename).split(".").pop().toUpperCase();
  return ({ JPG: "JPEG image", JPEG: "JPEG image", PDF: "PDF document", ZIP: "ZIP archive", BIN: "Binary sample" })[ext] || "Sample file";
}
function friendlyEvent(event = "") {
  return ({ "dataset.initialize": "Sample files initialized", "experiment_completed": "Experiment completed", "integrity_check": "Integrity check completed" })[event] || String(event).replace(/[._]/g, " ").replace(/\b\w/g, char => char.toUpperCase());
}
function date(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
function tag(status) {
  const key = String(status || "unknown").toUpperCase();
  const kind = ["MATCH", "EXACT", "EXACT_MATCH", "COMPLETE"].includes(key) ? "good" : ["MISMATCH", "CORRUPTED", "MISSING", "FAILED", "EMPTY"].includes(key) ? "bad" : ["UNREGISTERED", "PARTIAL", "RUNNING", "TRUNCATED", "OUTPUT_LIMIT"].includes(key) ? "warn" : key === "DELIMITED" ? "info" : "neutral";
  const display = ({ MATCH: "Exact match", EXACT: "Exact match", EXACT_MATCH: "Exact match", MISMATCH: "Corrupted", CORRUPTED: "Corrupted", MISSING: "Missing", UNREGISTERED: "Unlisted", UNKNOWN: "Unverified", COMPLETE: "Complete", FAILED: "Failed", PARTIAL: "Partial", RUNNING: "Running", DETECTED: "Found", "NOT FOUND": "Not found", CARVED: "Recovered", DELIMITED: "End marker found", TRUNCATED: "Extent estimated", EMPTY: "Empty candidate", OUTPUT_LIMIT: "Not saved (output limit)", RECORDED: "Recorded", READY: "Ready", PENDING: "Not checked" })[key] || key;
  return `<span class="tag ${kind}" aria-label="${esc(display)}">${esc(display)}</span>`;
}
function kpi(label, value, note, accent = false) {
  return `<article class="kpi"><div class="kpi-label">${esc(label)}</div><div class="kpi-value ${accent ? "kpi-accent" : ""}">${esc(value)}</div><div class="kpi-note">${esc(note)}</div></article>`;
}
function panel(title, subtitle, body, action = "") {
  return `<section class="panel"><div class="panel-head"><div><div class="panel-title">${title}</div>${subtitle ? `<div class="panel-subtitle">${subtitle}</div>` : ""}</div>${action}</div><div class="panel-body">${body}</div></section>`;
}
function title(eyebrow, name, description, actions = "") {
  return `<div class="eyebrow">${eyebrow}</div><div class="page-title-row"><div><h1 class="page-title">${name}</h1><p class="page-description">${description}</p></div>${actions ? `<div class="title-actions">${actions}</div>` : ""}</div>`;
}
function sectionTitle(name, note = "") { return `<div class="section-heading"><h2>${name}</h2><span>${note}</span></div>`; }
function table(headers, rows, empty = "No records to display.") {
  if (!rows.length) return `<div class="empty"><div class="empty-icon">⌁</div><strong>Nothing here yet</strong><p>${empty}</p></div>`;
  return `<div class="table-wrap"><table><thead><tr>${headers.map(item => `<th>${item}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) } });
  let value;
  try { value = await response.json(); } catch { value = {}; }
  if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}
function toast(message, error = false) {
  const node = document.createElement("div");
  node.className = `toast${error ? " error" : ""}`;
  node.textContent = message;
  $("#toast-region").append(node);
  setTimeout(() => node.remove(), 4200);
}
function loading() { $("#content").innerHTML = `<div class="loading"><span class="spinner"></span>Loading your workspace…</div>`; }
function setPage(page) {
  state.page = labels[page] ? page : "overview";
  if (location.hash !== `#${state.page}`) history.replaceState(null, "", `#${state.page}`);
  $$(".nav-link").forEach(item => item.classList.toggle("active", item.dataset.page === state.page));
  $("#crumb-current").textContent = state.page.toUpperCase();
  render();
}
async function render() {
  loading();
  try {
    if (state.page === "overview") await renderOverview();
    if (state.page === "dataset") await renderDataset();
    if (state.page === "integrity") await renderIntegrity();
    if (state.page === "evidence") await renderEvidence();
    if (state.page === "carve") await renderCarve();
    if (state.page === "results") await renderResults();
    if (state.page === "log") await renderLog();
    updateSidebar();
    bindActions();
  } catch (error) {
    $("#content").innerHTML = `${title("WORKSPACE", "This page did not load", "There was a problem getting the latest information. Try again in a moment.")}${panel("Connection problem", "Your files have not been changed", `<div class="inline-alert error">${esc(error.message)}</div><button class="button" data-action="refresh">Try again</button>`)}`;
    bindActions();
  }
}
async function renderOverview() {
  const [data, realEvidence] = await Promise.all([api("/api/overview"), api("/api/evidence").catch(() => ({ sources: [] }))]); state.overview = data; state.runs = data.runs;
  const integrity = data.integrity || {};
  const issues = Number(integrity.MISMATCH || 0) + Number(integrity.MISSING || 0) + Number(integrity.UNREGISTERED || 0);
  const runs = [...(data.runs || [])].reverse();
  const latest = runs[0];
  const pipeline = `<ol class="quick-steps">${[
    ["Check the sample files", "Make sure every file still matches its saved fingerprint."],
    ["Run the recovery test", "Try recovery with files together, split apart, and partly overwritten."],
    ["Review the results", "See what was found and which files were recovered exactly."],
  ].map(([heading, copy]) => `<li><strong>${heading}</strong><span>${copy}</span></li>`).join("")}</ol>`;
  const conditions = `<div class="condition-list">${[
    ["1", "Stored together", "The whole file is kept in one piece"],
    ["2", "Split apart", "File pieces are saved in different places"],
    ["3", "Partly overwritten", "Some of the original bytes are replaced"],
  ].map(item => `<div class="condition-item"><div class="condition-icon">${item[0]}</div><div><div class="condition-name">${item[1]}</div><div class="condition-note">${item[2]}</div></div></div>`).join("")}</div>`;
  const latestEvents = (data.latest_events || []).slice(0, 4).map(event => `<div class="activity-row"><span class="activity-dot"></span><div><strong>${esc(friendlyEvent(event.event))}</strong><small>${date(event.timestamp_utc)}</small></div></div>`).join("");
  $("#content").innerHTML = `${title("YOUR WORKSPACE", "Evidence overview", "Check the sample files, run a recovery test, and review what the tool could recover.", `<button class="button primary" data-action="run">Run a recovery test</button>`)}
    <div class="kpi-grid overview-kpis">${kpi("Sample files", pretty(data.fixture_count), "Synthetic reference set")}${kpi("Imported sources", pretty(realEvidence.sources?.length), "Real files copied locally", true)}${kpi("Files verified", `${pretty(integrity.MATCH)} of ${pretty(data.fixture_count)}`, "Match their saved fingerprints")}${kpi("Files to review", pretty(issues), "Changed, missing, or unlisted")}${kpi("Saved test runs", pretty(data.runs?.length), "Synthetic results to reopen")}</div>
    <div class="dashboard-grid"><div>${panel("Getting started", "Three simple steps", pipeline)}${sectionTitle("What the recovery test checks")}${panel("Three file conditions", "The same sample files are tested in different states", conditions)}</div><div>${panel("Latest test run", latest ? `${date(latest.created_utc)}` : "No test run yet", latest ? `<div class="run-row"><div><div class="run-id">${esc(latest.run_id)}</div><div class="run-meta">You can open these saved results any time.</div></div>${tag(latest.status)}</div><button class="button subtle" style="margin-top:16px" data-page="results">View latest results</button>` : `<div class="empty"><div class="empty-icon">＋</div><strong>Ready when you are</strong><p>Run the test to see how recovery changes across the three file conditions.</p><button class="button primary" data-action="run" style="margin-top:16px">Run a recovery test</button></div>`)}<details class="activity-disclosure"><summary>Recent activity <span>${pretty(data.event_count)} total</span></summary><div class="activity-list">${latestEvents || `<p class="muted">No activity yet.</p>`}</div></details></div></div>`;
}
async function renderDataset() {
  const [data, integrity] = await Promise.all([api("/api/dataset"), api("/api/integrity")]);
  const m = data.manifest; const entries = m.entries || [];
  const current = new Map((integrity.results || []).map(item => [item.filename, item]));
  const good = Number(data.integrity?.MATCH || 0);
  const rows = entries.map(item => {
    const result = current.get(item.filename) || {};
    return `<tr><td><span class="file-name">${esc(item.filename)}</span><div class="muted">${esc(item.description || "")}</div></td><td>${esc(fileType(item.filename))}</td><td>${pretty(item.size_bytes)} bytes</td><td>${tag(result.status || "UNKNOWN")}</td><td><div class="row-actions"><button class="button subtle" data-preview="${esc(item.filename)}">View bytes</button><details class="technical-details"><summary>File details</summary><div class="detail-content"><span>Saved fingerprint</span><code>${esc(item.sha256)}</code><span>Signature</span><code>${item.signature_hex ? esc(item.signature_hex.toUpperCase()) : "No file signature"}</code><span>Signature starts at</span><code>${item.signature_offset ?? "Not applicable"}</code></div></details></div></td></tr>`;
  });
  const catalogue = (data.catalogue || []).map(item => `<tr><td><span class="file-name">${esc(item.filename)}</span></td><td>${esc(item.description)}</td><td class="mono">${item.signature_hex ? esc(item.signature_hex) : "No signature"}</td></tr>`);
  const issues = entries.length - good;
  $("#content").innerHTML = `${title("EVIDENCE FILES", "Your sample files", "These generated sample files are the known originals used in every recovery test.", `<button class="button primary" data-action="initialize">Create missing sample files</button>`)}
    <div class="kpi-grid">${kpi("Files in this set", pretty(entries.length), "Synthetic samples")}${kpi("Verified", `${pretty(good)} of ${pretty(entries.length)}`, "Still match the saved fingerprint", true)}${kpi("Need attention", pretty(issues), "Changed, missing, or not verified")}</div>
    ${panel("Sample file list", "Choose “View bytes” to inspect the beginning of a file.", table(["Sample file", "File type", "Size", "Current status", "Actions"], rows, "Select “Create missing sample files” to prepare the sample set."), `<button class="button subtle" data-action="manifest">Download file list</button>`)}
    <details class="section-disclosure"><summary>Technical signature reference <span>For users who need the byte patterns</span></summary><div class="disclosure-body">${table(["Sample file", "Description", "Signature bytes"], catalogue)}</div></details>`;
}
async function renderIntegrity() {
  const data = await api("/api/integrity"); const counts = data.summary || {};
  const problems = (data.results || []).filter(row => row.status !== "MATCH");
  const rows = (data.results || []).map(item => `<tr><td><span class="file-name">${esc(item.filename)}</span><div class="muted">${esc(item.description || "")}</div></td><td>${tag(item.status)}</td><td>${item.actual_size == null ? "File not found" : `${pretty(item.actual_size)} bytes`}</td><td><details class="technical-details"><summary>Fingerprint details</summary><div class="detail-content"><span>Saved fingerprint</span><code>${esc(item.expected_sha256 || "Not available")}</code><span>Current fingerprint</span><code>${esc(item.actual_sha256 || "Not available")}</code></div></details></td></tr>`);
  const banner = problems.length
    ? `<div class="inline-alert ${problems.some(row => row.status === "MISMATCH" || row.status === "MISSING") ? "error" : "warning"}"><strong>${problems.length} file${problems.length === 1 ? " needs" : "s need"} attention.</strong> The saved fingerprints have not been changed.</div>`
    : `<div class="inline-alert"><strong>All sample files look good.</strong> Every file matches its saved fingerprint and is ready for a recovery test.</div>`;
  $("#content").innerHTML = `${title("FILE CHECK", "Are the sample files unchanged?", "We compare each file with the fingerprint saved when the sample set was created. This check does not modify your files.", `<button class="button" data-action="integrity-self-test">Run safe self-test</button>`)}
    <div class="kpi-grid">${kpi("Verified", pretty(counts.MATCH), "Files match their saved fingerprint", true)}${kpi("Changed", pretty(counts.MISMATCH), "File content differs")}${kpi("Missing", pretty(counts.MISSING), "Expected file is not present")}${kpi("Unlisted", pretty(counts.UNREGISTERED), "File is outside the saved list")}</div>
    ${panel("Integrity check", problems.length ? "Review the files marked below" : "Your evidence set is ready", `${banner}${table(["Sample file", "Status", "Current size", "More information"], rows, "Create the sample files first, then check them here.")}`)}
    <details class="section-disclosure"><summary>How this check works <span>Simple explanation</span></summary><div class="disclosure-body"><p>Each original file has a saved SHA-256 fingerprint, a unique summary of its contents. If even one byte changes, the fingerprint changes. The saved reference is never rewritten by this check.</p><p>Use the self-test to see change detection in action. It modifies a temporary copy and leaves the original sample alone.</p><div id="self-test-result"></div><button class="button primary" data-action="integrity-self-test">Run safe self-test</button></div></details>`;
}
function humanSize(value) {
  let size = Number(value || 0);
  const units = ["bytes", "KB", "MB", "GB", "TB"];
  let index = 0;
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}
function importEvidenceFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/api/evidence/import");
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.setRequestHeader("X-TraceByte-Filename", encodeURIComponent(file.name));
    request.upload.onprogress = event => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    request.onerror = () => reject(new Error("The file could not be sent to the local workbench."));
    request.onabort = () => reject(new Error("The file upload was cancelled."));
    request.onload = () => {
      let result = {};
      try { result = JSON.parse(request.responseText); } catch { /* use the status text below */ }
      if (request.status < 200 || request.status >= 300) return reject(new Error(result.error || `Upload failed (${request.status}).`));
      resolve(result);
    };
    request.send(file);
  });
}
async function renderEvidence() {
  let data;
  try { data = await api("/api/evidence"); }
  catch (error) {
    if (!/not found|404/i.test(error.message)) throw error;
    $("#content").innerHTML = `${title("REAL DATA", "Evidence analysis", "This local server needs its updated evidence API before it can import and scan real files.")}${panel("Updated workbench available", "The older server on port 8510 could not be stopped automatically", `<p class="body-copy">Open the updated local instance, or restart the older TraceByte process and run <code>python server.py</code>. Your existing sample files and experiment results are unchanged.</p><a class="button primary" href="http://127.0.0.1:8511/">Open updated workbench on port 8511</a>`)}`;
    return;
  }
  const sources = data.sources || [];
  const scans = data.scans || [];
  if (!state.selectedEvidenceScan && scans.length) state.selectedEvidenceScan = scans[0].scan_id;
  let selectedScan = scans.find(item => item.scan_id === state.selectedEvidenceScan) || null;
  if (state.selectedEvidenceScan) selectedScan = await api(`/api/evidence/scans/${encodeURIComponent(state.selectedEvidenceScan)}`);

  const sourceCards = sources.map(source => `<article class="evidence-source-card"><div class="evidence-source-head"><div><span class="eyebrow">IMPORTED COPY</span><h3>${esc(source.original_name)}</h3><p>${humanSize(source.size_bytes)} <span>·</span> Added ${date(source.imported_utc)}</p></div><span class="tag info">${pretty(source.scan_count)} scan${source.scan_count === 1 ? "" : "s"}</span></div><div class="evidence-source-actions"><button class="button primary" data-evidence-scan="${esc(source.source_id)}">Scan this copy</button>${source.latest_scan_id ? `<button class="button subtle" data-show-evidence-scan="${esc(source.latest_scan_id)}">Open latest results</button>` : ""}<details class="technical-details"><summary>Fingerprint</summary><div class="detail-content"><span>SHA-256</span><code>${esc(source.sha256)}</code></div></details></div></article>`).join("");
  const scanHistory = scans.slice(0, 8).map(scan => `<div class="evidence-scan-item"><div><strong>${esc(scan.original_name || "Evidence scan")}</strong><small>${date(scan.created_utc)} · ${pretty(scan.candidate_count)} candidate${scan.candidate_count === 1 ? "" : "s"}</small></div><button class="button subtle" data-show-evidence-scan="${esc(scan.scan_id)}">View results</button></div>`).join("");
  let resultPanel = `<div class="empty"><strong>No evidence scan selected</strong><p>Import a file or choose a previous scan to see its results.</p></div>`;
  if (selectedScan) {
    const candidateRows = (selectedScan.candidates || []).map(candidate => {
      const offset = `0x${Number(candidate.offset || 0).toString(16).toUpperCase().padStart(8, "0")}`;
      const detail = `<details class="candidate-details"><summary>Scan details</summary><div class="detail-content"><span>Extent method</span><code>${esc(candidate.extent_policy || "unknown")}</code><span>Candidate SHA-256</span><code>${esc(candidate.output_sha256 || "Not available")}</code><span>Review note</span><code>${esc(candidate.notes || "No additional details")}</code></div></details>`;
      const save = candidate.output_name ? `<a class="button subtle" href="/api/evidence/scans/${encodeURIComponent(selectedScan.scan_id)}/files/${encodeURIComponent(candidate.output_name)}" download>Save candidate</a>` : candidate.metadata?.output_skipped_reason ? tag("OUTPUT_LIMIT") : "No output file";
      return `<tr><td><strong>${esc(candidate.signature)}</strong><div class="muted">${esc(candidate.extension)}</div></td><td class="mono">${offset}<div class="muted">${pretty(candidate.offset)} bytes</div></td><td>${humanSize(candidate.length)}</td><td>${tag(String(candidate.status || "").toUpperCase())}</td><td><div class="row-actions">${save}${detail}</div></td></tr>`;
    });
    const findings = selectedScan.status === "failed"
      ? `<div class="inline-alert error"><strong>Scan stopped.</strong> ${esc(selectedScan.error || "The scan could not be completed.")}</div>`
      : `${selectedScan.status === "complete" ? `<div class="inline-alert warning"><strong>A signature match is a lead, not proof.</strong> An end marker does not confirm that a candidate is a valid or complete file. Review the source and validate candidates with an appropriate format parser.</div>` : ""}${table(["Detected type", "Starting position", "Candidate size", "Extent status", "Actions"], candidateRows, "No supported signatures were found. This scan recognizes JPEG, PNG, GIF, PDF, and ZIP signatures; absence of a match does not prove that no recoverable data exists.")}`;
    resultPanel = `<div class="evidence-report-head"><div><h3>${esc(selectedScan.original_name)}</h3><p>${humanSize(selectedScan.size_bytes)} · scanned ${date(selectedScan.created_utc)} · up to ${humanSize(selectedScan.candidate_max_size_bytes)} per candidate</p></div><div class="evidence-report-actions">${tag(String(selectedScan.status || "").toUpperCase())}${selectedScan.status === "complete" ? `<a class="button subtle" href="/api/evidence/scans/${encodeURIComponent(selectedScan.scan_id)}/report" download>Download report</a>` : ""}</div></div><div class="kpi-grid evidence-kpis">${kpi("Candidates", pretty(selectedScan.candidate_count), "Signature matches found", true)}${kpi("End markers found", pretty(selectedScan.delimited_count), "Extent has a known trailer")}${kpi("May be incomplete", pretty(selectedScan.truncated_count), "Extent estimated from nearby data")}${kpi("Not saved", pretty(selectedScan.output_limited_count), "Output size safety limit")}</div>${findings}`;
  }
  const upload = `<section class="evidence-upload"><div class="evidence-upload-copy"><span class="eyebrow">LOCAL EVIDENCE INTAKE</span><h2>Analyze a real file or raw image</h2><p>Select a file from this computer. TraceByte stores a separate copy, records its SHA-256 fingerprint, and scans that copy without editing it.</p><div class="evidence-boundary"><strong>Supported input</strong><span>Individual files and uncompressed raw images, up to 2 GiB. Current signature scan recognizes JPEG, PNG, GIF, PDF, and ZIP, with up to 5,000 candidates per scan. Choose an 8, 16, 32, or 64 MiB maximum candidate size. Extracted files are capped at 512 MiB per scan.</span></div></div><div class="evidence-upload-controls"><label for="evidence-file">Choose evidence file</label><input id="evidence-file" type="file"><label for="candidate-max-size">Maximum size for one candidate</label><select class="select" id="candidate-max-size"><option value="8">8 MiB · faster</option><option value="16">16 MiB</option><option value="32">32 MiB</option><option value="64">64 MiB · larger files</option></select><button class="button primary button-large" data-action="upload-evidence">Import copy and scan</button><div class="evidence-progress" id="evidence-progress" aria-live="polite">Your selected file stays unchanged.</div></div></section>`;
  const historyPanel = panel("Previous evidence scans", "Reopen a saved candidate report", scanHistory || `<div class="empty"><strong>No scans saved yet</strong><p>Your real evidence scan history will appear here.</p></div>`);
  const sourcePanel = panel("Imported evidence copies", `${pretty(sources.length)} source${sources.length === 1 ? "" : "s"} stored on this computer`, sourceCards || `<div class="empty"><strong>No real evidence imported</strong><p>Use the intake panel to import a file or raw image. Synthetic examples remain available in Dataset and Carving lab.</p></div>`);
  $("#content").innerHTML = `${title("REAL DATA", "Evidence analysis", "Scan a working copy of user-supplied evidence alongside the synthetic demonstration workflow.")}${upload}<div class="evidence-notice"><span class="evidence-notice-icon">i</span><p><strong>Keep the findings in context.</strong> This workstation scans individual files and uncompressed raw byte images. It does not acquire a live disk, interpret E01 containers, or prove that a detected candidate is intact.</p></div><div class="two-col evidence-columns">${sourcePanel}${historyPanel}</div>${sectionTitle("Latest candidate report", "REAL EVIDENCE · READ-ONLY SCAN")}${panel("Scan findings", selectedScan ? "Candidates found in the imported copy" : "Choose a source or run a scan", resultPanel)}`;
}
async function renderCarve() {
  const [data, runsData] = await Promise.all([api("/api/dataset"), api("/api/runs")]);
  const signatures = (data.catalogue || []).filter(row => row.signature_hex).map(row => `<tr><td><span class="file-name">${esc(row.filename)}</span></td><td class="mono"><span class="tag info">${esc(row.signature_hex)}</span></td><td>${esc(row.description)}</td></tr>`);
  const conditions = [["Together", "Each sample file is stored as one complete piece."], ["Split apart", "The bytes of each sample are spread into separate pieces."], ["Partly overwritten", "Some original bytes are replaced with other data."]].map(([name, desc], index) => `<div class="condition-item"><div class="condition-icon">${index + 1}</div><div><div class="condition-name">${name}</div><div class="condition-note">${desc}</div></div></div>`).join("");
  const runRows = (runsData.runs || []).slice().reverse().slice(0, 5).map((run, index) => `<div class="run-row"><div><div class="run-id">Test ${pretty((runsData.runs || []).length - index)} · ${date(run.created_utc)}</div><div class="run-meta">Saved recovery results</div></div>${tag(run.status)}</div>`).join("");
  $("#content").innerHTML = `${title("RECOVERY TEST", "Try file recovery", "See how well the tool finds files when their data is stored in different ways.")}
    <div class="two-col">${panel("What this test does", "One click checks all three sample conditions", `<p class="body-copy">The tool makes a safe copy of the sample data, looks for known file patterns, and compares any recovered files with the originals. Your sample files are left unchanged.</p><div class="condition-list">${conditions}</div><div class="inline-alert">Each test is saved separately so you can come back to older results.</div><button class="button primary button-large" data-action="run">Run the recovery test</button>`)}${panel("Previous tests", `${(runsData.runs || []).length} saved run${(runsData.runs || []).length === 1 ? "" : "s"}`, runRows || `<div class="empty"><div class="empty-icon">○</div><strong>No tests yet</strong><p>Run the recovery test to create your first set of results.</p></div>`)} </div>
    <details class="section-disclosure"><summary>Supported file patterns <span>JPEG, PDF, and ZIP</span></summary><div class="disclosure-body">${table(["Sample file", "Pattern found in file", "What the sample represents"], signatures)}</div></details>`;
}
function conditionLabel(value = "") {
  const key = String(value).toLowerCase().replace(/[ _-]+/g, " ").trim();
  return ({ contiguous: "Stored together", fragmented: "Split apart", "partially overwritten": "Partly overwritten" })[key] || key.replace(/\b\w/g, char => char.toUpperCase());
}
function runLabel(run, index) { return `Test ${index + 1} · ${date(run.created_utc)}`; }
async function renderResults() {
  const runsData = await api("/api/runs");
  state.runs = runsData.runs || [];
  if (!state.selectedRun || !state.runs.some(item => item.run_id === state.selectedRun)) state.selectedRun = [...state.runs].reverse()[0]?.run_id || "";
  const selectedIndex = state.runs.findIndex(item => item.run_id === state.selectedRun);
  const action = state.runs.length ? `<label class="run-picker-label" for="run-select">Choose a test</label><select class="select" id="run-select">${state.runs.map((item, index) => `<option value="${esc(item.run_id)}" ${item.run_id === state.selectedRun ? "selected" : ""}>${esc(runLabel(item, index))}</option>`).join("")}</select>` : "";
  if (!state.selectedRun) {
    $("#content").innerHTML = `${title("RECOVERY RESULTS", "See what was recovered", "Each test compares the files the tool found with the original samples.")}${panel("No saved tests yet", "Your sample files are ready for a recovery test", `<div class="empty"><div class="empty-icon">1</div><strong>Start with a recovery test</strong><p>The test checks files stored together, split apart, and partly overwritten.</p><button class="button primary" data-page="carve" style="margin-top:16px">Go to recovery test</button></div>`)}`;
    return;
  }
  const data = await api(`/api/runs/${encodeURIComponent(state.selectedRun)}`);
  const records = data.records || [];
  const avg = select => records.length ? records.reduce((sum, row) => sum + Number(select(row) || 0), 0) / records.length : 0;
  const found = row => Number(row.detection?.tp || 0);
  const total = row => Number(row.detection?.tp || 0) + Number(row.detection?.fn || 0);
  const restored = row => Number(row.exact_recovery?.tp || 0);
  const restorable = row => Number(row.exact_recovery?.tp || 0) + Number(row.exact_recovery?.fn || 0);
  const conditionRows = records.map(row => `<tr><td><strong>${esc(conditionLabel(row.condition))}</strong></td><td>${pretty(found(row))} of ${pretty(total(row))}</td><td>${pretty(restored(row))} of ${pretty(restorable(row))}</td><td>${percent(row.mean_byte_coverage)}</td></tr>`);
  const detailCards = records.map(row => {
    const outcomes = (row.outcomes || []).map(item => {
      const coverage = Math.max(0, Math.min(100, Number(item.byte_coverage || 0) * 100));
      return `<tr><td><span class="file-name">${esc(item.file_id)}</span></td><td>${item.detected ? tag("DETECTED") : tag("NOT FOUND")}</td><td>${item.exact ? tag("EXACT") : tag(item.status || "PENDING")}</td><td><div class="coverage-cell"><div class="progress"><span style="width:${coverage}%"></span></div><span class="mono">${percent(item.byte_coverage)}</span></div></td></tr>`;
    });
    const d = row.detection || {}; const r = row.exact_recovery || {};
    const scores = Object.entries(row.per_signature || {}).map(([name, value]) => `<div class="bar-row"><span class="bar-label">${esc(name)}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.max(0, Math.min(100, Number(value.recall || 0) * 100))}%"></div></div><span class="bar-value">${percent(value.recall)}</span></div>`).join("");
    const extras = row.false_positives || [];
    const advanced = `<details class="technical-details advanced-metrics"><summary>Technical measurements</summary><div class="disclosure-body"><div class="result-grid"><div class="result-card"><h3>Detection score</h3><div class="big">${percent(d.f1)}</div><small>${pretty(d.tp)} found · ${pretty(d.fp)} extra · ${pretty(d.fn)} missed</small></div><div class="result-card"><h3>Exact recovery score</h3><div class="big">${percent(r.recall)}</div><small>${pretty(r.tp)} of ${pretty(r.tp + r.fn)} original files</small></div><div class="result-card"><h3>Data completeness</h3><div class="big">${percent(row.data_completeness)}</div><small>${percent(row.mean_byte_coverage)} average bytes recovered</small></div></div>${scores ? `${sectionTitle("Results by file type")}<div class="chart-bars">${scores}</div>` : ""}${extras.length ? `<details class="technical-details"><summary>Extra matches (${extras.length})</summary><div class="disclosure-body">${table(["Candidate", "File type", "Position", "Size", "Note"], extras.map(item => `<tr><td class="mono">${esc(item.candidate_id)}</td><td>${esc(item.signature)}</td><td class="mono">${pretty(item.offset)}</td><td class="mono">${pretty(item.length)} bytes</td><td>${esc(item.note)}</td></tr>`))}</div></details>` : ""}${(row.notes || []).map(note => `<div class="inline-alert warning">${esc(note)}</div>`).join("")}</div></details>`;
    return `<details class="result-disclosure"><summary><span>${esc(conditionLabel(row.condition))}</span><small>${pretty(found(row))} of ${pretty(total(row))} found · ${pretty(restored(row))} recovered exactly</small></summary><div class="disclosure-body"><p class="results-explainer">A file can be found even when all of its contents cannot be restored.</p>${table(["Sample file", "Found", "Restored exactly", "Bytes recovered"], outcomes, "No file-by-file results were saved for this condition.")}${advanced}</div></details>`;
  }).join("");
  const run = state.runs[selectedIndex] || {};
  $("#content").innerHTML = `${title("RECOVERY RESULTS", "See what was recovered", "Compare the files found and restored for each storage condition.", action)}
    <div class="kpi-grid">${kpi("Test conditions", pretty(records.length), "Each uses the same sample files")}${kpi("Found rate", percent(avg(row => total(row) ? found(row) / total(row) : 0)), "Average files recognized", true)}${kpi("Exact recovery", percent(avg(row => restorable(row) ? restored(row) / restorable(row) : 0)), "Files matching the original")}${kpi("File data recovered", percent(avg(row => row.mean_byte_coverage)), "Average share of original contents")}</div>
    <div class="results-run-note">${tag(String(run.status || "saved").toUpperCase())}<span>${esc(runLabel(run, selectedIndex))}</span></div>
    ${panel("At a glance", "Files found and restored in each condition", `<p class="results-explainer">“Found” means the tool recognized a file. “Restored exactly” means the recovered contents match the original sample.</p>${table(["File condition", "Files found", "Restored exactly", "Bytes recovered"], conditionRows, "No results were saved for this test.")}`)}
    ${sectionTitle("File-by-file results", "Select a condition to see more")}<div class="result-disclosures">${detailCards || `<div class="empty"><strong>No file details available</strong><p>This saved test does not contain per-file results.</p></div>`}</div>`;
  $("#run-select")?.addEventListener("change", event => { state.selectedRun = event.target.value; render(); });
}
async function renderLog() {
  const data = await api("/api/log"); state.events = data.events || [];
  const eventOptions = (data.event_types || []).map(item => `<option value="${esc(item)}">${esc(friendlyEvent(item))}</option>`).join("");
  const actorOptions = (data.actors || []).map(item => `<option value="${esc(item)}">${esc(item)}</option>`).join("");
  $("#content").innerHTML = `${title("WORKSPACE HISTORY", "Recent activity", "A record of checks and recovery tests carried out in this workspace.", `<button class="button" data-action="export-log">Download activity data</button>`)}
    <div class="kpi-grid">${kpi("Activities", pretty(data.events?.length), "Records in this workspace")}${kpi("Action types", pretty(data.event_types?.length), "Checks and recovery tests")}${kpi("Users and processes", pretty(data.actors?.length), "Who or what recorded an action")}${kpi("History saved", "Yes", "Stored on this device", true)}</div>
    ${panel("Find an activity", "Choose a type or user to narrow the list", `<div class="form-row"><label class="filter-field"><span>Action</span><select class="select" id="log-event"><option value="">All actions</option>${eventOptions}</select></label><label class="filter-field"><span>Recorded by</span><select class="select" id="log-actor"><option value="">Everyone</option>${actorOptions}</select></label><button class="button" data-action="filter-log">Show activities</button><button class="button subtle" data-action="clear-log-filters">Clear filters</button></div>`)}
    ${sectionTitle("Activity", "Newest first")}${panel("Workspace history", "Select an entry to see its saved details", `<div id="event-list">${renderEvents(state.events)}</div>`)}`;
}
function renderEvents(events) {
  if (!events.length) return `<div class="empty"><div class="empty-icon">—</div><strong>No activities found</strong><p>Try clearing the filters or run a check to add an activity.</p></div>`;
  return events.map(event => {
    const payload = Object.entries(event.payload || {});
    const details = payload.length ? `<details class="event-details"><summary>Show saved details</summary><dl>${payload.map(([key, value]) => `<div><dt>${esc(key.replace(/[_-]/g, " "))}</dt><dd>${esc(typeof value === "string" ? value : JSON.stringify(value))}</dd></div>`).join("")}</dl></details>` : "";
    return `<article class="log-event"><div class="log-time">${date(event.timestamp_utc)}</div><div class="log-copy"><div class="log-name">${esc(friendlyEvent(event.event || "Activity"))}</div><div class="log-detail">Recorded by ${esc(event.actor || "local process")}</div>${details}</div>${tag("RECORDED")}</article>`;
  }).join("");
}
function updateSidebar() {
  const data = state.overview;
  if (!data) return;
  const summary = data.integrity || {};
  $("#status-evidence").textContent = `${pretty(summary.MATCH)} / ${pretty(data.fixture_count)} match`;
  $("#status-runs").textContent = pretty(data.runs?.length || 0);
  $("#status-events").textContent = pretty(data.event_count || 0);
}
async function refreshOverview() {
  try { state.overview = await api("/api/overview"); state.runs = state.overview.runs || []; updateSidebar(); }
  catch (error) { toast(error.message, true); }
}
async function runExperiment(button) {
  if (button) { button.disabled = true; button.innerHTML = '<span class="spinner"></span>Running all conditions'; }
  try {
    const result = await api("/api/runs", { method: "POST", body: JSON.stringify({}) });
    toast(`Run complete · ${result.run_id}`); state.selectedRun = result.run_id; state.page = "results"; history.replaceState(null, "", "#results");
    await render(); await refreshOverview();
  } catch (error) { toast(error.message, true); if (button) { button.disabled = false; button.textContent = "Run all conditions"; } }
}
function bindActions() {
  $$('[data-page]', $("#content")).forEach(button => button.addEventListener("click", () => setPage(button.dataset.page)));
  $$('[data-action="refresh"]').forEach(button => button.addEventListener("click", render));
  $$('[data-action="run"]').forEach(button => button.addEventListener("click", () => runExperiment(button)));
  $$('[data-action="initialize"]').forEach(button => button.addEventListener("click", async () => {
    button.disabled = true; button.textContent = "Initializing…";
    try { const result = await api("/api/dataset/initialize", { method: "POST", body: JSON.stringify({}) }); toast(`Dataset ready · ${result.created_count} created, ${result.preserved_count} preserved`); await render(); await refreshOverview(); }
    catch (error) { toast(error.message, true); button.disabled = false; button.textContent = "＋  Initialize dataset"; }
  }));
  $$('[data-action="integrity-self-test"]').forEach(button => button.addEventListener("click", async () => {
    button.disabled = true; button.textContent = "Testing…";
    try { const result = await api("/api/integrity/self-test", { method: "POST", body: JSON.stringify({}) }); const target = $("#self-test-result"); if (target) target.innerHTML = `<div class="inline-alert ${result.ok ? "" : "error"}">${esc(result.detail || (result.ok ? "Self-test passed." : "Self-test could not complete."))}${result.expected_sha256 ? `<div class="hash">BASELINE ${esc(result.expected_sha256)}</div><div class="hash">MUTATED&nbsp; ${esc(result.mutated_sha256)}</div>` : ""}</div>`; else toast(result.detail || "Self-test finished.", !result.ok); }
    catch (error) { toast(error.message, true); }
    finally { button.disabled = false; button.textContent = "Run detection self-test"; }
  }));
  $$('[data-action="upload-evidence"]').forEach(button => button.addEventListener("click", async () => {
    const file = $("#evidence-file")?.files?.[0];
    const progress = $("#evidence-progress");
    if (!file) { toast("Choose an evidence file first.", true); return; }
    if (file.size > 2 * 1024 * 1024 * 1024) { toast("Evidence files may be up to 2 GiB.", true); return; }
    button.disabled = true;
    button.textContent = "Importing copy…";
    if (progress) progress.textContent = "Uploading 0%";
    let copyImported = false;
    try {
      const source = await importEvidenceFile(file, value => { if (progress) progress.textContent = `Uploading ${Math.round(value * 100)}%`; });
      copyImported = true;
      if (progress) progress.textContent = "Copy saved. Scanning for supported file signatures…";
      button.textContent = "Scanning copy…";
      const candidateMaxSize = Number($("#candidate-max-size")?.value || 8);
      const result = await api("/api/evidence/scans", { method: "POST", body: JSON.stringify({ source_id: source.source_id, candidate_max_size_mb: candidateMaxSize }) });
      state.selectedEvidenceScan = result.scan_id;
      await render();
      toast(`${pretty(result.candidate_count)} candidate${result.candidate_count === 1 ? "" : "s"} found. Review the findings before treating a candidate as recovered.`);
      await refreshOverview();
    } catch (error) {
      if (progress) progress.textContent = error.message;
      toast(error.message, true);
      button.disabled = false;
      button.textContent = "Import copy and scan";
      if (copyImported) { state.selectedEvidenceScan = ""; await render(); }
    }
  }));
  $$('[data-evidence-scan]').forEach(button => button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Scanning copy…";
    try {
      const candidateMaxSize = Number($("#candidate-max-size")?.value || 8);
      const result = await api("/api/evidence/scans", { method: "POST", body: JSON.stringify({ source_id: button.dataset.evidenceScan, candidate_max_size_mb: candidateMaxSize }) });
      state.selectedEvidenceScan = result.scan_id;
      await render();
      toast(`${pretty(result.candidate_count)} candidate${result.candidate_count === 1 ? "" : "s"} found. Review the findings before treating a candidate as recovered.`);
    } catch (error) {
      toast(error.message, true);
      button.disabled = false;
      button.textContent = "Scan this copy";
    }
  }));
  $$('[data-show-evidence-scan]').forEach(button => button.addEventListener("click", () => {
    state.selectedEvidenceScan = button.dataset.showEvidenceScan;
    render();
  }));
  $$('[data-action="filter-log"]').forEach(button => button.addEventListener("click", async () => {
    const params = new URLSearchParams(); if ($("#log-event").value) params.set("event", $("#log-event").value); if ($("#log-actor").value) params.set("actor", $("#log-actor").value);
    try { const result = await api(`/api/log?${params}`); $("#event-list").innerHTML = renderEvents(result.events || []); }
    catch (error) { toast(error.message, true); }
  }));
  $$('[data-action="clear-log-filters"]').forEach(button => button.addEventListener("click", async () => { const event = $("#log-event"); const actor = $("#log-actor"); if (event) event.value = ""; if (actor) actor.value = ""; const result = await api("/api/log"); $("#event-list").innerHTML = renderEvents(result.events || []); }));
  $$('[data-action="export-log"]').forEach(button => button.addEventListener("click", async () => { try { const result = await api("/api/log"); const text = (result.events || []).slice().reverse().map(row => JSON.stringify(row)).join("\n"); download(text ? `${text}\n` : "", "experiment_log.jsonl", "application/x-ndjson"); } catch (error) { toast(error.message, true); } }));
  $$('[data-action="manifest"]').forEach(button => button.addEventListener("click", async () => { try { const result = await api("/api/dataset"); download(`${JSON.stringify(result.manifest, null, 2)}\n`, "manifest.json", "application/json"); } catch (error) { toast(error.message, true); } }));
  $$('[data-preview]').forEach(button => button.addEventListener("click", () => openPreview(button.dataset.preview)));
}
function download(content, filename, type) { const url = URL.createObjectURL(new Blob([content], { type })); const a = document.createElement("a"); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url); }
async function openPreview(filename) {
  try {
    const data = await api(`/api/fixtures/${encodeURIComponent(filename)}/hex`);
    const backdrop = document.createElement("div"); backdrop.className = "modal-backdrop";
    const lines = data.lines.map(row => `<span class="offset">${esc(row.offset)}</span>${esc(row.hex)} &nbsp; <span class="muted">${esc(row.ascii)}</span>`).join("\n");
    backdrop.innerHTML = `<div class="modal"><div class="eyebrow">EVIDENCE / BYTE PREVIEW</div><h2>${esc(filename)}</h2><p>Read-only opening bytes · ${pretty(data.size_bytes)} total bytes · synthetic fixture</p><div class="byte-view">${lines}</div><div class="toolbar"><span class="toolbar-note">OFFSET · HEX · ASCII</span><button class="button" data-close>Close</button></div></div>`;
    backdrop.addEventListener("click", event => { if (event.target === backdrop || event.target.closest("[data-close]")) backdrop.remove(); }); document.body.append(backdrop);
  } catch (error) { toast(error.message, true); }
}
$("#today").textContent = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" }).format(new Date()).toUpperCase();
$$('.nav-link').forEach(button => button.addEventListener("click", () => setPage(button.dataset.page)));
$("#refresh-button").addEventListener("click", render);
window.addEventListener("hashchange", () => setPage(location.hash.slice(1)));
api("/api/health").then(async () => { await refreshOverview(); setPage(state.page); }).catch(error => { $("#content").innerHTML = `${title("LOCAL ENGINE / OFFLINE", "Engine unavailable", "Start the TraceByte local web server to connect this workspace.")}${panel("Connection failed", "Local API", `<div class="inline-alert error">${esc(error.message)}</div><code>python server.py</code>`)}`; });
