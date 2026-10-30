# Bio engine transport v1

Interpreter: `/opt/paperassist-bio/bin/python -I -B /app/app/adapters/bio_engine/worker.py PARENT_PID`.
The child emits `READY\n`, reads a four-byte network-order unsigned JSON byte length,
then exactly that many UTF-8 bytes and EOF. Payload/output JSON maximum is 2 MiB.
The parent supplies an empty environment, enforces warmup (180 s), compute wall
time (1200 s), RSS (2 GiB), container resources and process termination. Child
sets numeric threads to 1, CPU 900 s, address space 3 GiB, file size 256 MiB,
file descriptor 1024, no subprocess/network, read-only trusted Python/font roots,
and per-file Landlock grants. Only the task output directory is writable.
Trusted synthetic numeric/JIT/font warmup precedes reading any customer member.
Input groups are bounded before warmup/file access: raw <=256, processed <=256,
annotation <=2, import_v2 files <=256, at most 514 declared files in total.
Each distinct input path/inode is granted separately and pinned for the attempt;
duplicate path/inode pairs do not consume extra grants. Distinct hardlink paths
stay pinned separately for Windows bind-mount Landlock compatibility. The fixed descriptor
budget covers all 514 files, four runtime/output grants, and numeric I/O.

Payload:

```json
{"mode":"qc","raw":{"manifest":{},"members":{"matrix_data":{"path":"/fixed/input/leaf","sha256":"...","size_bytes":1,"role":"matrix_data","format":"npy"}}},"config":{},"identity":{"raw_source":{},"recipe_version_id":"...","environment_digest":"...","code_digest":"..."},"output_directory":"/fixed/output"}
```

`raw.manifest` is the immutable B01 manifest (`input_shape.features/observations`).
Required members: `matrix_data`, `matrix_indices`, `matrix_indptr` (observations ×
features CSR NPY), `features_index` (`feature_ids/feature_symbols/feature_types`),
`barcodes_index` (`barcodes`). Optional `positions_index` is the unchanged B01
position-row list. Optional `observation_map_index` is `{schema_version:1,rows:[
{barcode,sample_id:{status,value},section:{status,value},donor:{status,value},
batch:{status,value},group:{status,value}}]}`. Only `known` values are used;
unknown mappings do not create donors or independent replicates.

Compute params: `in_tissue_only`, `min_counts`, `min_genes`, `min_spots`,
`exclude_barcodes`, `mt_rule`, `hvg_count`, `resolution` (default 0.5),
`marker_top_n`, `output_language` (`en` or `zh-CN`). Defaults are target_sum=10000,
pca_components=30, neighbors=15, seed=0; bounded user values are executed and
recorded (target_sum 1..1e6, PCA 2..100, neighbors 2..100, seed 0..2^31-1,
HVG 3..10000, marker_top_n 1..100). Effective dimensions are capped by data.
Optional max_counts and confirmed-rule max_mt_fraction (0..1) filter explicitly.

`figure` additionally supplies `processed:{manifest,members}` including
`processed` H5AD and `markers_top` TSV. `config.kind` is `qc`, `pca`, `umap`,
`marker_dotplot`, `marker_heatmap`, `spatial_cluster`, `spatial_gene`, `annotation`;
`gene_ids` always contain stable IDs. `layer=counts|normalized|log1p`,
`palette=viridis|magma|tab20`, `title`, `vmin/vmax`, `width/height` pixels,
`dpi`, `output_language` are frozen in figure manifests. Annotation is
`{labels,members:{geometry:{path,sha256,size_bytes},assignments:{...}}}`.
Geometry and assignments follow the backend fullres region schema. `figure`
reads the fixed processed object and never recomputes normalization/clusters.
`panel` freezes the actual graphic identity: QC accepts distribution/scatter/
violin/mitochondrial/sample_id/section/batch (default=distribution); PCA accepts
scores/variance (default=scores); UMAP accepts scores (default=scores); other
kinds accept default. Every default figure stores explicit kind/panel. Changing
only a title regenerates that same panel and preserves its plotting data.
`color_by=cluster|sample_id|section|batch` applies to PCA/UMAP scores. Continuous
vmin/vmax apply only to spatial_gene and marker figures. Marker colors always
mean log1p; marker dot area always reflects counts>0 detection fraction.
Categorical tab20 requests use effective_palette=paperassist_golden_angle_hsl_v1:
cluster ID i (0..49) maps to HSL(h=(i*137.50776405003785)%360,s=.65,l=.52),
with colorsys.hls_to_rgb(h/360,.52,.65), alpha=1. Spatial/PCA/UMAP share this
mapping independently of the number or subset of clusters. Viridis/magma
cluster colors use fixed i/49 sampling. Non-numeric labels use sorted label-ID
ordinals; unknown is #777777. Plot-data records actual category_colors (or
annotation label_colors); figure manifests record effective_palette.
Spatial image selection skips preserved auxiliary alignment/detected-tissue
previews without calibration. Only a tissue_image member with an explicit
tissue_hires_scalef or tissue_lowres_scalef field becomes the coordinate
background; no scale is guessed for other images.

`h5_check` receives a 10x member selected by `h5_member_key`, and optional
`compare_alternate:true` with B01 canonical CSR members for exhaustive comparison.
Unsupported HDF5 schemas, links, vlen strings, external/virtual data, unknown
filters or allocations beyond limits fail closed.

`import_v2` takes `{mode,files:[{id,filename,path,sha256,size_bytes,role}],
matrix_representation:mtx|10x_h5,compare_alternate:boolean,settings:BioLimits,
identity,output_directory}`. It reuses unchanged B01 unpack/spatial validation,
but bounded-reads 10x H5 and canonicalizes duplicate/zero MTX coordinates.
All original components must identify at most one GSM before role relabeling.
Selected and alternate sources, exact member hashes, full sparse comparison,
and explicit derived MTX/TSV exports are recorded. Original H5/MTX bytes remain
preserved sources; derived exports use role=derived_representation. Its result
also contains parser_version=geo_visium_import_v2, n_features, n_observations,
entry_count and the B01-compatible canonical CSR/axis roles. V1 is unchanged.

Success: `{result:{engine_version,status,outputs,manifest,summary,steps,checks,
effective_params}}`. Each output has `key,role,format,path,size_bytes,sha256`.
Parent must independently verify hashes/limits, admit storage, fence publication
and publish transactionally. Failed output directories are never formal results.
Error: `{error:{code,detail?}}`; unexpected errors cannot become an NA result.
Current public errors contain only a stable code; diagnostic traceback remains
on the secret-free child stderr. The outer outputs index supplies the manifest's
own hash; the manifest lists every other leaf without a recursive self-hash.

Tables include `features`, `observations`, `mapping_strata`, and for compute:
`embedding`, `hvg`, `markers`, `markers_top`, `cluster_summary`. NA values in JSON
are null with reason; TSV uses an empty numeric field plus explicit reason.
All tested markers are retained; `markers_top` controls only display.
CSR layers use `{prefix}_data/indices/indptr.npy` and `{prefix}_shape.json`.
H5AD X=log1p, layers counts/normalized, raw index mappings in obs/var,
PCA/UMAP/spatial in obsm, distances/connectivities in obsp. Raw full counts
remain in the original dataset and are not overwritten.
