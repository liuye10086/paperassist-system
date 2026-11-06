# Loaded before isolation, from fixed application code covered by code_digest.
suppressPackageStartupMessages({
    library(Matrix)
    library(SingleCellExperiment)
    library(BiocParallel)
    library(scDblFinder)
    library(decontX)
    library(harmony)
    library(SingleR)
})
BiocParallel::register(BiocParallel::SerialParam(progressbar=FALSE))
options(mc.cores=1L, Ncpus=1L)
if (requireNamespace("RcppParallel", quietly=TRUE)) RcppParallel::setThreadOptions(numThreads=1L)

pa_singler_fit <- function(mat, reference, labels, seed) {
    set.seed(seed)
    SingleR::SingleR(test=mat,ref=reference,labels=labels,genes="de",de.method="classic",
        quantile=.8,fine.tune=TRUE,tune.thresh=.05,prune=TRUE,
        BPPARAM=BiocParallel::SerialParam(progressbar=FALSE),BNPARAM=BiocNeighbors::KmknnParam())
}

pa_singler_warmup <- function() {
    # Trusted fixed synthetic bytes only; no user input or reference is opened.
    set.seed(17)
    ref <- matrix(rpois(80L*12L,2),nrow=80L,dimnames=list(paste0("warmgene",1:80),paste0("ref",1:12)))
    ref[1:35,1:6] <- ref[1:35,1:6]+12
    ref[36:70,7:12] <- ref[36:70,7:12]+12
    ref <- log1p(ref)
    test <- as(ref[,c(1,2,8,9)],"dgCMatrix")
    fit <- pa_singler_fit(test,ref,rep(c("A","B"),each=6),17L)
    nrow(fit)==4L && all(is.finite(fit$scores))
}

pa_singler <- function(x,i,p,genes,cells,reference_path,label_level,seed) {
    logs <- character()
    con <- textConnection("logs","w",local=TRUE)
    sink(con);sink(con,type="message")
    on.exit({sink(type="message");sink();close(con)},add=TRUE)
    tryCatch(withCallingHandlers({
        mat <- methods::new("dgCMatrix",x=x,i=i,p=p,Dim=as.integer(c(length(genes),length(cells))),Dimnames=list(genes,cells))
        methods::validObject(mat)
        reference <- readRDS(reference_path)
        stopifnot(is.matrix(reference$logcounts),is.numeric(reference$logcounts),all(is.finite(reference$logcounts)),
            !anyDuplicated(rownames(reference$logcounts)))
        labels <- reference[[paste0("labels_",label_level)]]
        stopifnot(length(labels)==ncol(reference$logcounts),!anyNA(labels),length(unique(labels))>=2L)
        common <- genes[genes %in% rownames(reference$logcounts)]
        if (length(common)<50L) return(list(status="not_computable",reason="insufficient_common_genes",logs=logs))
        mat <- mat[common,,drop=FALSE]
        if (any(Matrix::colSums(mat)<=0)) return(list(status="not_computable",reason="no_expression_on_common_genes",logs=logs))
        ref <- reference$logcounts[common,,drop=FALSE]
        fit <- pa_singler_fit(mat,ref,labels,seed)
        pruned <- as.character(fit$pruned.labels);pruned[is.na(pruned)] <- ""
        cat("SingleR 2.8.0 classic; common_genes=",length(common),"; reference_samples=",ncol(ref),"; SerialParam\n",sep="")
        list(status="completed",reason="",logs=logs,cells=rownames(fit),common_genes=common,
            labels=as.character(fit$labels),pruned=pruned,scores=fit$scores,score_labels=colnames(fit$scores),
            delta_next=fit$delta.next,delta_median=SingleR::getDeltaFromMedian(fit))
    },warning=function(w){cat("warning: ",conditionMessage(w),"\n",sep="");invokeRestart("muffleWarning")}),
    error=function(e) list(status="failed",reason="tool_failed",logs=c(logs,paste0("error: ",conditionMessage(e)))))
}

