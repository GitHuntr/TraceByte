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

**Stage 1 of 5 is implemented.** Stage 1 provides the foundation: the project
scaffold, the synthetic dataset, the SHA-256 baseline manifest, the integrity
verification screen, the provenance log and the automated test suite.

| Stage | Scope | Status |
| --- | --- | --- |
| 1 | Scaffold, synthetic dataset, SHA-256 manifest, integrity screen, tests | **Complete** |
| 2 | Signature scanner and carving engine (3 storage conditions) | Not started |
| 3 | Recovery pipeline, content validation, ground-truth matching | Not started |
| 4 | Precision / recall measurement and results dashboard | Not started |
| 5 | Failure analysis, limitations, final report | Not started |

> **Nothing in this repository fabricates a metric.** No precision, recall or
> accuracy number is displayed anywhere, because no carving experiment has been run
> yet. Stage 1 deliberately ships no simulated results.

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
   separately from Stage 2 onwards; a signature hit is never reported as a recovered
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
│       └── log.py          # Experiment log viewer
├── src/
│   ├── paths.py            # Canonical project paths
│   ├── hashing.py          # Chunked SHA-256 utility
│   ├── manifest.py         # Immutable baseline manifest
│   ├── fixtures.py         # Deterministic synthetic fixtures + initialisation
│   ├── integrity.py        # Verification, mismatch/missing/unregistered detection
│   └── experiment_log.py   # Append-only JSON Lines provenance log
├── tests/                  # pytest suite (45 tests)
├── data/
│   ├── originals/          # Ground truth: fixtures + manifest.json  (tracked)
│   ├── experiments/        # Experimental inputs                     (ignored)
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
   * Creates the five synthetic fixtures in `data/originals/`.
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
4. **Experiment log** — the append-only provenance record, newest first.

---

## 6. The synthetic fixture set

| Fixture | Bytes | Signature | Offset | Fully parseable |
| --- | --- | --- | --- | --- |
| `synthetic_photo_01.jpg` | 3200 | `FFD8FF` (JPEG SOI) | 0 | No |
| `synthetic_doc_01.pdf` | 2167 | `%PDF-` | 0 | No |
| `synthetic_archive_01.zip` | 1667 | `504B0304` (PK local header) | 0 | No |
| `synthetic_blob_01.bin` | 4096 | none | n/a | No |
| `synthetic_container_01.bin` | 3142 | `FFD8FF` embedded | 1024 | No |

The byte content is derived from a SHA-256 counter-mode expansion of a fixed seed, so
it is identical on every platform and every Python version: regenerating the dataset
reproduces the same hashes.

`data/originals/FIXTURE_NOTES.md` repeats this table next to the files.

---

## 7. Verification without the dashboard

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

## 8. Known limitations of Stage 1

* **No carving engine yet.** The dashboard cannot carve, recover or validate anything;
  Stage 2 adds the scanner.
* **No metrics yet.** There is no precision/recall table because no experiment has been
  run. This is intentional, not an omission.
* **The fixtures are not real files.** They carry realistic signatures but no valid
  structure, so a carving engine measured against them will be measured against
  signature-shaped placeholders, not against genuine JPEG/PDF/ZIP content. Stage 3
  must decide how real-but-public sample files (for example files published by
  standard bodies under an open licence) are added, if at all.
* **Baseline re-baselining is a library API only.** `rebaseline_entry()` is tested but
  deliberately not exposed in the dashboard, to keep the operator from changing a
  baseline by accident.
* **The experiment log is append-only but not tamper-evident.** It is a plain JSON
  Lines file. A cryptographic chain over the log entries is planned as part of the
  reproducibility checks in Stage 5.
* **The manifest is not signed.** The baseline is trusted because it lives in version
  control; a detached signature over `manifest.json` is a candidate improvement.

---

## 9. Reproducibility checklist

* [x] Deterministic fixture generation (fixed seed, no RNG, no timestamps in content)
* [x] SHA-256 baseline for every original, recorded in `manifest.json`
* [x] Originals preserved byte for byte on re-initialisation
* [x] Baselines never regenerated silently
* [x] Tool versions recorded in the manifest and in every log event
* [x] Append-only experiment log in JSON Lines
* [x] Automated test suite covering hashing, initialisation, preservation and
      change detection
* [ ] Signature scanner and carving engine (Stage 2)
* [ ] Measured precision / recall table (Stage 4)
* [ ] Failure analysis and final report (Stage 5)

---

## 10. Licence and attribution

Coursework project for the Digital Forensics PBL (DF-PBL-016). All data produced by
this repository is synthetic and generated by the code in `src/`.
