# Open EE retrieval expansion

## Added sources

The source manifest now includes two build-time GitHub sources:

- `spatialaudio/signals-and-systems-lecture`
  - Scope: continuous/discrete signals and systems, Fourier analysis, sampling
  - License: CC BY 4.0
- `spatialaudio/digital-signal-processing-lecture`
  - Scope: DSP, DFT/DTFT, recursive/non-recursive filters, filter design
  - License: MIT

The repositories are cloned when the index is built and are ignored by Git.
Their URLs, local paths, licenses, and topics are recorded in
`data/rag/sources.json`.

## Ingestion

- Markdown cells from Jupyter notebooks are extracted; code cells and outputs are skipped.
- Every source receives a stable prefix so same-named files in different repositories
  cannot collide.
- Project-owned course outlines remain a local manifest source.
- Images, audio, notebook outputs, and repository tooling are not indexed.

## Evaluation

Real `BAAI/bge-small-zh-v1.5` embeddings were used with the expanded index:

- Sources: 4
- Documents: 154
- Chunks: 1,746
- Existing hardware set: Hit@5 100%, MRR@5 1.0000
- Existing data-and-algorithm set: Hit@5 100%, MRR@5 1.0000
- New open EE set: Hit@5 100%, MRR@5 0.7333

The open EE set contains five Chinese questions covering signals, sampling,
DFT/DTFT, FIR/IIR, and bilinear-transform filter design. It intentionally checks
cross-language retrieval against English course material.

## Hybrid retrieval finding

Equal-weight vector/BM25 fusion reduced cross-language MRR because Chinese keyword
matches from unrelated Chinese sources could outrank relevant English vector hits.
The production configuration therefore uses weighted RRF:

- vector rank weight: `1.0`
- BM25 rank weight: `0.5`

This preserved the open EE vector baseline MRR of `0.7333`, while retaining exact-term
boosts for queries such as DFT, DTFT, FIR, and IIR.
