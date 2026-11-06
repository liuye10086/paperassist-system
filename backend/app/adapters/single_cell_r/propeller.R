# Trusted fixed code, loaded before isolation; no files, network or parallelism.
suppressPackageStartupMessages({library(speckle);library(limma);library(statmod)})
options(mc.cores=1L,Ncpus=1L)

pa_propeller <- function(values,samples,labels,conditions,donors,batches,mode,transform,adjust,numerator,denominator) {
    logs <- character()
    con <- textConnection("logs","w",local=TRUE)
    sink(con);sink(con,type="message")
    on.exit({sink(type="message");sink();close(con)},add=TRUE)
    tryCatch(withCallingHandlers({
        counts <- matrix(values,nrow=length(samples),byrow=TRUE,dimnames=list(samples,labels))
        cell.samples <- rep(samples,rowSums(counts))
        cell.labels <- unlist(lapply(seq_len(nrow(counts)),function(i) rep(labels,counts[i,])))
        props <- speckle::getTransformedProps(clusters=factor(cell.labels,levels=labels),sample=factor(cell.samples,levels=samples),transform=transform)
        stopifnot(identical(rownames(props$Proportions),labels),identical(colnames(props$Proportions),samples))
        group <- factor(conditions,levels=c(denominator,numerator))
        donor <- factor(donors,levels=unique(donors));batch <- factor(batches,levels=unique(batches))
        design <- if(mode=="paired") {
            if(adjust) model.matrix(~0+group+donor+batch) else model.matrix(~0+group+donor)
        } else if(adjust) model.matrix(~0+group+batch) else model.matrix(~0+group)
        rownames(design) <- samples
        contrast <- c(-1,1,rep(0,ncol(design)-2))
        base <- list(logs=logs,design=design,design_columns=colnames(design),contrast=contrast,
            proportions=t(props$Proportions),transformed=t(props$TransformedProps))
        unavailable <- function(reason) c(list(status="not_computable",reason=reason),base)
        if(qr(design)$rank<ncol(design)) return(unavailable("design_rank_deficient"))
        if(nrow(design)<=ncol(design)) return(unavailable("no_residual_degrees_of_freedom"))
        testable <- apply(props$TransformedProps,1,function(x) diff(range(x))>1e-12)
        if(!any(testable)) return(unavailable("no_testable_variation"))
        fit <- limma::lmFit(props$TransformedProps[testable,,drop=FALSE],design)
        if(!any(fit$sigma>1e-12)) return(unavailable("no_residual_variation"))
        selected <- lapply(props,function(x) x[testable,,drop=FALSE])
        native <- speckle::propeller.ttest(selected,design=design,contrasts=contrast,robust=TRUE,trend=FALSE,sort=FALSE)
        base$logs <- logs
        base$robust_effective <- nrow(selected$TransformedProps)>2
        statistics <- matrix(NA_real_,nrow=length(labels),ncol=6,dimnames=list(labels,NULL))
        statistics[,1] <- rowMeans(props$Proportions[,conditions==denominator,drop=FALSE])
        statistics[,2] <- rowMeans(props$Proportions[,conditions==numerator,drop=FALSE])
        statistics[,3] <- statistics[,2]/statistics[,1]
        statistics[testable,] <- as.matrix(native)
        c(list(status="completed",reason=""),base,list(statistics=statistics,testable=testable))
    },warning=function(w){cat("warning: ",conditionMessage(w),"\n",sep="");invokeRestart("muffleWarning")}),
    error=function(e) list(status="failed",reason="propeller_failed",logs=c(logs,paste0("error: ",conditionMessage(e)))))
}
