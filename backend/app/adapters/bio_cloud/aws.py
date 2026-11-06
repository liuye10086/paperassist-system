"""Lazy AWS SDK adapter. No SDK import or credential lookup at module import."""
import base64
import hashlib
import json
from urllib.parse import urlsplit
from app.domain.bio_cloud.contracts import MAX_INPUT_BYTES, object_key
from app.domain.bio_cloud.provider import ProviderError


def identity(value, maximum=1024):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ProviderError('invalid_identifier')
    return value


class AwsBioProvider:
    def __init__(self, settings, *, omics=None, s3=None):
        self.settings = settings
        self._omics, self._s3 = omics, s3

    def _client(self, service):
        if not self.settings.enabled:
            raise ProviderError('cloud_disabled')
        attribute = '_omics' if service == 'omics' else '_s3'
        client = getattr(self, attribute)
        if client is None:
            try:
                import boto3
                from botocore.config import Config
                # StartRun must never be retried implicitly, including SDK retries.
                client = boto3.client(service, region_name=self.settings.region, config=Config(retries={'total_max_attempts': 1, 'mode': 'standard'}))
                setattr(self, attribute, client)
            except Exception:
                raise ProviderError('provider_unavailable') from None
        return client

    def _call(self, service, method, *, uncertain=False, **kwargs):
        client = self._client(service)
        if service == 'omics' and method == 'start_run':
            # Real SDK clients expose this concrete metadata. Lightweight injected
            # fakes need not implement SDK metadata.
            meta = vars(client).get('meta')
            if meta is not None:
                retries = meta.config.retries or {}
                if retries.get('total_max_attempts') != 1 and retries.get('max_attempts') != 0:
                    raise ProviderError('provider_retries_enabled')
        try:
            return getattr(client, method)(**kwargs)
        except Exception as exc:
            # A definite service rejection is not an unknown network receipt.
            response = getattr(exc, 'response', None)
            definite = False
            if isinstance(response, dict):
                status = response.get('ResponseMetadata', {}).get('HTTPStatusCode')
                code = response.get('Error', {}).get('Code')
                definite = status in (400, 401, 403, 404, 409, 429) and code in {
                    'ValidationException', 'AccessDeniedException', 'UnauthorizedException',
                    'ResourceNotFoundException', 'ConflictException', 'ThrottlingException',
                    'ServiceQuotaExceededException', 'LimitExceededException',
                }
            unknown = uncertain and not definite
            raise ProviderError('submission_unknown' if unknown else 'provider_request_failed', uncertain=unknown) from None

    def close(self):
        for client in (self._omics, self._s3):
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    def _input(self, key):
        return {'Bucket': self.settings.input_bucket, 'Key': object_key(key)}

    def begin_upload(self, key):
        result = self._call('s3', 'create_multipart_upload', **self._input(key), ChecksumAlgorithm='SHA256')
        return identity(result.get('UploadId'))

    def sign_part(self, key, upload_id, number, checksum):
        if type(number) is not int or not 1 <= number <= 10000:
            raise ProviderError('invalid_part_number')
        try:
            if len(base64.b64decode(checksum, validate=True)) != 32:
                raise ValueError()
        except Exception:
            raise ProviderError('invalid_checksum') from None
        params = {**self._input(key), 'UploadId': identity(upload_id), 'PartNumber': number, 'ChecksumSHA256': checksum}
        url = self._call('s3', 'generate_presigned_url', ClientMethod='upload_part', Params=params, ExpiresIn=900, HttpMethod='PUT')
        return {'url': url, 'headers': {'x-amz-checksum-sha256': checksum}, 'expires_in': 900}

    def list_parts(self, key, upload_id):
        params = {**self._input(key), 'UploadId': identity(upload_id)}
        parts, marker = [], 0
        while True:
            result = self._call('s3', 'list_parts', **params, PartNumberMarker=marker)
            for p in result.get('Parts', []):
                number = p.get('PartNumber', 0)
                if not marker < number <= 10000 or (parts and number <= parts[-1]['part_number']):
                    raise ProviderError('invalid_provider_pagination')
                parts.append(dict(part_number=number, etag=p.get('ETag'), size_bytes=p.get('Size'), checksum_sha256=p.get('ChecksumSHA256')))
            if len(parts) > 10000:
                raise ProviderError('provider_page_limit')
            if not result.get('IsTruncated'):
                return parts
            next_marker = result.get('NextPartNumberMarker', 0)
            if not isinstance(next_marker, int) or next_marker <= marker or next_marker > 10000:
                raise ProviderError('invalid_provider_pagination')
            marker = next_marker

    def complete_upload(self, key, upload_id, parts):
        if not parts or len(parts) > 10000:
            raise ProviderError('invalid_parts')
        total = 0
        payload = []
        for index, p in enumerate(parts):
            size = p.get('size_bytes')
            if p.get('part_number') != index + 1 or type(size) is not int or size <= 0 or size > 5 * 1024**3 or (index < len(parts)-1 and size < 5*1024**2) or not p.get('etag') or not p.get('checksum_sha256'):
                raise ProviderError('invalid_parts')
            total += size
            payload.append({'PartNumber': index+1, 'ETag': p['etag'], 'ChecksumSHA256': p['checksum_sha256']})
        if total > MAX_INPUT_BYTES:
            raise ProviderError('input_too_large')
        self._call('s3', 'complete_multipart_upload', **self._input(key), UploadId=identity(upload_id), MultipartUpload={'Parts': payload})
        result = self.head_input(key)
        if result['size_bytes'] != total:
            raise ProviderError('upload_size_mismatch')
        return result

    def head_input(self, key):
        value = self._call('s3', 'head_object', **self._input(key), ChecksumMode='ENABLED')
        size = value.get('ContentLength')
        if type(size) is not int or not 0 <= size <= MAX_INPUT_BYTES:
            raise ProviderError('invalid_object_size')
        return dict(size_bytes=size, etag=value.get('ETag'), version_id=value.get('VersionId'), checksum_sha256=value.get('ChecksumSHA256'), checksum_type=value.get('ChecksumType'))

    def abort_upload(self, key, upload_id):
        self._call('s3', 'abort_multipart_upload', **self._input(key), UploadId=identity(upload_id))

    def put_samplesheet(self, key, content):
        if not isinstance(content, bytes) or not content or len(content) > 1024*1024:
            raise ProviderError('invalid_samplesheet')
        self._call('s3', 'put_object', **self._input(key), Body=content, ContentType='text/csv', ChecksumAlgorithm='SHA256')
        return f's3://{self.settings.input_bucket}/{key}'

    def submit_run(self, profile, *, request_id, task_id, output_prefix, parameters):
        if not profile.account_verified:
            raise ProviderError('profile_unverified')
        if profile not in self.settings.profiles or set(parameters) != set(profile.parameters) or any(not isinstance(v, str) for v in parameters.values()):
            raise ProviderError('invalid_workflow_parameters')
        prefix = object_key(identity(output_prefix).removesuffix('/')) + '/'
        payload = dict(requestId=identity(request_id,128), workflowId=profile.workflow_id, workflowType=profile.workflow_type, roleArn=self.settings.role_arn, name=identity(task_id,128), outputUri=f's3://{self.settings.output_bucket}/{prefix}', parameters=parameters)
        if profile.workflow_version:
            payload['workflowVersionName'] = profile.workflow_version
        result = self._call('omics', 'start_run', uncertain=True, **payload)
        try:
            run_id = identity(result.get('id'))
        except ProviderError:
            raise ProviderError('submission_unknown', uncertain=True) from None
        return dict(run_id=run_id, arn=result.get('arn'), uuid=result.get('uuid'), run_output_uri=result.get('runOutputUri'), status=result.get('status'))

    def get_run(self, run_id):
        result = self._call('omics', 'get_run', id=identity(run_id))
        safe = dict(run_id=result.get('id', run_id), status=result.get('status'), run_output_uri=result.get('runOutputUri'))
        for source, target in (('name','name'), ('workflowId','workflow_id'), ('workflowType','workflow_type'), ('workflowVersionName','workflow_version')):
            if source in result:
                safe[target] = result[source]
        if 'parameters' in result:
            try:
                encoded = json.dumps(result['parameters'], sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
                safe['parameters_sha256'] = hashlib.sha256(encoded).hexdigest()
            except (TypeError, ValueError):
                raise ProviderError('invalid_run_parameters') from None
        for key in ('creationTime', 'startTime', 'stopTime', 'arn', 'uuid'):
            if key in result:
                safe[key] = result[key]
        return safe

    def cancel_run(self, run_id):
        self._call('omics', 'cancel_run', id=identity(run_id))

    def list_outputs(self, run_output_uri):
        parsed = urlsplit(identity(run_output_uri))
        if parsed.scheme != 's3' or parsed.netloc != self.settings.output_bucket or parsed.query or parsed.fragment:
            raise ProviderError('invalid_output_uri')
        prefix = object_key(parsed.path.lstrip('/').rstrip('/')) + '/'
        results, token, seen, pages = [], None, set(), 0
        while True:
            pages += 1
            if pages > 10000:
                raise ProviderError('provider_page_limit')
            params = dict(Bucket=self.settings.output_bucket, Prefix=prefix)
            if token:
                params['ContinuationToken'] = token
            page = self._call('s3', 'list_objects_v2', **params)
            for p in page.get('Contents', []):
                key = object_key(p['Key'])
                if not key.startswith(prefix):
                    raise ProviderError('invalid_output_scope')
                results.append(dict(key=key, size_bytes=p['Size'], etag=p.get('ETag')))
            if len(results) > 10000:
                raise ProviderError('provider_page_limit')
            if not page.get('IsTruncated'):
                return results
            token = page.get('NextContinuationToken')
            if not token or token in seen:
                raise ProviderError('invalid_provider_pagination')
            seen.add(token)

    def stream_output(self, key, *, expected_etag: str | None = None):
        params = dict(Bucket=self.settings.output_bucket, Key=object_key(key))
        if expected_etag is not None:
            params['IfMatch'] = identity(expected_etag)
        return self._call('s3', 'get_object', **params)['Body']
