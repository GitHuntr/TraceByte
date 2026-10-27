# TraceByte — Demonstration and Viva Guide

**Assignment:** Signature Carving Evaluation · **Reference:** DF-PBL-016  
**SAP ID:** 500119665 · **Target duration:** 6–7 minutes including demonstration

Use this guide as a speaking outline. Verify the saved run and test output before
recording. The course asks for a 5–8 minute response/demo video; this outline
targets that range. Do not present synthetic results as real-case performance.

## Suggested timing

| Time | Section |
|---|---|
| 0:00–0:35 | Title and assignment objective |
| 0:35–1:20 | Problem and scope |
| 1:20–2:15 | Method and integrity controls |
| 2:15–3:00 | Dashboard demonstration |
| 3:00–4:25 | Results and interpretation |
| 4:25–5:30 | Failure analysis and limitations |
| 5:30–6:20 | Conclusion and reproducibility |
| 6:20–7:00 | Questions / closing |

## 1. Objective (0:00–0:35)

“Hello. I am presenting TraceByte for DF-PBL-016, Signature Carving Evaluation.
The project asks how well a signature-based carver detects and recovers files
under contiguous, fragmented, and partially overwritten conditions. My evidence
is a controlled synthetic experiment, with real-evidence scanning available as a
separate exploratory workflow.”

## 2. Problem and scope (0:35–1:20)

“A file header can identify a possible format, but a signature hit does not prove
that a complete file was recovered. The candidate may be truncated, overlong,
fragmented, overwritten, or simply contain the same bytes by coincidence.
TraceByte separates detection from extraction and exact SHA-256 comparison.

“The benchmark uses eight deterministic synthetic fixtures. They contain
signature-shaped data, not fully standards-conformant JPEG, PDF, or ZIP files.
Therefore the benchmark evaluates the implemented logic on controlled inputs;
it does not certify real-world recovery.”

## 3. Method and integrity controls (1:20–2:15)

“The baseline manifest records the synthetic originals and their SHA-256 values.
For each run, the system creates separate images and ground-truth maps for all
three conditions. The carver scans the images; the evaluation layer compares the
result with the saved ground truth. Each run has its own directory and metrics.

“The application also separates user-selected evidence copies from synthetic
experiment data. The intake records a hash and scans a stored copy. Real scans do
not have known labels, so I do not report synthetic precision or recall for them.”

## 4. Dashboard demonstration (2:15–3:00)

Show these screens in sequence:

1. **Overview:** identify the local TraceByte workbench and project scope.
2. **Dataset:** show the fixture inventory and baseline integrity state.
3. **Carving lab:** select or run a three-condition experiment; note the run ID.
4. **Results:** select `run-20261027T141506Z-489d1acf` and show the metric table.
5. **Real evidence:** explain that this is a separate intake and candidate-scan flow;
   never claim its signature hits are confirmed recovered files.
6. **Activity log:** point out that application actions create local provenance
   events.

If recording after generating a new run, present the values from that new run's
`metrics.json`; do not combine values from multiple run IDs.

## 5. Results (3:00–4:25)

“In saved run `run-20261027T141506Z-489d1acf`, detection precision was 0.7778,
recall was 1.0, and F1 was 0.875 in each condition. These detection scores are
7 true positives, 2 false positives, and 0 false negatives against seven
ground-truth signature instances.

“Exact SHA-256 matches were 3 of 8 fixtures in the contiguous condition, and 0
of 8 in both fragmented and partially overwritten conditions. Mean byte coverage
was 100 percent, 33.64 percent, and 75.15 percent respectively. Data completeness
was 100 percent, 100 percent, and 75.02 percent.

“So, in this test, detecting the expected signatures did not guarantee exact
recovery. The contiguous condition captured all expected bytes on average but
some candidates included extra bytes and failed hash comparison. Under
fragmentation, all source bytes were represented somewhere in the image, while
the linear extraction recovered only about one third on average. Overwriting
reduced the bytes available in this generated image.”

## 6. Failure analysis and limitations (4:25–5:30)

“The key failure modes are extent selection and non-contiguous data. A file with
no usable end boundary can be over-carved or continue to end of stream. A linear
carver does not reassemble fragments. An overwritten fixture cannot match the
original hash if bytes changed. The two false-positive candidates demonstrate
that a signature match is only a lead.

“These findings are specific to this small synthetic dataset and the implemented
signature and extent policies. The fixtures are not parser-validated files; no
real disk acquisition, file-system recovery, E01 container parsing, or fragmented
file reassembly is implemented. Coverage is a project diagnostic, not a universal
recovery metric. A next evaluation should add licensed real-format test files,
independent format parsers, more placements, and a comparison with established
carving tools.”

## 7. Conclusion and reproducibility (5:30–6:20)

“TraceByte implements the assigned controlled evaluation and reports detection,
candidate extraction, and exact matching separately. For the saved run, recall
was high while exact recovery depended strongly on storage condition. This
supports a limited conclusion about this implementation and these generated
inputs, not a claim about every forensic tool or real case.

“The run artifacts, ground-truth maps, candidate records, and metrics are saved
under the run ID shown on screen. The project also includes an automated test
suite, which I can reproduce with `python -m pytest -q`. Thank you.”

## Viva questions to prepare

### Why is detection precision below 1?

Two candidates in each saved image do not correspond to a ground-truth file
starting at those offsets. Thus 7 of 9 detections were true positives, giving
precision 7/9 = 0.7778. This is only the measured result for these generated
images; it is not a rate estimate for real media.

### Why can coverage be 100% when exact recovery fails?

Coverage records whether expected bytes are represented in the candidate. A
candidate can contain all expected bytes and extra bytes. The extra bytes alter
the candidate SHA-256, so it is not an exact match.

### What is the difference between data completeness and byte coverage?

Completeness is measured against bytes present in the condition image. Coverage
is measured against bytes included in the carver's candidate. In the fragmented
condition, all original bytes are present somewhere (100% completeness), but the
linear candidate contains only 33.64% coverage on average.

### Does a SHA-256 match prove the file is valid?

It proves byte equality with the corresponding known synthetic fixture, assuming
the baseline is correct. It does not establish that the fixture is a valid
real-world file or prove anything about a different candidate without a trusted
reference.

### What does the real-evidence feature establish?

It stores and hashes a local copy, scans supported signatures, and records
candidates. Without known ground truth and independent format validation, a
signature hit is not proof of a complete or valid recovered file.

### How would you improve the experiment?

Use a larger, documented corpus of parser-valid files; vary layout and overwrite
locations across repeated runs; include independent carvers and format parsers;
report per-format results and uncertainty; and make provenance tamper-evident.

## Attribution and disclosure

The project references Garfinkel's discussion of contiguous and fragmented
carving and the NIST CFTT tool-testing program. AI assistance was used to review
project files and revise project documentation. Verify the values against saved
artifacts and follow the course's required disclosure format before submission.
