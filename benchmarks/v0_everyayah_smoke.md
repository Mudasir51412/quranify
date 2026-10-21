# Benchmark v0 — EveryAyah smoke test
Model: `basharalrfooh/whisper-small-quran` via transformers on CPU. n=10.
**WER raw 56.5% · CER raw 8.4% · WER normalized 12.5% · CER normalized 1.3%**

⚠️ In-distribution smoke benchmark (EveryAyah = model's training distribution). Not a held-out generalization estimate.

| Ayah | WER (norm) | CER (norm) | Diacritics in output | Pipeline | Skips | Harakat errs |
|---|---|---|---|---|---|---|
| 112:1 | 0.00 | 0.00 | True | ok | [] | 0 |
| 112:2 | 0.00 | 0.00 | True | ok | [] | 0 |
| 112:3 | 0.00 | 0.00 | True | ok | [] | 0 |
| 112:4 | 0.00 | 0.00 | True | ok | [] | 0 |
| 113:1 | 0.00 | 0.00 | True | ok | [] | 0 |
| 114:1 | 0.00 | 0.00 | True | ok | [] | 0 |
| 114:6 | 0.67 | 0.00 | True | ok | [] | 0 |
| 1:1 | 0.00 | 0.00 | True | ok | [] | 0 |
| 1:2 | 0.25 | 0.06 | True | ok | [] | 0 |
| 108:1 | 0.33 | 0.07 | True | ok | [] | 0 |
