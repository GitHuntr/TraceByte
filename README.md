# TraceByte | FileCarveLab

**File Signature Carving Evaluation** — Digital Forensics Project Based Learning
Project reference: **DF-PBL-016**

The repository is named **TraceByte**; the research dashboard built on top of it is
branded **FileCarveLab**. The dashboard is the web interface for the experiment.

---

## 1. What this project does

FileCarveLab measures how accurately a file-signature carving engine recovers files
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

**Stage 2 of 5 is implemented.** Stage 1 provided the foundation: the project
scaffold, the synthetic dataset, the SHA-256 baseline manifest, the integrity
verification screen, the provenance log and the automated test suite. Stage 2
adds the signature scanner, the carving engine, the three controlled storage
conditions and the measurement layer that turns a carve into numbers.

| Stage | Scope | Status |
| --- | --- | --- |
| 1 | Scaffold, synthetic dataset, SHA-256 manifest, integrity screen, tests | **Complete** |
| 2 | Signature scanner and carving engine (3 storage conditions) | **Complete** |
| 3 | Recovery pipeline, content validation, ground-truth matching | **Complete** (folded into Stage 2) |
| 4 | Precision / recall measurement and results dashboard | **Complete** (folded into Stage 2) |
| 5 | Failure analysis, limitations, final report | Not started |

> **Nothing in this repository fabricates a metric.** Every number on the
> **Results** page is computed from the ground-truth map that was written
> *before* carving and from the baseline manifest. The carver never sees the
> ground truth; the measurement layer never guesses.

### Measured results (Stage 2)

The table below is produced by `src.experiments.run_all_conditions()` on the
committed dataset. It is reproduced by pressing **Run carving experiments** on
the **Carve** page.

| Condition | Detection P / R | Validated recoveries | Mean byte coverage | Data completeness |
| --- | --- | --- | --- | --- |
| Contiguous | 0.78 / 1.00 | 3 of 8 files | 100 % | 100 % |
| Fragmented | 0.78 / 1.00 | 0 of 8 files | 34 % | 100 % |
| Partially overwritten | 0.78 / 1.00 | 0 of 8 files | 75 % | 75 % |

Reading the table:

* **Detection recall is 1.00 in every condition.** Every signature that the
  ground truth places in an image is found, including the JPEG header embedded
  at offset 1024 inside `synthetic_container_01.bin`.
* **Detection precision is 0.78** because two decoy signatures are planted in
  the filler of every image on purpose. The filler itself contains no
  signature at all, so the false positives are designed, not accidental.
* **Only three files are ever recovered byte for byte.** Those are the three
  fixtures that carry their own terminator (`FFD9`, `%%EOF`, `PK 05 06`). The
  five Stage 1 fixtures start with a real signature but contain no terminator,
  so a carving engine can detect them but cannot delimit them — the carve
  either runs into the next file (**over-carving**) or stops at the end of the
  stream (**truncation**). This is the central finding of Stage 2.
* **Fragmentation destroys recovery.** All data is still present
  (completeness 100 %), but the bytes are no longer contiguous, so the
  signature-delimited extent no longer matches the original and only about a
  third of the bytes survive a naive byte-by-byte comparison.
* **Overwriting destroys recovery and shows up in the completeness measure.**
  25 % of every original was replaced, so completeness drops to 75 % and the
  mean byte coverage drops to the same value.

---

## 2. Forensic and integrity rules applied

1. **Synthetic data only.** Every fixture is generated locally by `src/fixtures.py`
   from a fixed seed. No real device, disk image, account or third-party data is
   involved, and no destructive disk operation is performed.
2. **Separation of concerns.** Ground truth (`data/originals/`), experimental inputs
   (`data/experiments/`) and recovery output (`data/recovered/`) live in separate
   directories and are never mixed.
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

---

## 3. Project structure

```
TraceByte/
├── app.py                  # Streamlit entry point (run this)
├── app/
│   ├── branding.py         # FileCarveLab branding and shared UI copy
│   ├── state.py            # cached, read-only data access for the dashboard
│   └── views/
│       ├── home.py         # Overview, guardrails, roadmap
│       ├── dataset.py      # Dataset initialisation + baseline manifest
│       ├── integrity.py    # SHA-256 verification against the baseline
│       ├── carve.py        # Stage 2: build images, run the carving engine
│       ├── results.py      # Stage 2: the measured accuracy of the engine
│       └── log.py          # Experiment log viewer
├── src/
│   ├── paths.py            # Canonical project paths
│   ├── hashing.py          # Chunked SHA-256 utility
│   ├── manifest.py         # Immutable baseline manifest
│   ├── fixtures.py         # Deterministic synthetic fixtures + initialisation
│   ├── integrity.py        # Verification, mismatch/missing/unregistered detection
│   ├── experiment_log.py   # Append-only JSON Lines provenance log
│   ├── signatures.py       # Stage 2: signature registry, scanner, extent policies
│   ├── conditions.py       # Stage 2: the three controlled storage conditions
│   ├── carver.py           # Stage 2: the carving engine and its provenance
│   ├── metrics.py          # Stage 2: detection / recovery / validation scoring
│   └── experiments.py      # Stage 2: build -> carve -> measure -> log
├── tests/                  # pytest suite (145 tests)
├── data/
│   ├── originals/          # Ground truth: fixtures + manifest.json  (tracked)
│   ├── experiments/        # Experimental inputs + measurements       (ignored)
│   └── recovered/          # Carving output                          (ignored)
├── logs/                   # experiment_log.jsonl                     (ignored)
├── reports/                # Generated report artefacts              (ignored)
├── .streamlit/config.toml  # Dashboard theme
├── requirements.txt
├── pyproject.toml
└── .gitignore
```

