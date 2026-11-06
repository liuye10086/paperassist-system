# Build-time only. All inputs have already passed pinned SHA256 verification.
args <- commandArgs(trailingOnly=TRUE)
suppressPackageStartupMessages(library(SummarizedExperiment))
values <- readRDS(file.path(args[1],"monaco-logcounts.rds"))
labels <- readRDS(file.path(args[1],"monaco-coldata.rds"))
hgnc <- read.delim(file.path(args[1],"hgnc_complete_set.txt"),stringsAsFactors=FALSE,
    quote="",comment.char="",check.names=FALSE)
stopifnot(is.matrix(values),is.numeric(values),ncol(values)==114L,nrow(labels)==114L,
    identical(colnames(values),rownames(labels)),all(is.finite(values)),
    length(unique(labels$label.main))==10L,length(unique(labels$label.fine))==29L)
# No alias inference, no many-to-one collapsing: retain exact current approved
# symbols with one unambiguous stable Ensembl gene ID and one reference row.
hgnc <- hgnc[hgnc$status=="Approved" & grepl("^ENSG[0-9]+$",hgnc$ensembl_gene_id),]
hgnc <- hgnc[!duplicated(hgnc$symbol) & !duplicated(hgnc$symbol,fromLast=TRUE),]
idx <- match(rownames(values),hgnc$symbol)
ids <- hgnc$ensembl_gene_id[idx]
keep <- !is.na(ids) & !duplicated(ids) & !duplicated(ids,fromLast=TRUE)
original <- nrow(values)
values <- values[keep,,drop=FALSE]
rownames(values) <- ids[keep]
stopifnot(nrow(values)>10000L,!anyDuplicated(rownames(values)))
dir.create(args[2],recursive=TRUE,showWarnings=FALSE)
saveRDS(list(logcounts=values,labels_main=as.character(labels$label.main),
    labels_fine=as.character(labels$label.fine)),file.path(args[2],"reference.rds"),compress="xz")
jsonlite::write_json(list(gene_ids=rownames(values),samples=ncol(values),genes_before_mapping=original,
    genes_after_mapping=nrow(values),genes_dropped_mapping=original-nrow(values),
    labels_main=sort(unique(labels$label.main)),labels_fine=sort(unique(labels$label.fine))),
    file.path(args[2],"prepared.json"),auto_unbox=TRUE,pretty=TRUE)