pa_run <- function(x, i, p, genes, cells, tool, seed, expected_rate=NULL) {
    logs <- character()
    con <- textConnection("logs", "w", local=TRUE)
    sink(con)
    sink(con, type="message")
    on.exit({sink(type="message"); sink(); close(con)}, add=TRUE)
    tryCatch(withCallingHandlers({
        mat <- methods::new("dgCMatrix", x=x, i=i, p=p,
            Dim=as.integer(c(length(genes), length(cells))), Dimnames=list(genes,cells))
        methods::validObject(mat)
        if (ncol(mat)<4L || nrow(mat)<3L) return(list(status="not_computable", reason="insufficient_cells_or_genes",logs=logs))
        set.seed(seed)
        if (tool=="scdblfinder") {
            dims <- as.integer(min(20L,ncol(mat)-1L,nrow(mat)-1L))
            sce <- scDblFinder::scDblFinder(mat, dbr=expected_rate, clusters=FALSE,
                dims=dims, includePCs=min(19L,dims), nfeatures=min(1352L,nrow(mat)),
                verbose=TRUE, BPPARAM=BiocParallel::SerialParam(progressbar=FALSE))
            return(list(status="completed",reason="",logs=logs,genes=rownames(sce),cells=colnames(sce),
                score=sce$scDblFinder.score,prediction=as.character(sce$scDblFinder.class)))
        }
        if (tool!="decontx") stop("unsupported_fixed_tool")
        # decontX's native model uses per-library automatic broad-population
        # initialization; its pinned version sets UMAP n_threads=1 internally.
        fit <- decontX::decontX(mat, seed=seed, verbose=TRUE)
        if (length(unique(fit$z))<2L) return(list(status="not_computable",reason="insufficient_cell_populations",logs=logs))
        corrected <- as(fit$decontXcounts,"dgCMatrix")
        list(status="completed",reason="",logs=logs,genes=rownames(corrected),cells=colnames(corrected),
            contamination=fit$contamination,x=corrected@x,i=corrected@i,p=corrected@p)
    }, warning=function(w) {cat("warning: ",conditionMessage(w),"\n",sep="");invokeRestart("muffleWarning")}),
    error=function(e) {
        text <- conditionMessage(e)
        reason <- if (grepl("only one cluster|At least 2 genes|not enough|too few|cannot find more nearest",text,ignore.case=TRUE)) "insufficient_model_conditions" else "tool_failed"
        list(status=if (reason=="tool_failed") "failed" else "not_computable",reason=reason,logs=c(logs,paste0("error: ",text)))
    })
}

pa_harmony <- function(values, cells, batches, dimensions, seed, theta, ridge, max_iter) {
    logs <- character()
    con <- textConnection("logs", "w", local=TRUE)
    sink(con); sink(con, type="message")
    on.exit({sink(type="message"); sink(); close(con)}, add=TRUE)
    tryCatch(withCallingHandlers({
        pcs <- matrix(values,nrow=length(cells),ncol=dimensions,byrow=TRUE,
            dimnames=list(cells,paste0("PC",seq_len(dimensions))))
        metadata <- data.frame(batch=batches,row.names=cells)
        stopifnot(identical(rownames(pcs),rownames(metadata)),all(is.finite(pcs)))
        set.seed(seed)
        corrected <- harmony::RunHarmony(data_mat=pcs,meta_data=metadata,vars_use="batch",
            theta=theta,sigma=.1,lambda=ridge,max_iter=as.integer(max_iter),
            early_stop=TRUE,ncores=1L,return_object=FALSE,verbose=TRUE)
        stopifnot(identical(dim(corrected),dim(pcs)),identical(rownames(corrected),cells),all(is.finite(corrected)))
        list(status="completed",reason="",logs=logs,cells=rownames(corrected),embedding=corrected)
    },warning=function(w){cat("warning: ",conditionMessage(w),"\n",sep="");invokeRestart("muffleWarning")}),
    error=function(e) list(status="failed",reason="harmony_failed",logs=c(logs,paste0("error: ",conditionMessage(e)))))
}
