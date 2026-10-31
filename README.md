# TraceByte — Signature Carving Evaluation

![Tests](https://img.shields.io/badge/tests-170%20passing-brightgreen)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)
![Domain](https://img.shields.io/badge/domain-Digital%20Forensics-blueviolet)

TraceByte is a forensic evaluation workbench for file-signature carving. It measures
how accurately a carving engine recovers files under three controlled storage
conditions — contiguous, fragmented, and partially overwritten — using a reproducible
synthetic dataset with cryptographic ground-truth tracking. It also supports
read-only scans of user-supplied evidence copies through a local web interface.

## ⚡ Quickstart

```powershell
# 1 — Clone and enter the repo
git clone https://github.com/your-username/TraceByte.git
cd TraceByte

# 2 — Create the virtual environment and install dev dependencies
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3 — Launch the workbench
python app.py          # opens at http://127.0.0.1:8510
```

Run the full test suite (170 tests, ~32 s):
```powershell
python -m pytest -q
```

---

## 1. What this project does

TraceByte measures how accurately a file-signature carving engine recovers files
that are stored under three conditions:

| Condition | Description |
| --- | --- |
| Contiguous | the whole file is stored in one continuous run of bytes |
| Fragmented | the file is split across several non-contiguous byte ranges |
| Partially overwritten | some bytes of the original have been overwritten by later data |

The project produces three deliverables:

1. **Experimental dataset** — a reproducible, synthetic dataset with a hashed baseline.
2. **Precision / recall table** — computed only from explicitly measured ground truth.
3. **Failure analysis** — limitations, alternative explanations and reproducibility checks.

### Current status

**The assigned experiment and workbench are implemented.** The project includes
the synthetic ground-truth dataset, SHA-256 baseline, integrity checks, isolated
multi-run experiments, signature scanner and carver, metrics, provenance log, local
web UI, and an independent real-evidence intake workflow. The final report and
reproducibility materials are in `reports/`.

| Component | Scope | Status |
| --- | --- | --- |
| Dataset and integrity | Synthetic ground truth, baseline hashes, and checks | **Complete** |
| Carving experiment | Signature scan, recovery, and three storage conditions | **Complete** |
| Evaluation and reporting | Metrics, failure analysis, limitations, report, and viva guide | **Complete** |
| Workbench | Local UI, real evidence intake, provenance log | **Complete** |

> **Nothing in this repository fabricates a metric.** Every number on the
> **Results** page is computed from the ground-truth map that was written
> *before* carving and from the baseline manifest. The carver never sees the
> ground truth; the measurement layer never guesses.

### Measured results (saved run)

The following values are read from the saved run
`run-20261027T141506Z-489d1acf`, created 2026-10-27 14:15 UTC. The run contains
its own `run.json`, ground-truth maps, carve outputs, and `metrics.json` files.
New runs may differ if project code or the baseline changes.

| Condition | Detection P / R / F1 | Exact SHA-256 matches | Mean byte coverage | Data completeness |
| --- | --- | --- | --- | --- |
| Contiguous | 0.7778 / 1.0000 / 0.8750 | 3 of 8 files | 100.00 % | 100.00 % |
| Fragmented | 0.7778 / 1.0000 / 0.8750 | 0 of 8 files | 33.64 % | 100.00 % |
| Partially overwritten | 0.7778 / 1.0000 / 0.8750 | 0 of 8 files | 75.15 % | 75.02 % |

Reading the table:

* **Detection recall is 1.00 over the seven ground-truth signature instances**
  in each condition. The embedded JPEG signature is detected, but is not counted
  as a top-level file recovery.
* **Detection precision is 0.7778 (7 TP, 2 FP) in this run.** The two false
  positives are the two planted decoy signatures with no ground-truth file
  starting at their offsets. The filler is checked for accidental signatures.
  This controlled result is not a real-world false-positive rate.
* **Three of eight ground-truth files match their baseline SHA-256** in the
  contiguous condition. Those are the three
  fixtures that carry their own terminator (`FFD9`, `%%EOF`, `PK 05 06`). The
  five fixtures start with a signature but contain no terminator,
  so a carving engine can detect them but cannot delimit them — the carve
  either runs into the next file (**over-carving**) or stops at the end of the
  stream (**truncation**). This is the central experimental finding.
* **Fragmentation destroys recovery.** All data is still present
  (completeness 100 %), but the bytes are no longer contiguous, so the
  signature-delimited extent no longer matches the original and only about a
  third of the bytes survive a naive byte-by-byte comparison.
* **Overwriting reduces byte availability.** In this run data completeness is
  75.02 % and mean byte coverage is 75.15 %. These measures are close but distinct.

---

## 2. Forensic and integrity rules applied

1. **Synthetic experiment fixtures.** Files used for measured precision and recall
   are generated locally by `src/fixtures.py` from a fixed seed. The separate real
   evidence workflow below does not feed imported data into synthetic metrics.
2. **Separation of concerns.** Ground truth (`data/originals/`), experimental inputs
   (`data/experiments/`), imported evidence copies (`data/evidence/`) and recovery
   output (`data/recovered/`) live in separate directories and are never mixed.
3. **Originals are never silently overwritten.** Dataset initialisation creates only
   the files that do not exist yet. An existing original is always preserved byte for
   byte.
4. **Baselines are never silently regenerated.** A recorded SHA-256 is written once.
   Re-running initialisation does not change it. A change is *reported*, not absorbed.
   The only way to replace a baseline is `src.manifest.rebaseline_entry()`, which
   demands a written reason and writes an event to the experiment log.
5. **Provenance is recorded.** File size, SHA-256, timestamps, tool versions and
   experiment parameters are stored in `data/originals/manifest.json` and in
   `logs/experiment_log.jsonl`.
6. **Detection, recovery and validation are different claims.** They are recorded
   separately; a signature hit is never reported as a recovered
   file.
7. **Metrics only come from measured ground truth.** Precision and recall will be
   computed from the baseline manifest, never from assumed or simulated labels.
8. **Synthetic fixtures are labelled.** The JPEG-like, PDF-like and ZIP-like fixtures
   carry a real signature but are **not valid, fully parseable files**. They are
   marked `fully_parseable = false` in the manifest and are never presented as valid
   recovered media or documents.

### 2.1 Real evidence intake

The **Real evidence** page accepts an individual file or an uncompressed raw image
up to 2 GiB. The browser sends the selected file to the local workstation, which
stores a content-addressed copy under `data/evidence/sources/`, records its size and
SHA-256, and scans that copy without modifying it. Re-importing identical bytes
reuses the existing copy. Each scan stores a candidate report under
`data/evidence/scans/` and any extracted candidates under
`data/recovered/evidence/`; import and scan actions are added to the provenance log.

Real evidence scans currently recognize JPEG, PNG, GIF, PDF and ZIP signatures and cap a scan
at 5,000 candidates and 512 MiB of extracted output. Operators can choose an 8, 16,
32 or 64 MiB maximum extent for each candidate. The scanner does not acquire a live device, unpack E01/EWF
containers, interpret file systems, or establish that a signature hit is a valid
file. An end marker is only a structural clue. Use a format parser and independent
validation before treating a candidate as recovered. Precision, recall and exact
recovery metrics remain available only for synthetic runs with known ground truth.

---

## 3. Project structure

```
TraceByte/
├── app.py                  # Forensic Workbench entry point (run this)
├── server.py               # Local HTTP API over the existing Python engine
├── web/                    # Cyber operations interface (HTML, CSS, JavaScript)
├── src/
│   ├── paths.py            # Canonical project paths
│   ├── hashing.py          # Chunked SHA-256 utility
│   ├── manifest.py         # Immutable baseline manifest
│   ├── fixtures.py         # Deterministic synthetic fixtures + initialisation
│   ├── integrity.py        # Verification, mismatch/missing/unregistered detection
│   ├── experiment_log.py   # Append-only JSON Lines provenance log
│   ├── evidence.py         # Local import, hashing, and real-evidence scan records
│   ├── signatures.py       # Signature registry, scanner, extent policies
│   ├── conditions.py       # Three controlled storage conditions
│   ├── carver.py           # Carving engine and per-candidate provenance
│   ├── metrics.py          # Detection / recovery / validation scoring
│   └── experiments.py      # Build -> carve -> measure -> log
├── data/
│   ├── originals/          # Ground truth: fixtures + manifest.json  (tracked)
│   ├── experiments/        # Experimental inputs + measurements       (ignored)
│   ├── evidence/           # Imported source copies + scan reports     (ignored)
│   └── recovered/          # Carving output                          (ignored)
├── logs/                   # experiment_log.jsonl                     (ignored)
├── reports/                # Generated report artefacts              (ignored)
├── tests/                  # Engine, isolation, and workbench API checks
├── requirements.txt
├── pyproject.toml
└── .gitignore
```

`data/originals/` is **tracked in git on purpose**: it holds the ground truth and the
baseline manifest, so a reviewer can independently re-verify every hash. The other
three directories hold regenerable data and are ignored.

### 3.1 How the experiment artefacts are organised

Every run of the carving experiments owns a directory of its own. Two runs can
therefore never overwrite each other, and the candidates of a run stay
together:

```
data/experiments/
├── run-20261021T120401Z-c7f67afd/          # one run
│   ├── run.json                            # run manifest (run id, timestamp, conditions)
│   ├── exp-contiguous/
│   │   ├── image.bin                       # the built storage image
│   │   ├── ground_truth.json               # what was planted into it
│   │   ├── carve_results.json              # every candidate with its provenance
│   │   └── metrics.json                    # the measured detection / recovery scores
│   ├── exp-fragmented/…
│   └── exp-overwritten/…
└── exp-contiguous/                         # artefacts from before the per-run layout
    …                                        # (read-only, still selectable in the UI)

data/recovered/
├── run-20261021T120401Z-c7f67afd/exp-contiguous/<candidate files>
└── exp-contiguous/<candidate files>         # from before the per-run layout
```

Rules:

* A run identifier is `run-<UTC timestamp>-<random suffix>`; the three
  conditions of one run share it.
* **Nothing is ever deleted.** A later run cannot remove the candidates of an
  earlier one, and the artefacts written before this layout existed stay where
  they are. They are exposed as the read-only `legacy` run and can still be
  selected in the **Carve** and **Results** pages.
* The dashboard shows **one run at a time**. Both pages have a run selector
  that lists every run still on disk; the newest one is selected by default.
* `logs/experiment_log.jsonl` is append-only and records the run identifier of
  every experiment as `payload.experiment_run_id`.

---

## 4. Windows setup (PowerShell)

Run every command from the project root (`D:\TraceByte`).

### 4.1 Create the virtual environment

```powershell
cd D:\TraceByte
py -3 -m venv .venv
```

If `py` is not available, use the full interpreter path:

```powershell
C:\Users\aryan\AppData\Local\Python\bin\python.exe -m venv .venv
```

### 4.2 Activate it

```powershell
.\.venv\Scripts\Activate.ps1
```

> If PowerShell refuses to run the activation script with an
> *"running scripts is disabled on this system"* error, fix it once for your user:
>
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```
>
> Then activate again. You can also skip activation entirely and call the venv
> interpreter directly: `.\.venv\Scripts\python.exe -m pip ...`.

### 4.3 Install test tools (optional)

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The workbench itself uses the Python standard library and needs no package
installation. `requirements.txt` contains `pytest` for running the test suite.

### 4.4 Run the dashboard

```powershell
python app.py
```

The TraceByte Forensic Workbench opens at <http://127.0.0.1:8510>. It uses a
local web server and the existing Python forensic engine; no frontend build
step is needed. The server binds to loopback by default. To choose another
local port:

```powershell
$env:TRACEBYTE_PORT = 8511
python server.py
```

The interface is served directly by the local Python entry point and does not
use Streamlit.

### 4.5 Run the tests

```powershell
python -m pytest -q
```

More verbose variants:

```powershell
python -m pytest -v                 # per-test names
python -m pytest tests/test_integrity.py -v
python -m pytest --collect-only -q  # list the tests without running them
```

**Verified 2026-10-27.** The current suite contains **170 tests** covering the
engine, isolation, integrity, evidence intake, and workbench API behavior. The
suite completed with **170 passed, 0 failed** using
`python -m pytest -q -p no:cacheprovider`.

### 4.6 Build the assignment report PDF (optional)

The Markdown report is the editable source. To regenerate its PDF:

```powershell
python -m pip install "reportlab>=4.2"
python scripts/build_submission_pdf.py
```

The PDF is written to `output/pdf/TraceByte_Final_Report.pdf`.

### 4.7 What the tests do *not* touch

The test suite never writes to the project itself:

* `data/originals/` and `data/originals/manifest.json` are only ever read.
  Every test works on a copy in a temporary directory.
* `data/experiments/`, `data/recovered/` and `logs/experiment_log.jsonl` are
  not touched either. The canonical locations are resolved **when a run
  starts**, not when the modules are imported, so the workbench API tests can
  redirect the application into a temporary workspace.
* `tests/test_isolation.py` is the regression test for this: it fingerprints
  the real originals (including the baseline manifest), the experiment, the
  recovery and the log files, drives a full isolated carve run and asserts
  that not a single byte of the real project state changed.

The paths that are *derived* from a directory follow it: redirecting
`paths.ORIGINALS_DIR` moves `paths.MANIFEST_PATH` with it, redirecting
`paths.LOGS_DIR` moves `paths.EXPERIMENT_LOG_PATH` with it. A workspace that
is handed in explicitly also gets its own manifest, so a verification script
can no longer write to the real baseline while it believes it works in a
sandbox.

Run the suite as often as you like - the project directory stays untouched.

### 4.8 Deactivate the environment (when finished)

```powershell
deactivate
```

---

## 5. Using the dashboard

1. **Overview** — project scope, the applied forensic guardrails and the roadmap.
2. **Dataset** → press **Initialise dataset**.
   * Creates the eight synthetic fixtures in `data/originals/`.
   * Writes the baseline manifest `data/originals/manifest.json` (filename, size,
     SHA-256, description, signature, timestamps, tool versions).
   * Writes a `dataset.initialize` event to `logs/experiment_log.jsonl`.
   * Pressing it again is safe: existing originals are preserved and their baseline
     hashes are left untouched.
   * The manifest is only written when its content actually changed. An unchanged
     baseline stays **byte for byte identical** - including its `updated_utc`
     stamp - so the evidence record of the ground truth is stable. The one
     metadata block that is refreshed on every run is `tool_versions`: if the
     recorded tool versions differ from the current ones, the manifest is
     rewritten and `updated_utc` moves, and nothing else about the baseline
     changes.
3. **Integrity** → compares every original with the baseline and reports
   **MATCH**, **MISMATCH**, **MISSING** or **UNREGISTERED**.
   * The **Run detection self-test** button copies one original into a temporary
     directory, flips a single byte in the *copy* and re-runs the verification. The
     original is never modified. This demonstrates that a modified copy is detected
     as changed.
4. **Carving lab** → the synthetic evaluation engine.
   * Lists the supported signatures (magic bytes, extension, end marker and the
     validation strategy that is applied to each of them).
   * **Run carving experiments** builds the three images, carves them, measures the
     result and appends an `experiment_completed` event to the experiment log.
   * Writes to `data/experiments/<run_id>/<experiment>/` (image, ground truth, carve
     report, metrics) and `data/recovered/<run_id>/<experiment>/` (the carved
     candidates). Every run gets its own directory, so an earlier run and its
     candidates are never overwritten or removed.
   * The **Runs** selector shows the measurements of one run at a time; the newest
     run is selected by default and every earlier run can still be opened.
5. **Results** → the measurements, read back from the artefacts.
   * A comparison table and a grouped bar chart across the three conditions, one
     scorecard per condition, a per-file table that separates *detected*, *carved*,
     *exact* and *span*, the per-signature breakdown and the list of false
     positives. The comparison can be downloaded as CSV.
   * The **Run** selector switches between the runs that are still on disk. Only the
     artefacts of the selected run are shown.
6. **Activity log** — the append-only provenance record, newest first.
   * Filters by event type and by actor, a distribution chart and the full event
     table with the raw payload. The log itself can be downloaded as JSON Lines.

### 5.1 The Forensic Workbench

The local web interface uses a responsive operations layout with a persistent
evidence navigation rail, workspace status, KPI cards, run-scoped analysis
tables, and semantic evidence state indicators. Its HTML, CSS and JavaScript
live in `web/`; `server.py` adapts the UI requests to the established functions
in `src/`. The byte preview is read-only and only serves fixtures registered
in the ground-truth manifest.

---

## 6. The synthetic fixture set

| Fixture | Bytes | Signature | Offset | Fully parseable |
| --- | --- | --- | --- | --- |
| `synthetic_photo_01.jpg` | 3200 | `FFD8FF` (JPEG SOI) | 0 | No |
| `synthetic_doc_01.pdf` | 2167 | `%PDF-` | 0 | No |
| `synthetic_archive_01.zip` | 1667 | `504B0304` (PK local header) | 0 | No |
| `synthetic_blob_01.bin` | 4096 | none | n/a | No |
| `synthetic_container_01.bin` | 3142 | `FFD8FF` embedded | 1024 | No |
| `synthetic_len_photo_01.jpg` | 1213 | `FFD8FF` (JPEG SOI) + `FFD9` terminator | 0 | No |
| `synthetic_len_doc_01.pdf` | 1189 | `%PDF-` + `%%EOF` trailer | 0 | No |
| `synthetic_len_archive_01.zip` | 1202 | `504B0304` + `PK 05 06` record | 0 | No |

The byte content is derived from a SHA-256 counter-mode expansion of a fixed seed, so
it is identical on every platform and every Python version: regenerating the dataset
reproduces the same hashes.

Three fixtures carry a **start** signature but no **terminator**, so a
carving engine can detect them but cannot delimit them. The last three carry an
end marker for their format, which can make a byte-exact recovery possible in the
contiguous condition. They are the difference
between "the signature was found" and "the file was recovered".

Two fixtures act as **negative controls**: `synthetic_blob_01.bin` has no signature
at all, and `synthetic_container_01.bin` only carries a JPEG header *inside* the
file, at offset 1024. A correct engine must not report either of them as a file
that starts at its own offset.

`data/originals/FIXTURE_NOTES.md` repeats this table next to the files.

---

## 7. How the experiment is controlled

The experiment has to be reproducible by someone who did not run it, so every
source of randomness is removed and every assumption is written down.

### 7.1 The three images

`src/conditions.py` builds one image per condition from the eight originals:

| Condition | How the image is built | What it simulates |
| --- | --- | --- |
| `contiguous` | every original is stored in one continuous run of bytes, separated by filler | a file that was written in one go and never touched again |
| `fragmented` | every original is split into 3 fragments that are scattered across the image and separated by filler | a file that was written in several pieces, or whose blocks were relocated |
| `overwritten` | every original is stored contiguously, but 25 % of its interior (from 35 % of the file onwards) is replaced by filler | a file whose blocks were reused by a later file |

Before carving, the module writes `ground_truth.json`: the absolute offset of
every original, the ranges of its fragments, which bytes were overwritten, the
baseline SHA-256 of the original and the signatures that are embedded inside it.
The carver never reads that file.

### 7.2 Why the filler is generated, not random

The filler between the originals contains **no** registered signature and **no**
end marker. That control matters:

* A random `FFD9` in the filler would silently truncate every JPEG carve. The
  result would then depend on luck instead of on the design.
* A random `%PDF-` in the filler would create a false positive that is not
  reported anywhere, and the measured precision would be a property of the
  random draw rather than of the engine.

Instead, the number of false positives is **designed**: two decoy signatures are
planted in the filler of every image, at deterministic positions. After the image
is built it is verified: every signature hit in it must be either a ground-truth
signature or a planted decoy, otherwise the build fails. That is why the measured
precision of 0.78 is a controlled number and not a coincidence.

### 7.3 The three claims

| Claim | Question | Established by |
| --- | --- | --- |
| **detected** | was the signature found at the right offset? | `src/metrics.py`, comparing detections with the ground-truth map |
| **carved** | was a byte range written to `data/recovered/`? | `src/carver.py`, which records the extent policy it used |
| **validated** | do the carved bytes match the original byte for byte? | the baseline SHA-256 of the original, compared with the SHA-256 of the candidate |

A candidate that is detected and carved but fails validation is reported as such:
a *false positive* for detection purposes and a *carved but not validated* file in
the per-file table.

### 7.4 Running it without the dashboard

```powershell
python -c "import json; from src.experiments import run_all_conditions, summarise; print(json.dumps(summarise(run_all_conditions()), indent=2))"
```

Every run writes `data/experiments/<run_id>/<experiment>/` (`image.bin`,
`ground_truth.json`, `carve_results.json`, `metrics.json`, plus the `run.json`
manifest of the run) and `data/recovered/<run_id>/<experiment>/`, and appends an
`experiment_completed` event to the experiment log. The run identifier is
printed by `run_all_conditions()` and can be pinned with
`run_all_conditions(run_id="run-20261021T120401Z-c7f67afd")`.

Earlier runs are never touched: each run owns its directory, and nothing is
deleted.

---

## 8. Verification without the dashboard

The baseline can be checked from a PowerShell prompt:

```powershell
Get-Content data\originals\manifest.json | ConvertFrom-Json |
  ForEach-Object { $_.fixtures } |
  Format-Table filename, size_bytes, sha256
```

Recompute a hash with the project utility:

```powershell
python -c "import sys; sys.path.insert(0,'.'); from src.hashing import sha256_file; print(sha256_file('data/originals/synthetic_photo_01.jpg'))"
```

---

## 9. Limitations

* **The fixtures are not real files.** They carry realistic signatures and, for the
  three `synthetic_len_*` fixtures, a realistic terminator, but no valid structure.
  They are measured as *signature-shaped placeholders*, not genuine JPEG/PDF/ZIP
  content. Real, openly licensed test files with independent parser validation
  could expand evaluation beyond signature-shaped fixtures.
* **Synthetic evaluation formats are JPEG, PDF and ZIP.** Real-evidence scans
  recognize JPEG, PNG, GIF, PDF and ZIP. No compound containers (e.g. DOCX inside
  ZIP) or fragmented-file reassembly are implemented.
* **The extent policies are simple.** A candidate ends at the format's terminator, at
  the next signature or at the end of the stream. There is no size-based carving, no
  carving from the end of the file backwards and no format-aware header repair.
* **Byte coverage is a naive measure.** It assumes that the file's bytes follow the
  signature contiguously. Under fragmentation that assumption is wrong by
  construction, so the coverage figure is a lower bound, not a recovery rate.
* **False positives depend on the test image.** Interpret each result using its
  saved ground-truth map and candidate list. Synthetic filler behavior is not a
  population estimate of false positives on real media.
* **Baseline re-baselining is a library API only.** `rebaseline_entry()` is tested but
  deliberately not exposed in the dashboard, to keep the operator from changing a
  baseline by accident.
* **The experiment log is append-only but not tamper-evident.** It is a plain JSON
  Lines file and is not digitally signed or hash chained.
* **The manifest is not signed.** The baseline is trusted because it lives in version
  control; a detached signature over `manifest.json` is a candidate improvement.
* **Every run keeps its artefacts.** Because nothing is ever deleted,
  `data/experiments/` and `data/recovered/` grow with every run. A retention policy
  (keep the last *n* runs, or a run that the operator explicitly prunes) is a
  possible future improvement.

---

## 10. Reproducibility checklist

* [x] Deterministic fixture generation (fixed seed, no RNG, no timestamps in content)
* [x] SHA-256 baseline for every original, recorded in `manifest.json`
* [x] Originals preserved byte for byte on re-initialisation
* [x] Baseline manifest preserved byte for byte on re-initialisation (it is only
      written when its content actually changed)
* [x] Baselines never regenerated silently
* [x] Tool versions recorded in the manifest and in every log event
* [x] Append-only experiment log in JSON Lines
* [x] Signature scanner with chunk-boundary-safe detection (`src/signatures.py`)
* [x] Carving engine with full per-candidate provenance (`src/carver.py`)
* [x] Three controlled storage conditions with a recorded ground-truth map
* [x] Deterministic filler that contains no signature, plus designed decoys
* [x] Measured precision / recall from the ground truth, never assumed
* [x] Automated test suite covering hashing, initialisation, preservation, change
      detection, scanning, carving, conditions and measurement
* [x] Test suite that never writes to the project: the originals, the baseline
      manifest, the experiment artefacts and the provenance log are unchanged by a
      test run (regression test in `tests/test_isolation.py`)
* [x] Canonical paths resolved when a run starts, and derived paths follow their
      parent directory, so a redirected workspace can never reach the real
      baseline manifest or the real provenance log
* [x] One directory per experiment run, so that runs cannot overwrite each other
      and no artefact is ever deleted
* [x] Failure analysis, limitations, reproducibility notes and final report

---

## 11. Licence and attribution

This project is licensed under the MIT License. Synthetic evaluation fixtures are
generated by the code in `src/`; imported real evidence is user-provided and is
stored and reported separately.
