"""Separate batch06 public-input approval, durable attempts and fixed model transport.

The manifest is an explicit approval artifact: its exact public input hashes must
be prepared and inspected by the approved runner, never derived automatically
from an arbitrary incoming task. It is independent of the closed batch05 journal.
"""
from copy import deepcopy
import json
import re
import time

from openai import APIConnectionError, APIStatusError, DefaultHttpxClient

from app.adapters.models.openai_responses import OpenAIResponsesProvider, ModelProviderError, RESPONSE_ID, canonical_payload
from app.domain.model_usage.contracts import ModelPolicy
from app.domain.model_usage.gateway import input_digest
from app.domain.model_usage.pricing import estimate_usage
from app.domain.literature_assistance.contracts import result_text_format
from .ledger import LiveLedger
from .policy import LivePolicyError, strict_json


MODEL_POLICY = dict(model='gpt-6.1-sol', prompt_version='literature_assistance_v1',max_output_tokens=3000,
    timeout_seconds=45,tools=[],output_format='text',price=dict(version='stage05-batch06-standard-2026-10-19',
    currency='USD',model='gpt-6.1-sol',input_micro_usd_per_million=2000000,cached_input_micro_usd_per_million=100000,
    cache_write_micro_usd_per_million=2500000,output_micro_usd_per_million=10000000))
LIMITS = {'model_create':8,'model_read':40,'pmc':12}
HASH = re.compile(r'[0-9a-f]{64}\Z')


