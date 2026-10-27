"""Installed, finite frozen writing wire contract; no current configuration reads."""
import json
from typing import Annotated,Literal
from pydantic import Field
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


def validate(value):
    value=Contract.model_validate(value).model_dump(mode='json')
    p=value['policy']
    if (p['model']!=installed.MODEL or p['prompt_version']!='sci-writing-v2' or p['tools']
        or p['output_format']!='manuscript_writing_v2' or p['max_output_tokens']>installed.MAX_OUTPUT):raise ValueError('Unsupported writing contract')
    combine('fixed',value['instruction'])
    return value


def contract(version=None):
    models=version['bundle']['models'] if version else None
    execution=models['writing']['execution'] if models else None
    return validate(dict(policy=execution['policy'] if execution else installed.policy().model_dump(mode='json'),
        max_input_allowance=execution['input_token_allowance'] if execution else installed.MAX_INPUT,
        instruction=version['bundle']['prompts']['writing_instruction'] if version else '',
        task_limit_micro_usd=execution['task_limit_micro_usd'] if execution else installed.TASK_CAP,
        batch_max_posts=models['batch_max_posts'] if models else installed.MAX_POSTS,
        max_corrections=models['max_corrections'] if models else installed.MAX_CORRECTIONS,
        batch_cap_micro_usd=models['batch_cap_micro_usd'] if models else installed.BATCH_CAP))


def bundle_contract(bundle):
    return validate(bundle['execution_contract']) if 'execution_contract' in bundle else contract()


def validate_wire(wire_json,value):
    from app.adapters.models.openai_responses import canonical_payload
    from .bundle import INSTRUCTIONS
    from .live_contracts import LiveOutput
    value=validate(value);p=value['policy'];wire=json.loads(wire_json)
    expected=dict(model=p['model'],background=True,store=True,service_tier='default',
        instructions=combine(INSTRUCTIONS,value['instruction']),input=wire['input'],max_output_tokens=p['max_output_tokens'],
        text=dict(format=dict(type='json_schema',name='manuscript_writing_v2',strict=True,schema=LiveOutput.model_json_schema())))
    if wire!=expected or canonical_payload(wire)!=wire_json or not isinstance(wire['input'],str):raise ValueError('Invalid frozen wire')
    if len(wire_json.encode())+value['protocol_allowance']>value['max_input_allowance']:raise ValueError('Input exceeds frozen limit')
    return ModelPolicy.model_validate(p)
