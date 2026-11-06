# Batch 6 pinned original methods

Base: paperassist-single-cell-worker:b5-propeller (R 4.4.3, Bioconductor 3.20).
Algorithms: slingshot 2.14.0 (Artistic-2.0), GENIE3 1.28.0 (GPL >=2),
CellChat 2.2.0.9001 (GPL-3), official source commit
75253cd0c9e68410e6e721a6d3a0419a1d7e358f.
Source checksums are asserted in Dockerfile.topics. Additional compiled source:
princurve 2.1.6, TrajectoryUtils 1.14.0, NMF 0.28, BiocManager 1.30.27.
Conda dependencies preserve the base environment using --freeze-installed;
the exact resulting URLs/hashes are recorded in topics-explicit-spec.txt.

The final multi-stage image copies only the R prefix; compiler toolchain and
source archives remain in the builder. Bundled official CellChat data/ is
removed before final copy. This product does not claim license clearance for
commercial redistribution of the upstream official database (which cites KEGG).
Only the separately curated CC-BY-4.0 human-demo-literature-v1 three-interaction
JSON is enabled. It includes attribution, scope, complex subunits, and a verified
canonical-payload SHA256. It is neither CellChatDB nor a comprehensive catalog.

CellChat consumes externally log-normalized, nonnegative expression. Use the
full-symbol-count normalization denominator before selecting resource genes.
No DE-based hidden LR filtering: computeCommunProb receives explicit LR.use,
triMean, raw.use=TRUE, population.size=FALSE, distance.use=FALSE, sequential plan.
Return all selected source x target x interaction probabilities and p-values.
Original filterCommunication excludes groups with <= min.cells, so bridge
requires each group size strictly greater than min_cells.

GENIE3 receives cells x genes CSR but native input is genes x cells; output is
regulators x targets. Explicit requested regulators retain their input order.
Slingshot preserves native NA pseudotimes, lineage membership weights, root,
lineage cluster sequences, and curve coordinates in input embedding dimensions.
