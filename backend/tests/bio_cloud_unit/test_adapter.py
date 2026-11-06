import importlib
import pytest


def test_missing_settings_does_not_resolve_credentials(monkeypatch):
    monkeypatch.delenv('PAPERASSIST_BIO_CLOUD_CONFIG_FILE', raising=False)
    assert importlib.util.find_spec('app.domain.bio_cloud.settings') is not None
    from app.domain.bio_cloud.settings import load_settings
    assert load_settings().enabled is False


def profile():
    from app.domain.bio_cloud.contracts import WorkflowProfile
    return WorkflowProfile(id='p', name='p', workflow_id='123', workflow_version='v1', species='human', chemistries=['v3'], reference_id='ref', parameters={'input': '{samplesheet_uri}', 'fixed': 'yes'}, outputs={k:k+'.txt' for k in ['matrix','features','barcodes','qc','log']}, account_verified=True)


def settings():
    from app.domain.bio_cloud.settings import CloudSettings
    return CloudSettings(enabled=True, input_bucket='input-bucket', output_bucket='output-bucket', role_arn='arn:aws:iam::123456789012:role/run', profiles=[profile()])


class Client:
    def __init__(self, **responses):
        self.responses = responses
        self.calls = []
    def __getattr__(self, name):
        def call(**kwargs):
            self.calls.append((name, kwargs))
            result = self.responses.get(name, {})
            if isinstance(result, Exception):
                raise result
            if isinstance(result, list):
                return result.pop(0)
            return result
        return call


def provider(client):
    from app.adapters.bio_cloud.aws import AwsBioProvider
    return AwsBioProvider(settings(), omics=client, s3=client)


def test_submit_keeps_request_identity():
    client = Client(start_run={'id':'42', 'arn':'arn', 'uuid':'u', 'status':'PENDING'})
    assert provider(client).submit_run(profile(), request_id='persisted', task_id='task', output_prefix='project/run', parameters={'input':'s3://input-bucket/s.csv','fixed':'yes'})['run_id'] == '42'
    payload = client.calls[0][1]
    assert payload['requestId'] == 'persisted'
    assert payload['workflowType'] == 'READY2RUN'
    assert payload['workflowVersionName'] == 'v1'


def test_submit_accepts_server_generated_directory_prefix():
    client = Client(start_run={'id':'42', 'status':'PENDING'})
    provider(client).submit_run(profile(), request_id='persisted', task_id='task',
        output_prefix='paperassist/project/bio-cloud/run/outputs/', parameters={'input':'x','fixed':'yes'})
    assert client.calls[0][1]['outputUri'] == 's3://output-bucket/paperassist/project/bio-cloud/run/outputs/'


def test_submit_unknown_is_single_safe_failure():
    from app.domain.bio_cloud.provider import ProviderError
    client = Client(start_run=TimeoutError('secret'))
    with pytest.raises(ProviderError) as err:
        provider(client).submit_run(profile(), request_id='r',task_id='t',output_prefix='p',parameters={'input':'x','fixed':'yes'})
    assert err.value.uncertain and str(err.value) == 'submission_unknown'
    assert len(client.calls) == 1


def test_parts_paginate_and_checksum_completion():
    client = Client(list_parts=[{'Parts':[{'PartNumber':1,'ETag':'e','Size':10,'ChecksumSHA256':'hash'}], 'IsTruncated':True,'NextPartNumberMarker':1}, {'Parts':[{'PartNumber':2,'ETag':'f','Size':2,'ChecksumSHA256':'hash2'}]}], head_object={'ContentLength':12,'ETag':'e','ChecksumSHA256':'composite','ChecksumType':'COMPOSITE'})
    p = provider(client)
    parts = p.list_parts('p/file','upload')
    assert len(parts) == 2 and parts[0]['checksum_sha256'] == 'hash'
    # Non-final multipart chunks must reach 5 MiB.
    from app.domain.bio_cloud.provider import ProviderError
    with pytest.raises(ProviderError):
        p.complete_upload('p/file','upload',parts)
    assert p.head_input('p/file')['checksum_type'] == 'COMPOSITE'


def test_unknown_status_and_output_scope():
    from app.domain.bio_cloud.provider import ProviderError
    c = Client(get_run={'id':'42','status':'FUTURE_STATUS','parameters':{'secret':'x'},'statusMessage':'secret'})
    p = provider(c)
    assert {k:v for k,v in p.get_run('42').items() if k != 'parameters_sha256'} == {'run_id':'42','status':'FUTURE_STATUS','run_output_uri':None}
    with pytest.raises(ProviderError): p.list_outputs('s3://evil-bucket/p')
    with pytest.raises(ProviderError): p.head_input('../secret')


