"""Reuse admitted, fenced science publication for independent annotation tasks."""
import csv
import hashlib
import io
from pathlib import Path
from uuid import UUID,uuid5
from app.adapters.bio_analysis_execution import BioAnalysisExecution
from app.adapters.bio_objects import BioAnnotationObjects
from app.adapters.task_store import DatasetTaskAssets
from app.domain.bioinformatics.annotation_service import BioAnnotationService,candidate_annotations
from app.domain.bioinformatics.contracts import canonical


def annotation_documents(task,result,objects,stage):
    """Attach human-readable evidence and exact machine assignments before admission."""
    value=task['input_snapshot'];identifier=value['run_id'];members=[]
    for item in result['outputs']:
        members.append({**{k:item[k] for k in ('key','role','format','sha256','size_bytes')},
            'id':str(uuid5(UUID(identifier),stage+':'+item['key'])),
            'object_key':f'{objects.prefix}/{identifier}/{item["sha256"]}.bin'})
    candidate=next(item for item in result['outputs'] if item['key']=='annotation_candidates')
    rows=list(csv.DictReader(io.StringIO(Path(candidate['path']).read_text(encoding='utf-8')),delimiter='\t'))
    _,assignments=candidate_annotations(rows)
    algorithm=result['manifest'].get('algorithm')
    if not isinstance(algorithm,dict):
        algorithm=dict(tool='SingleR',version=result['manifest'].get('tool_version'),reference=result['manifest'].get('reference'),matching=result['manifest'].get('matching'),candidate_only=True)
    parent=value['parent_processed_source']
    geometry=dict(schema_version=1,name=value['name'],coordinate_space='cell',raw_source=parent['raw_source'],
        processed_source=parent,overlap_policy='ambiguity',regions=[],origin='SingleR',algorithm=algorithm,members=members)
    for key,body in [('annotation_geometry',geometry),('annotation_assignments',dict(schema_version=1,rows=assignments))]:
        content=canonical(body);path=Path(candidate['path']).parent/(key+'.json');path.write_bytes(content)
        result['outputs'].append(dict(key=key,role='annotation',format='json',sha256=hashlib.sha256(content).hexdigest(),size_bytes=len(content),path=str(path)))
    return result


class BioAnnotationExecution(BioAnalysisExecution):
    def service(self,task):return BioAnnotationService(DatasetTaskAssets(task['user_id'],self.repository.config,self.repository.assets.directory))
    def objects(self,task):return BioAnnotationObjects(self.repository.assets.directory)
    def _prepare(self,lease,checkpoint,result,stage):
        with self.repository.connection() as db:
            task=self.repository.require_lease(db,lease);self.repository.require_owner(db,task)
        result=annotation_documents(task,result,self.objects(task),stage)
        return super()._prepare(lease,checkpoint,result,stage)
