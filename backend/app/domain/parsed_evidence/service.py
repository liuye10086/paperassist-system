"""Reuse each existing ownership and immutable object verification boundary."""
from urllib.parse import quote
from app.domain.parsed_evidence.contracts import Origin
from app.domain.parsed_evidence.documents import project_document
from app.domain.parsed_evidence.datasets import project_sheet


class ParsedEvidenceService:
    def __init__(self, assets):
        self.assets = assets

    def origin(self, project, file, id, version, kind, filename, digest, suffix, source_digest):
        base='/api/v1/projects/{}/files/{}'.format(quote(project,safe=''),quote(file,safe=''))
        return Origin(project_id=project,file_id=file,version_id=id,version=version,kind=kind,
            filename=filename,sha256=digest,source_sha256=source_digest,original_download_url=base+'/download',
            object_download_url=base+'/'+suffix+'/'+quote(id,safe='')+'/download')

    def document(self, project, file, id, page):
        from app.domain.documents.service import DocumentService
        service=DocumentService(self.assets)
        row=service.load(project,file,id,True)
        _,document=service.read(row)
        origin=self.origin(project,file,id,row['version'],'document_version',document.filename,
            row['result_json']['object']['sha256'],'document-versions',row['source_sha256'])
        return project_document(document,origin,origin.object_download_url.removesuffix('/download')+'/images',page)

    def dataset(self, project, file, id, page):
        from app.domain.datasets.service import DatasetService
        row,_,sheet=DatasetService(self.assets).dataset(project,file,id)
        origin=self.origin(project,file,id,row['version'],'dataset_version',row['manifest_json']['filename'],
            row['sha256'],'dataset-versions',row['source_sha256'])
        return project_sheet(sheet,origin,row['parser_version'],page)

    def prepared(self, project, file, id, page):
        from app.domain.dataset_preparation.service import DatasetPreparationService
        service=DatasetPreparationService(self.assets)
        row,_,obj=service.load_version(project,file,id)
        raw,_,sheet=service.datasets.dataset(project,file,row['parent_dataset_id'])
        origin=self.origin(project,file,id,row['version'],'prepared_dataset_version',raw['manifest_json']['filename'],
            row['sha256'],'prepared-dataset-versions',obj.parent_source.source_sha256)
        origin.parent_version_id=row['parent_dataset_id']
        origin.parent_object_download_url=origin.original_download_url.removesuffix('/download')+'/dataset-versions/'+quote(row['parent_dataset_id'],safe='')+'/download'
        return project_sheet(obj.sheet,origin,obj.transform_version,page,prepared=obj,raw_sheet=sheet)