def test_config_rejects_secret_and_template_traversal(tmp_path, monkeypatch):
    from app.domain.bio_cloud.settings import load_settings
    from app.domain.bio_cloud.provider import ProviderError
    path=tmp_path/'config.json'; path.write_text('{"access_key":"secret"}')
    monkeypatch.setenv('PAPERASSIST_BIO_CLOUD_CONFIG_FILE', str(path))
    with pytest.raises(ProviderError) as error: load_settings()
    assert 'secret' not in str(error.value)
    from pydantic import ValidationError
    with pytest.raises(ValidationError): profile().model_validate({**profile().model_dump(), 'parameters':{'bad':'{sample_id.__class__}'}})


def test_sdk_models_and_real_stubber():
    import boto3
    from botocore.config import Config
    from botocore.stub import Stubber
    from app.adapters.bio_cloud.aws import AwsBioProvider
    client = boto3.client('omics', region_name='ap-southeast-1', aws_access_key_id='offline', aws_secret_access_key='offline', config=Config(retries={'total_max_attempts':1}))
    stub = Stubber(client)
    expected = dict(requestId='request',workflowId='123',workflowType='READY2RUN',workflowVersionName='v1',roleArn=settings().role_arn,name='task',outputUri='s3://output-bucket/p/',parameters={'input':'uri','fixed':'yes'})
    stub.add_response('start_run', {'id':'42','arn':'arn:aws:omics:ap-southeast-1:123456789012:run/42','status':'PENDING'}, expected)
    with stub:
        assert AwsBioProvider(settings(),omics=client).submit_run(profile(),request_id='request',task_id='task',output_prefix='p',parameters={'input':'uri','fixed':'yes'})['run_id']=='42'
    assert client.meta.config.retries['total_max_attempts']==1
    client.close()


def test_sdk_s3_contract_and_embedded_completion_failure():
    import boto3
    from botocore.stub import Stubber
    from app.adapters.bio_cloud.aws import AwsBioProvider
    from app.domain.bio_cloud.provider import ProviderError
    c=boto3.client('s3',region_name='ap-southeast-1',aws_access_key_id='offline',aws_secret_access_key='offline')
    s=Stubber(c)
    s.add_response('create_multipart_upload',{'UploadId':'u'},{'Bucket':'input-bucket','Key':'p/f','ChecksumAlgorithm':'SHA256'})
    s.add_client_error('complete_multipart_upload',service_error_code='InternalError',service_message='secret',http_status_code=200)
    p=AwsBioProvider(settings(),s3=c)
    with s:
        assert p.begin_upload('p/f')=='u'
        with pytest.raises(ProviderError) as error:
            p.complete_upload('p/f','u',[dict(part_number=1,etag='e',size_bytes=1,checksum_sha256='abc')])
        assert str(error.value)=='provider_request_failed'
    c.close()


def test_sign_parts_complete_and_paginate_outputs():
    import base64
    from app.domain.bio_cloud.contracts import build_parameters
    c=Client(generate_presigned_url='signed', complete_multipart_upload={}, head_object={'ContentLength':1,'ETag':'e'}, list_objects_v2=[{'Contents':[{'Key':'p/a','Size':1}], 'IsTruncated':True,'NextContinuationToken':'next'},{'Contents':[{'Key':'p/b','Size':2}]}])
    p=provider(c)
    checksum=base64.b64encode(b'x'*32).decode()
    assert p.sign_part('p/f','u',1,checksum)['headers']=={'x-amz-checksum-sha256':checksum}
    assert c.calls[0][1]['ExpiresIn']==900
    assert p.complete_upload('p/f','u',[dict(part_number=1,etag='e',size_bytes=1,checksum_sha256=checksum)])['size_bytes']==1
    assert len(p.list_outputs('s3://output-bucket/p'))==2
    assert build_parameters(profile(),samplesheet_uri='uri',fastq_r1='a',fastq_r2='b',sample_id='s')=={'input':'uri','fixed':'yes'}


@pytest.mark.parametrize('method,args', [('get_run',('',)),('cancel_run',('',)),('sign_part',('p','u',10001,'bad')),('put_samplesheet',('p',b''))])
def test_rejected_inputs_never_call_sdk(method,args):
    from app.domain.bio_cloud.provider import ProviderError
    c=Client()
    with pytest.raises(ProviderError): getattr(provider(c),method)(*args)
    assert not c.calls


def test_repeated_pagination_rejected_and_no_secrets():
    from app.domain.bio_cloud.provider import ProviderError
    c=Client(list_objects_v2={'IsTruncated':True,'NextContinuationToken':'repeat'})
    with pytest.raises(ProviderError): provider(c).list_outputs('s3://output-bucket/p')
    assert len(c.calls)==2


