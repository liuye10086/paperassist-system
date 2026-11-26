---
name: research-report-reading
description: Explain a fixed research report through its principal findings, quality decisions and selected figures.
metadata:
  category: analysis
  version: "1.0.3"
---

Lead with the answer supported by the selected results. Name the comparison or observation, its direction and scale, and the saved table or numbered figure that supports it. Use the abstract for the principal finding and its main qualification. Use the findings section to develop the evidence in order of importance.

Distinguish the source dataset, units actually analysed, and units eligible for inference. Explain a recorded exclusion or quality issue by giving its scope, reason and consequence for the result. In `table_evidence`, Bulk testing limits are examples from the selected comparisons. A model-cohort total uses the stored model inputs and applies to that cohort. A threshold scenario applied to the same result changes selection, not the fitted estimates or the tested population.

Give the exact exclusion facts together in the data-quality discussion. State whether the feature remains measured, why it was excluded and what result is consequently unavailable. Elsewhere, refer to the tested feature set only where that scope changes the interpretation. Keep the abstract, warnings and figure captions focused on the distinct findings and limitations they need to convey.

When reporting an estimate, give its recorded scale and the relevant interval or standard error if available. Keep an adjusted P value tied to its correction scope and give the original magnitude when a threshold changes which features pass. State when information needed to assess precision or robustness is unreported. Distinguish a feature excluded before testing, an uncomputable estimate, and a test whose result missed a threshold.

Connect each numbered figure to the claim it supports and any table needed to interpret it. Use quality plots to explain what can be assessed about the data. A replot presents the saved result within the selected display scope. For trajectories, use saved coverage, pseudotime or lineage weights to explain the pattern as relative ordering in the selected representation. A known selected sample count gives the number of distinct sample labels recorded on selected input cells. By itself it gives no evidence of coverage by sample or replication.

In the design and data section, report any `source_import` library and feature counts as dimensions of the original input before processing. Keep those counts distinct from the cells selected for the trajectory, the sample labels recorded on those cells, and the number of independent biological replicates.

End with the limitations most likely to change the interpretation and a validation step specific to each important gap. Use the supplied evidence to explain implications, keeping the level of inference consistent from the abstract to the figure captions.
