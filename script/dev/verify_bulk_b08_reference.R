#!/usr/bin/env Rscript

# Rebuild the reference fit from frozen input counts and sample metadata.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2L, !file.exists(args[[2L]]))
spec_path <- normalizePath(args[[1L]], mustWork = TRUE)
spec <- jsonlite::fromJSON(spec_path, simplifyVector = FALSE)
options(digits = 17L, warn = 1L)
library(DESeq2)

input_path <- function(name) file.path(dirname(spec_path), name)
sha256 <- function(path) {
  checksum <- sub(" .*", "", system2("sha256sum", shQuote(path), stdout = TRUE))
  stopifnot(length(checksum) == 1L, grepl("^[0-9a-f]{64}$", checksum))
  checksum
}
input_sha256 <- list(spec = sha256(spec_path), counts = sha256(input_path(spec$counts)),
                     metadata = sha256(input_path(spec$metadata)))
stopifnot(identical(input_sha256$counts, spec$counts_sha256),
          identical(input_sha256$metadata, spec$metadata_sha256))

read_input <- function(name, sep) {
  read.table(input_path(name), sep = sep, header = TRUE, quote = '"',
             comment.char = "", check.names = FALSE, colClasses = "character",
             na.strings = character())
}

count_table <- read_input(spec$counts, spec$separator)
metadata <- read_input(spec$metadata, spec$separator)
features <- count_table[[1L]]
feature_column <- if (is.null(spec$feature_column)) "feature_id" else spec$feature_column
stopifnot(identical(names(count_table)[[1L]], feature_column),
          length(features) > 0L, !anyNA(features), all(nzchar(features)),
          !anyDuplicated(features), !anyDuplicated(names(count_table)),
          !anyNA(metadata$sample_id), !anyDuplicated(metadata$sample_id))
samples <- unlist(spec$samples, use.names = FALSE)
stopifnot(length(samples) > 1L, !anyDuplicated(samples),
          all(samples %in% names(count_table)[-1L]), all(samples %in% metadata$sample_id))
metadata <- metadata[match(samples, metadata$sample_id), , drop = FALSE]
selected_counts <- as.matrix(count_table[samples])
stopifnot(all(grepl("^[0-9]+$", selected_counts)))
counts <- matrix(as.numeric(selected_counts), nrow = length(features),
                 dimnames = list(features, samples))
stopifnot(all(is.finite(counts)), all(counts <= .Machine$integer.max))
storage.mode(counts) <- "integer"

design_data <- data.frame(row.names = samples)
for (term in spec$terms) {
  values <- metadata[[term$field]]
  levels <- unlist(term$levels, use.names = FALSE)
  stopifnot(length(values) == length(samples), setequal(values, levels))
  design_data[[term$name]] <- factor(values, levels = levels)
}
design <- reformulate(vapply(spec$terms, function(term) term$name, character(1)))
matrix <- model.matrix(design, design_data)
rank <- qr(matrix)$rank
stopifnot(rank == ncol(matrix), nrow(matrix) > rank)
minimum_samples <- min(table(design_data$condition))
total <- rowSums(counts) >= spec$minimum_total_counts
expressed <- rowSums(counts >= spec$minimum_sample_counts) >= minimum_samples
retained <- total & expressed
reason <- ifelse(!total, "minimum_total_counts", ifelse(!expressed, "minimum_sample_counts", ""))
stopifnot(any(retained), all(colSums(counts[retained, , drop = FALSE]) > 0))

dest <- args[[2L]]
dir.create(dest, recursive = TRUE)
write_tsv <- function(value, filename) {
  write.table(value, file.path(dest, filename), sep = "\t", row.names = FALSE,
              quote = FALSE, na = "NA", fileEncoding = "UTF-8")
}
dds <- DESeqDataSetFromMatrix(countData = counts[retained, , drop = FALSE],
                              colData = design_data, design = design)
dds <- DESeq(dds, test = "Wald", fitType = "parametric", sfType = spec$size_factor_method,
             betaPrior = FALSE, minReplicatesForReplace = Inf, minmu = 0.5, parallel = FALSE)

bh <- function(values) {
  selected <- is.finite(values)
  adjusted <- rep(NA_real_, length(values))
  adjusted[selected] <- p.adjust(values[selected], method = "BH")
  adjusted
}
expand <- function(values) {
  expanded <- rep(NA, length(features))
  expanded[retained] <- values
  expanded
}
filter_thresholds <- list()
tables <- lapply(spec$contrasts, function(item) {
  contrast <- c("condition", item$numerator, item$denominator)
  result <- results(dds, contrast = contrast, alpha = spec$alpha, independentFiltering = TRUE)
  raw <- results(dds, contrast = contrast, alpha = spec$alpha, independentFiltering = FALSE,
                 cooksCutoff = FALSE)
  stopifnot(identical(rownames(result), features[retained]))
  filter_thresholds[[item$id]] <<- as.numeric(metadata(result)$filterThreshold)
  data.frame(contrast_id = item$id, feature_id = features, numerator = item$numerator,
             denominator = item$denominator, tested = retained, exclusion_reason = reason,
             base_mean = expand(result$baseMean), effect_value = expand(result$log2FoldChange),
             lfc_se = expand(result$lfcSE), wald_statistic = expand(result$stat),
             p_value = expand(result$pvalue), q_within_contrast = expand(bh(result$pvalue)),
             original_method_adjustment = expand(result$padj), p_without_cooks = expand(raw$pvalue),
             beta_converged = expand(mcols(dds)$betaConv), dispersion = expand(dispersions(dds)))
})
full <- do.call(rbind, tables)
full$q_global_family <- bh(full$p_value)
write_tsv(full, "comparison_results.tsv")
write_tsv(data.frame(sample_id = samples, factor = sizeFactors(dds)), "size_factors.tsv")
write_tsv(data.frame(sample_id = samples, matrix, check.names = FALSE), "design_matrix.tsv")
write_tsv(data.frame(sample_id = samples, design_data), "model_sample_metadata.tsv")
writeLines(capture.output(sessionInfo()), file.path(dest, "session-info.txt"), useBytes = TRUE)
outputs <- c("comparison_results.tsv", "size_factors.tsv", "design_matrix.tsv",
             "model_sample_metadata.tsv", "session-info.txt")
output_sha256 <- setNames(lapply(file.path(dest, outputs), sha256), outputs)
jsonlite::write_json(list(r_version = as.character(getRversion()),
                          deseq2_version = as.character(packageVersion("DESeq2")),
                          design = format(design), rank = rank, residual_df = nrow(matrix) - rank,
                          fitted = sum(retained), input_features = nrow(counts),
                          input_samples = samples, minimum_expressing_samples = as.integer(minimum_samples),
                          fit_type = attr(dispersionFunction(dds), "fitType"),
                          filter_thresholds = filter_thresholds, input_sha256 = input_sha256,
                          output_sha256 = output_sha256),
                     file.path(dest, "diagnostics.json"), auto_unbox = TRUE, pretty = TRUE)
