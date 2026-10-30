"""Installed, finite frozen writing wire contract; no current configuration reads."""
import json
from typing import Annotated,Literal
from pydantic import Field,field_validator
from app.domain.model_usage.contracts import StrictContract,ModelPolicy,Money
from app.domain.admin_configuration.model_consumption import combine
from . import policy as installed


class Contract(StrictContract):
    schema_version:Literal[1]=1
    policy:ModelPolicy
    max_input_allowance:Annotated[int,Field(strict=True,ge=1,le=100000)]
    protocol_allowance:Literal[4096]=4096
    instruction:str=Field(max_length=1000)
    task_limit_micro_usd:Annotated[int,Field(strict=True,ge=0,le=3000000)]
    batch_max_posts:Annotated[int,Field(strict=True,ge=1,le=6)]
    max_corrections:Annotated[int,Field(strict=True,ge=0,le=2)]
    batch_cap_micro_usd:Annotated[int,Field(strict=True,ge=1,le=12000000)]


class NumericContract(Contract):
    schema_version:Literal[2]=2
    origin:Literal['installed','configuration']
    instruction_revision:Literal['legacy','numeric2-exact-v1']='legacy'

class SchoolContract(NumericContract):
    schema_version:Literal[3]=3
    numeric_contract_version:Literal[2]
    school_content_version:Literal['school-live-v1']='school-live-v1'

    @field_validator('schema_version','numeric_contract_version',mode='before')
    @classmethod
    def literal_school_version(cls,value):
        if type(value) is not int:raise ValueError('School versions require explicit integers')
        return value


def validate(value):
    model=SchoolContract if isinstance(value,dict) and value.get('schema_version')==3 else NumericContract if isinstance(value,dict) and value.get('schema_version')==2 else Contract
    parsed=model.model_validate(value)
    value=parsed.model_dump(mode='json')
    # Missing revision is the historical wire contract, including its dump shape.
    if 'instruction_revision' not in parsed.model_fields_set:value.pop('instruction_revision',None)
    p=value['policy']
    if (p['model']!=installed.MODEL or p['prompt_version']!='sci-writing-v2' or p['tools']
        or p['output_format']!='manuscript_writing_v2' or p['max_output_tokens']>installed.MAX_OUTPUT):raise ValueError('Unsupported writing contract')
    combine('fixed',value['instruction'])
    return value


def contract(version=None,*,schema_version=1,instruction_revision='numeric2-exact-v1'):
    if type(schema_version) is not int or schema_version not in (1,2,3):raise ValueError('Unknown frozen contract version')
    models=version['bundle']['models'] if version else None
    execution=models['writing']['execution'] if models else None
    return validate(dict(schema_version=schema_version,**({'instruction_revision':instruction_revision} if schema_version==2 and instruction_revision is not None else {}),**({'numeric_contract_version':2} if schema_version==3 else {}),**({'origin':'configuration' if version else 'installed'} if schema_version in (2,3) else {}),
        policy=execution['policy'] if execution else installed.policy().model_dump(mode='json'),
        max_input_allowance=execution['input_token_allowance'] if execution else installed.MAX_INPUT,
        instruction=version['bundle']['prompts']['writing_instruction'] if version else '',
        task_limit_micro_usd=execution['task_limit_micro_usd'] if execution else installed.TASK_CAP,
        batch_max_posts=models['batch_max_posts'] if models else installed.MAX_POSTS,
        max_corrections=models['max_corrections'] if models else installed.MAX_CORRECTIONS,
        batch_cap_micro_usd=models['batch_cap_micro_usd'] if models else installed.BATCH_CAP))


def bundle_contract(bundle):
    return validate(bundle['execution_contract']) if 'execution_contract' in bundle else contract(schema_version=1)


def wire_parts(value,payload):
    from .bundle import INSTRUCTIONS
    from .live_contracts import LiveOutput
    if value['schema_version']==3:
        from .school_live import INSTRUCTIONS as school_instruction,output_schema
        from .numeric_contract import INSTRUCTION
        if value['numeric_contract_version']!=2 or payload.get('numeric_contract_version')!=2 or payload.get('school_content_version')!=value['school_content_version']:raise ValueError('School contract version mismatch')
        instruction=school_instruction+' '+INSTRUCTION;name='manuscript_school_writing_v1';schema=output_schema(payload)
    elif value['schema_version']==2:
        from .numeric_contract import INSTRUCTION,EXACT_INSTRUCTION,output_schema
        if payload.get('numeric_contract_version')!=2:raise ValueError('Numeric contract version mismatch')
        numeric_instruction=EXACT_INSTRUCTION if value.get('instruction_revision')=='numeric2-exact-v1' else INSTRUCTION
        instruction=INSTRUCTIONS+' '+numeric_instruction;name='manuscript_writing_numeric_v2';schema=output_schema(payload)
    else:
        instruction=INSTRUCTIONS;name='manuscript_writing_v2';schema=LiveOutput.model_json_schema()
    return dict(instructions=combine(instruction,value['instruction']),
        text=dict(format=dict(type='json_schema',name=name,strict=True,schema=schema)))


def validate_wire(wire_json,value):
    from app.adapters.models.openai_responses import canonical_payload
    value=validate(value);p=value['policy'];wire=json.loads(wire_json)
    if not isinstance(wire.get('input'),str):raise ValueError('Invalid frozen wire')
    payload=json.loads(wire['input']) if value['schema_version'] in (2,3) else None
    if value['schema_version'] in (2,3) and canonical_payload(payload)!=wire['input']:raise ValueError('Noncanonical numeric input')
    expected=dict(model=p['model'],background=True,store=True,service_tier='default',
        input=wire['input'],max_output_tokens=p['max_output_tokens'],**wire_parts(value,payload))
    if wire!=expected or canonical_payload(wire)!=wire_json or not isinstance(wire['input'],str):raise ValueError('Invalid frozen wire')
    if len(wire_json.encode())+value['protocol_allowance']>value['max_input_allowance']:raise ValueError('Input exceeds frozen limit')
    return ModelPolicy.model_validate(p)
