# Original package entry points, sequential execution only.
pa_topics_capture <- function(f) {
  logs <- character()
  out <- tryCatch(withCallingHandlers(f(), warning=function(w) {logs <<- c(logs,conditionMessage(w)); invokeRestart('muffleWarning')}, message=function(m) {logs <<- c(logs,conditionMessage(m)); invokeRestart('muffleMessage')}),error=function(e) list(status='failed',reason=if(grepl('cannot allocate',conditionMessage(e))) 'resource_insufficient' else 'tool_failed',error=conditionMessage(e)))
  if(is.null(out$status)) out$status <- 'completed'
  if(is.null(out$reason)) out$reason <- ''
  out$logs <- c(logs,out$error); out
}
pa_topics_slingshot <- function(values,cells,labels,root,ndim,seed) pa_topics_capture(function() {
  set.seed(seed)
  x <- matrix(values,nrow=length(cells),ncol=ndim,byrow=TRUE,dimnames=list(cells,NULL))
  fit <- slingshot::slingshot(x,clusterLabels=labels,start.clus=root)
  pt <- slingshot::slingPseudotime(fit,na=TRUE)
  curves <- lapply(slingshot::slingCurves(fit),function(curve) curve$s[curve$ord,,drop=FALSE])
  list(cells=rownames(pt),pseudotime=pt,weights=slingshot::slingCurveWeights(fit),lineage_ids=colnames(pt),lineage_clusters=slingshot::slingLineages(fit),curves=curves)
})
pa_topics_matrix <- function(x,i,p,genes,cells) methods::new('dgCMatrix',x=x,i=i,p=p,Dim=as.integer(c(length(genes),length(cells))),Dimnames=list(genes,cells))
pa_topics_genie3 <- function(x,i,p,genes,cells,tf,seed,trees) pa_topics_capture(function() {
  expression <- pa_topics_matrix(x,i,p,genes,cells)
  set.seed(seed)
  weights <- GENIE3::GENIE3(as.matrix(expression),regulators=tf,nTrees=trees,nCores=1,verbose=FALSE)
  list(regulators=tf,targets=genes,weights=weights[tf,genes,drop=FALSE])
})
pa_topics_cellchat <- function(x,i,p,genes,cells,labels,resource_json,lr_ids,seed,nboot,mincells) pa_topics_capture(function() {
  future::plan(future::sequential)
  resource <- jsonlite::fromJSON(resource_json,simplifyVector=FALSE)
  rows <- resource$interactions
  rows <- rows[vapply(rows,function(r) r$interaction_id %in% lr_ids,logical(1))]
  interaction <- do.call(rbind,lapply(rows,function(r) data.frame(interaction_name=r$interaction_id,pathway_name=r$pathway,ligand=r$ligand,receptor=r$receptor,agonist=r$agonist,antagonist=r$antagonist,co_A_receptor=r$co_A_receptor,co_I_receptor=r$co_I_receptor,evidence=r$source,annotation=r$annotation,interaction_name_2=r$interaction_id,stringsAsFactors=FALSE)))
  rownames(interaction)<-interaction$interaction_name
  complex <- as.data.frame(matrix('',nrow=length(resource$complexes),ncol=4),stringsAsFactors=FALSE)
  names(complex)<-paste0('subunit_',1:4)
  if(length(resource$complexes)) for(j in seq_along(resource$complexes)) complex[j,seq_along(resource$complexes[[j]])]<-unlist(resource$complexes[[j]])
  rownames(complex)<-names(resource$complexes)
  cofactor<-as.data.frame(matrix('',nrow=length(resource$cofactors),ncol=max(2,lengths(resource$cofactors))),stringsAsFactors=FALSE)
  names(cofactor)<-paste0('cofactor',seq_len(ncol(cofactor)))
  if(length(resource$cofactors)) for(j in seq_along(resource$cofactors)) cofactor[j,seq_along(resource$cofactors[[j]])]<-unlist(resource$cofactors[[j]])
  rownames(cofactor)<-names(resource$cofactors)
  db<-list(interaction=interaction,complex=complex,cofactor=cofactor,geneInfo=data.frame(Symbol=unlist(resource$gene_symbols)))
  expression <- pa_topics_matrix(x,i,p,genes,cells)
  meta<-data.frame(labels=factor(labels,levels=unique(labels)),row.names=cells)
  cc<-CellChat::createCellChat(object=expression,meta=meta,group.by='labels',do.sparse=TRUE)
  cc@DB<-db
  cc<-CellChat::subsetData(cc)
  # Explicitly requested interactions: do not perform hidden DE filtering.
  cc<-CellChat::computeCommunProb(cc,LR.use=interaction,raw.use=TRUE,type='triMean',population.size=FALSE,nboot=nboot,seed.use=seed,distance.use=FALSE)
  cc<-CellChat::filterCommunication(cc,min.cells=mincells)
  prob<-cc@net$prob; pval<-cc@net$pval
  indices<-which(array(TRUE,dim(prob)),arr.ind=TRUE)
  list(sender=dimnames(prob)[[1]][indices[,1]],receiver=dimnames(prob)[[2]][indices[,2]],interaction_id=dimnames(prob)[[3]][indices[,3]],probability=prob[indices],p_value=pval[indices],group_names=levels(cc@idents),group_sizes=as.integer(table(cc@idents)))
})