class Batch06Ledger(LiveLedger):
    def __init__(self,path,*,batch_id,schema,public_inputs,pmcids):
        try:
            if not isinstance(schema,str) or not re.fullmatch(r'pa_test_[0-9a-f]{32}',schema):raise ValueError()
            self._validate_inputs(public_inputs,allow_empty=True)
            if (not isinstance(pmcids,list) or len(pmcids)>3 or len(set(pmcids))!=len(pmcids)
                or any(not isinstance(p,str) or not re.fullmatch(r'PMC[1-9][0-9]{0,11}',p) for p in pmcids)):raise ValueError()
            self._policy_json=canonical_payload(dict(version='stage05-batch06-public-v1',schema=schema,
                public_inputs=deepcopy(public_inputs),pmcids=list(pmcids),limits=LIMITS,
                create_reserve_micro_usd=250000,batch_budget_micro_usd=2000000,input_token_limit=12000,model_policy=MODEL_POLICY))
        except Exception:raise LivePolicyError('batch06_manifest_invalid') from None
        super().__init__(path,batch_id=batch_id)

    @staticmethod
    def _validate_inputs(public_inputs,*,allow_empty=False):
        if not isinstance(public_inputs,list) or not (0 if allow_empty else 1)<=len(public_inputs)<=8:raise ValueError()
        seen=set()
        for item in public_inputs:
            if (not isinstance(item,dict) or set(item)!={'task_id','input_digest','payload_digest'}
                or not isinstance(item['task_id'],str) or not re.fullmatch(r'[^\s]{1,64}',item['task_id'])
                or any(not isinstance(item[k],str) or not HASH.fullmatch(item[k]) for k in ('input_digest','payload_digest'))
                or item['task_id'] in seen):raise ValueError()
            seen.add(item['task_id'])

    @property
    def policy(self):return json.loads(self._policy_json)

    def _apply_reservation(self,state,kind,action):
        if kind not in LIMITS or not isinstance(action,dict):raise LivePolicyError('live_request_denied')
        if state[kind+'_attempts']>=LIMITS[kind]:raise LivePolicyError('live_budget_exhausted')
        if kind=='model_create':
            if action not in state['public_inputs']:raise LivePolicyError('batch06_input_mismatch')
            if action['task_id'] in state['created_tasks']:raise LivePolicyError('batch06_submission_unknown')
            state['created_tasks'].add(action['task_id'])
        elif kind=='model_read':
            if (set(action)!={'task_id','response_id'}
                or state['responses'].get(action.get('task_id'))!=action.get('response_id')
                or action.get('response_id') is None):raise LivePolicyError('live_request_denied')
        elif set(action)!={'pmcid'} or action['pmcid'] not in self.policy['pmcids']:
            raise LivePolicyError('live_request_denied')
        state[kind+'_attempts']+=1

    def _load(self,lock):
        try:
            raw=self.path.read_bytes();self._verify_checkpoint(lock,raw)
            if not raw.endswith(b'\n') or len(raw)>4*1024*1024:raise ValueError()
            events=[strict_json(line) for line in raw.splitlines()]
            first=events[0]
            if first!={'event':'opened','batch_id':self.batch_id,'policy':self.policy}:raise ValueError()
            state=dict(model_create_attempts=0,model_read_attempts=0,pmc_attempts=0,closed=False,
                reservations={},finished=set(),created_tasks=set(),responses={},accounting={},
                public_inputs=deepcopy(self.policy['public_inputs']),model_inputs_frozen=bool(self.policy['public_inputs']))
            for event in events[1:]:
                if not isinstance(event,dict) or state['closed']:raise ValueError()
                self._time(event['at']);kind=event['event']
                if kind=='reserved':
                    if (set(event)!={'event','attempt','kind','action','at'} or type(event['attempt']) is not int
                        or event['attempt']!=len(state['reservations'])+1):raise ValueError()
                    self._apply_reservation(state,event['kind'],event['action'])
                    state['reservations'][event['attempt']]=event
                elif kind=='finished':
                    if set(event)!={'event','attempt','at','receipt','code'}:raise ValueError()
                    if type(event['attempt']) is not int or event['attempt'] in state['finished']:raise ValueError()
                    reservation=state['reservations'][event['attempt']]
                    receipt=event['receipt']
                    if receipt is not None:
                        if (reservation['kind'] not in ('model_create','model_read') or event['code'] is not None
                            or set(receipt)!={'response_id','accounting'} or not RESPONSE_ID.fullmatch(receipt['response_id'])):raise ValueError()
                        task_id=reservation['action']['task_id']
                        if reservation['kind']=='model_read' and state['responses'][task_id]!=receipt['response_id']:raise ValueError()
                        accounting=receipt['accounting']
                        if (not isinstance(accounting,dict) or set(accounting)!={'provider_usage','estimated_cost_micro_usd','usage_status','reason_code'}):raise ValueError()
                        state['responses'][task_id]=receipt['response_id'];state['accounting'][task_id]=accounting
                    elif event['code'] not in ('request_failed','response_invalid','pmc_finished'):raise ValueError()
                    state['finished'].add(event['attempt'])
                elif kind=='model_inputs_frozen':
                    if set(event)!={'event','at','public_inputs'} or state['model_inputs_frozen']:raise ValueError()
                    self._validate_inputs(event['public_inputs'])
                    state['public_inputs']=event['public_inputs'];state['model_inputs_frozen']=True
                elif kind=='completed' and set(event)=={'event','at'}:state['closed']=True
                else:raise ValueError()
            return state
        except Exception:raise LivePolicyError('live_ledger_invalid') from None

    def reserve(self,state,kind,action):
        if self._lock_stream is None:raise LivePolicyError('live_ledger_invalid')
        if state['closed']:raise LivePolicyError('live_closed')
        # Validate against the actual durable state, never a caller-edited copy.
        current=self._load(self._lock_stream)
        self._apply_reservation(current,kind,action)
        attempt=len(current['reservations'])+1
        self.append(dict(event='reserved',attempt=attempt,kind=kind,action=deepcopy(action),at=time.time()))
        return attempt

    def finish(self,attempt,*,receipt=None,code=None):
        state=self._load(self._lock_stream)
        if state['closed'] or attempt not in state['reservations'] or attempt in state['finished']:raise LivePolicyError('live_request_denied')
        sanitized=None
        if receipt is not None:
            if (state['reservations'][attempt]['kind'] not in ('model_create','model_read') or code is not None
                or not isinstance(receipt,dict) or set(receipt)!={'response_id','usage'}
                or not isinstance(receipt['response_id'],str) or not RESPONSE_ID.fullmatch(receipt['response_id'])):
                raise LivePolicyError('live_request_denied')
            policy=ModelPolicy.model_validate(MODEL_POLICY)
            sanitized=dict(response_id=receipt['response_id'],accounting=estimate_usage(policy.price,receipt['usage']))
        elif code not in ('request_failed','response_invalid','pmc_finished'):raise LivePolicyError('live_request_denied')
        self.append(dict(event='finished',attempt=attempt,at=time.time(),receipt=sanitized,code=code))

    def summary(self):
        with self.locked() as state:
            known=(len(state['accounting'])==state['model_create_attempts'] and
                all(a['usage_status']=='estimated' for a in state['accounting'].values()))
            return dict(batch_id=self.batch_id,closed=state['closed'],schema=self.policy['schema'],
                **{kind+'_attempts':state[kind+'_attempts'] for kind in LIMITS},
                reserved_micro_usd=state['model_create_attempts']*250000,
                estimated_cost_micro_usd=sum(a['estimated_cost_micro_usd'] for a in state['accounting'].values()) if known else None,
                cost_status='estimated' if known else 'unknown',model_inputs_frozen=state['model_inputs_frozen'],
                frozen_model_inputs=len(state['public_inputs']),pmcids=list(self.policy['pmcids']))

    def freeze_model_inputs(self,entries):
        try:self._validate_inputs(entries)
        except Exception:raise LivePolicyError('batch06_manifest_invalid') from None
        with self.locked() as state:
            if state['closed']:raise LivePolicyError('live_closed')
            if state['model_inputs_frozen']:raise LivePolicyError('batch06_inputs_already_frozen')
            self.append(dict(event='model_inputs_frozen',at=time.time(),public_inputs=deepcopy(entries)))

    def assert_input(self,task_id,snapshot_digest,payload_digest):
        action=dict(task_id=task_id,input_digest=snapshot_digest,payload_digest=payload_digest)
        with self.locked() as state:
            if state['closed']:raise LivePolicyError('live_closed')
            if action not in state['public_inputs']:raise LivePolicyError('batch06_input_mismatch')
        return action