`data/originals/` is **tracked in git on purpose**: it holds the ground truth and the
baseline manifest, so a reviewer can independently re-verify every hash. The other
three directories hold regenerable data and are ignored.

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

### 4.3 Install the dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4.4 Run the dashboard

```powershell
python -m streamlit run app.py
```

The dashboard opens at <http://localhost:8501>. Useful alternatives:

```powershell
python -m streamlit run app.py --server.port 8502   # different port
python -m streamlit run app.py --server.headless true
```

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

### 4.6 Deactivate the environment (when finished)

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
3. **Integrity** → compares every original with the baseline and reports
   **MATCH**, **MISMATCH**, **MISSING** or **UNREGISTERED**.
   * The **Run detection self-test** button copies one original into a temporary
     directory, flips a single byte in the *copy* and re-runs the verification. The
     original is never modified. This demonstrates that a modified copy is detected
     as changed.
4. **Carve** → the Stage 2 engine.
   * Lists the supported signatures (magic bytes, extension, end marker and the
     validation strategy that is applied to each of them).
   * **Run carving experiments** builds the three images, carves them, measures the
     result and appends an `experiment_completed` event to the experiment log.
   * Writes to `data/experiments/<experiment>/` (image, ground truth, carve report,
     metrics) and `data/recovered/<experiment>/` (the carved candidates).
5. **Results** → the measurements, read back from the artefacts.
   * A comparison table across the three conditions, a per-file table that separates
     * *detected*, *carved* and *validated*, the per-signature breakdown and the list
     of false positives. The metrics can be downloaded as JSON.
6. **Experiment log** — the append-only provenance record, newest first.

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

The first five fixtures carry a **start** signature but no **terminator**, so a
carving engine can detect them but cannot delimit them. The last three were added in
Stage 2 and end with the terminator of their format, which is what makes a
byte-exact recovery possible in the contiguous condition. They are the difference
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

Every run writes `data/experiments/<experiment>/` (`image.bin`,
`ground_truth.json`, `carve_results.json`, `metrics.json`) and
`data/recovered/<experiment>/`, and appends an `experiment_completed` event to
the experiment log.

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

## 9. Known limitations after Stage 2

* **The fixtures are not real files.** They carry realistic signatures and, for the
  three `synthetic_len_*` fixtures, a realistic terminator, but no valid structure.
  They are measured against as *signature-shaped placeholders*, not against genuine
  JPEG/PDF/ZIP content. Stage 5 must decide how real-but-public sample files (for
  example files published by standard bodies under an open licence) are added, if at
  all.
* **The signature set is small.** JPEG, PDF and ZIP only. No compound containers
  (e.g. a DOCX inside a ZIP) and no fragmented-signature handling.
* **The extent policies are simple.** A candidate ends at the format's terminator, at
  the next signature or at the end of the stream. There is no size-based carving, no
  carving from the end of the file backwards and no format-aware header repair.
* **Byte coverage is a naive measure.** It assumes that the file's bytes follow the
  signature contiguously. Under fragmentation that assumption is wrong by
  construction, so the coverage figure is a lower bound, not a recovery rate.
* **The false positives are designed, not observed.** Two decoy signatures are planted
  in the filler of every image so that the false-positive count is reproducible. Real
  false positives come from chance coincidences in unallocated space, and the filler
  is deliberately kept free of signatures to keep the experiment under control.
* **Baseline re-baselining is a library API only.** `rebaseline_entry()` is tested but
  deliberately not exposed in the dashboard, to keep the operator from changing a
  baseline by accident.
* **The experiment log is append-only but not tamper-evident.** It is a plain JSON
  Lines file. A cryptographic chain over the log entries is planned as part of the
  reproducibility checks in Stage 5.
* **The manifest is not signed.** The baseline is trusted because it lives in version
  control; a detached signature over `manifest.json` is a candidate improvement.

---

## 10. Reproducibility checklist

* [x] Deterministic fixture generation (fixed seed, no RNG, no timestamps in content)
* [x] SHA-256 baseline for every original, recorded in `manifest.json`
* [x] Originals preserved byte for byte on re-initialisation
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
* [ ] Failure analysis and final report (Stage 5)

---

## 11. Licence and attribution

Coursework project for the Digital Forensics PBL (DF-PBL-016). All data produced by
this repository is synthetic and generated by the code in `src/`.