def test_profile_is_frozen_and_get_run_sdk_output_uri():
    from pydantic import ValidationError
    with pytest.raises(ValidationError): profile().account_verified=False
    import boto3
    from botocore.stub import Stubber
    from app.adapters.bio_cloud.aws import AwsBioProvider
    c=boto3.client('omics',region_name='ap-southeast-1',aws_access_key_id='offline',aws_secret_access_key='offline')
    s=Stubber(c)
    s.add_response('get_run',{'id':'42','status':'DELETED','runOutputUri':'s3://output-bucket/p'},{'id':'42'})
    with s:
        result=AwsBioProvider(settings(),omics=c).get_run('42')
        assert result['status']=='DELETED' and result['run_output_uri']=='s3://output-bucket/p'
    c.close()


@pytest.mark.parametrize('template',['{unknown}','{sample_id.__class__}','{sample_id[0]}','{sample_id!r}','{sample_id:10}','{{sample_id}}'])
def test_unsafe_templates_rejected(template):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        profile().model_validate({**profile().model_dump(),'parameters':{'x':template}})


def test_missing_submission_receipt_is_uncertain():
    from app.domain.bio_cloud.provider import ProviderError
    with pytest.raises(ProviderError) as error:
        provider(Client(start_run={})).submit_run(profile(),request_id='r',task_id='t',output_prefix='p',parameters={'input':'x','fixed':'yes'})
    assert error.value.uncertain


def test_config_parameters_reject_credentials():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        profile().model_validate({**profile().model_dump(),'parameters':{'aws_secret_access_key':'never-store'}})


def test_output_stream_uses_identity_precondition():
    c=Client(get_object={'Body':'stream'})
    assert provider(c).stream_output('p/result',expected_etag='"etag"')=='stream'
    assert c.calls[0][1]['IfMatch']=='"etag"'


@pytest.mark.parametrize('status', [500,503,200,None])
def test_submission_service_errors_are_uncertain(status):
    from app.domain.bio_cloud.provider import ProviderError
    class Failure(Exception):
        response={'ResponseMetadata':{'HTTPStatusCode':status},'Error':{'Code':'InternalError'}}
    with pytest.raises(ProviderError) as error:
        provider(Client(start_run=Failure())).submit_run(profile(),request_id='r',task_id='t',output_prefix='p',parameters={'input':'x','fixed':'yes'})
    assert error.value.uncertain


def test_injected_sdk_client_with_retries_rejected():
    import boto3
    from app.adapters.bio_cloud.aws import AwsBioProvider
    from app.domain.bio_cloud.provider import ProviderError
    c=boto3.client('omics',region_name='ap-southeast-1',aws_access_key_id='offline',aws_secret_access_key='offline')
    def forbid_network(**kwargs):
        raise AssertionError('network forbidden')
    c.meta.events.register('before-send.omics.StartRun',forbid_network)
    with pytest.raises(ProviderError, match="provider_retries_enabled"):
        AwsBioProvider(settings(),omics=c).submit_run(profile(),request_id='r',task_id='t',output_prefix='p',parameters={'input':'x','fixed':'yes'})
    c.close()


def test_get_run_safe_recovery_identity():
    import hashlib,json
    params={'input':'中文','fixed':'yes'}
    result=provider(Client(get_run={'id':'42','status':'RUNNING','name':'task','workflowId':'123','workflowType':'READY2RUN','workflowVersionName':'v1','parameters':params})).get_run('42')
    assert result['name']=='task' and result['workflow_id']=='123' and result['workflow_type']=='READY2RUN' and result['workflow_version']=='v1'
    assert result['parameters_sha256']==hashlib.sha256(json.dumps(params,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    assert 'parameters' not in result and 'workflowId' not in result


@pytest.mark.parametrize('key',['awsAccessKeyId','awsSessionToken','accessKeyId','AWS_SECRET_ACCESS_KEY'])
def test_normalized_credential_parameter_rejected(key):
    from pydantic import ValidationError
    with pytest.raises(ValidationError): profile().model_validate({**profile().model_dump(),'parameters':{key:'secret'}})




@pytest.mark.parametrize('status,code,uncertain',[(400,'ValidationException',False),(403,'AccessDeniedException',False),(429,'ThrottlingException',False),(400,'UnknownException',True),(500,'ValidationException',True)])
def test_only_explicit_submission_rejections_are_certain(status,code,uncertain):
    from app.domain.bio_cloud.provider import ProviderError
    class Failure(Exception):
        response={'ResponseMetadata':{'HTTPStatusCode':status},'Error':{'Code':code}}
    with pytest.raises(ProviderError) as error:
        provider(Client(start_run=Failure())).submit_run(profile(),request_id='r',task_id='t',output_prefix='p',parameters={'input':'x','fixed':'yes'})
    assert error.value.uncertain is uncertain