def input_allowance(instructions,payload,*,text=None):
    # UTF8 bytes plus fixed framing overhead is deliberately conservative.
    return (len(instructions.encode('utf-8'))+len(canonical_payload(payload).encode('utf-8'))+256
            +(len(canonical_payload({'text':text}).encode('utf-8')) if text is not None else 0))


class Batch06ModelProvider(OpenAIResponsesProvider):
    source_kind='stage05_batch06_public'

    def __init__(self,ledger,*,task_id,snapshot_digest,api_key,http_client=None):
        if type(ledger) is not Batch06Ledger:raise LivePolicyError('batch06_manifest_invalid')
        self.ledger,self.task_id,self.snapshot_digest=ledger,task_id,snapshot_digest
        self._authorization=None
        self.policy=ModelPolicy.model_validate(MODEL_POLICY)
        if http_client is None:http_client=DefaultHttpxClient(trust_env=False,follow_redirects=False)
        super().__init__(api_key=api_key,http_client=http_client)

    def authorize_task(self,task,*,config,instructions,payload):
        self._authorization=None
        if (config.environment!='test' or config.url.database!='paperassist_system_test'
            or config.schema!=self.ledger.policy['schema'] or task['id']!=self.task_id
            or task['input_digest']!=self.snapshot_digest):raise LivePolicyError('batch06_input_mismatch')
        try:
            digest=input_digest(instructions=instructions,payload=payload)
            # A historical GET keeps its original input contract. New submissions
            # include schema bytes before gateway admission and again at create.
            with self.ledger.locked() as state:
                submitted=self.task_id in state['created_tasks']
            text=None if submitted else result_text_format(payload)
            if input_allowance(instructions,payload,text=text)>12000:raise ValueError()
        except Exception:raise LivePolicyError('batch06_input_mismatch') from None
        self._authorization=self.ledger.assert_input(self.task_id,self.snapshot_digest,digest)

    def _check(self,policy):
        if self._authorization is None or policy.model_dump()!=MODEL_POLICY:raise LivePolicyError('batch06_input_mismatch')
        self.ledger.assert_input(self.task_id,self.snapshot_digest,self._authorization['payload_digest'])

    def create(self,*,policy,instructions,payload):
        self._check(policy)
        try:
            text=result_text_format(payload)
            allowance=input_allowance(instructions,payload,text=text)
        except (KeyError,TypeError,ValueError):raise LivePolicyError('batch06_input_mismatch') from None
        if (input_digest(instructions=instructions,payload=payload)!=self._authorization['payload_digest']
            or allowance>12000):raise LivePolicyError('batch06_input_mismatch')
        with self.ledger.locked() as state:
            attempt=self.ledger.reserve(state,'model_create',self._authorization)
            try:
                response=self.client.responses.create(model='gpt-6.1-sol',background=True,store=True,
                    instructions=instructions,input=canonical_payload(payload),max_output_tokens=3000,
                    reasoning={'effort':'low'},service_tier='default',timeout=45,text=text)
                receipt=self._receipt(response)
                if receipt['model']!='gpt-6.1-sol':raise ModelProviderError('model_response_invalid')
                self.ledger.finish(attempt,receipt={k:receipt[k] for k in ('response_id','usage')})
                return receipt
            except Exception as exc:
                self.ledger.finish(attempt,code='request_failed')
                if isinstance(exc,(APIConnectionError,APIStatusError)):
                    raise ModelProviderError(status_code=getattr(exc,'status_code',None)) from None
                raise

    def retrieve(self,response_id,*,policy):
        self._check(policy)
        if not isinstance(response_id,str) or not RESPONSE_ID.fullmatch(response_id):raise LivePolicyError('live_request_denied')
        with self.ledger.locked() as state:
            attempt=self.ledger.reserve(state,'model_read',dict(task_id=self.task_id,response_id=response_id))
            try:
                receipt=super().retrieve(response_id,policy=policy)
                if receipt['response_id']!=response_id or receipt['model']!='gpt-6.1-sol':raise ModelProviderError('model_response_invalid')
                self.ledger.finish(attempt,receipt={k:receipt[k] for k in ('response_id','usage')})
                return receipt
            except Exception:
                self.ledger.finish(attempt,code='request_failed')
                raise
