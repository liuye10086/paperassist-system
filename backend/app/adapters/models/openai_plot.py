"""Narrow, single-effect Code Interpreter calls over the official endpoint."""
import json
import re

from httpx2 import TransportError
from openai import APIConnectionError, APIStatusError

from app.adapters.models.openai_responses import (
    ModelProviderError, OpenAIResponsesProvider, RESPONSE_ID, canonical_payload, safe_request_id,
)
from app.adapters.openai_plot import PROMPT_VERSION

CONTAINER_ID = re.compile(r'cntr_[A-Za-z0-9_-]{1,200}\Z')
FILE_ID = re.compile(r'cfile_[A-Za-z0-9_-]{1,200}\Z')


def valid_file_path(path):
    return (isinstance(path, str) and 1 <= len(path) <= 1024 and path.startswith('/mnt/data/')
            and not path.endswith('/') and not any(part in ('.', '..') for part in path.split('/'))
            and not any(ord(char) < 32 or ord(char) == 127 or char == '\\' for char in path))


def _identifier(value, pattern):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ModelProviderError('plot_receipt_invalid')
    return value


def _policy(policy):
    if (policy.tools != ['code_interpreter'] or policy.output_format != 'text'
            or policy.prompt_version != PROMPT_VERSION):
        raise ModelProviderError('model_tools_unsupported')


def _failure(exc, *, container=False):
    code = 'plot_container_expired' if container and getattr(exc, 'status_code', None) in (404, 410) else 'model_provider_request_failed'
    return ModelProviderError(code, request_id=getattr(exc, 'request_id', None),
                              status_code=getattr(exc, 'status_code', None))


class OpenAIPlotProvider(OpenAIResponsesProvider):
    def create_container(self, *, policy, call_id):
        _policy(policy)
        if not isinstance(call_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', call_id):
            raise ModelProviderError('model_input_invalid')
        try:
            response = self.client.containers.create(name='paperassist-' + call_id, memory_limit='1g',
                expires_after={'anchor': 'last_active_at', 'minutes': 20},
                network_policy={'type': 'disabled'}, timeout=policy.timeout_seconds)
            return {'container_id': _identifier(response.id, CONTAINER_ID),
                    'request_id': safe_request_id(getattr(response, '_request_id', None))}
        except (APIConnectionError, APIStatusError) as exc:
            raise _failure(exc) from None

    def upload_input(self, *, container_id, payload, policy):
        _policy(policy)
        _identifier(container_id, CONTAINER_ID)
        try:
            content = canonical_payload(payload).encode('utf-8')
        except (TypeError, ValueError, RecursionError):
            raise ModelProviderError('model_input_invalid') from None
        try:
            response = self.client.containers.files.create(container_id,
                file=('data.json', content, 'application/json'), timeout=policy.timeout_seconds)
            if response.container_id != container_id or not valid_file_path(response.path):
                raise ModelProviderError('plot_receipt_invalid')
            return {'input_file_id': _identifier(response.id, FILE_ID), 'input_file_path': response.path,
                    'request_id': safe_request_id(getattr(response, '_request_id', None))}
        except (APIConnectionError, APIStatusError) as exc:
            raise _failure(exc, container=True) from None

    def create_plot(self, *, policy, instructions, container_id, input_file_path):
        _policy(policy)
        _identifier(container_id, CONTAINER_ID)
        if not isinstance(instructions, str) or not instructions.strip() or not valid_file_path(input_file_path):
            raise ModelProviderError('model_input_invalid')
        try:
            response = self.client.responses.create(model=policy.model, background=True, store=True,
                instructions=instructions, input='Use the python tool to read the uploaded JSON file at '
                + json.dumps(input_file_path) + ' (this is the data.json input), calculate and produce both required files.',
                tools=[{'type': 'code_interpreter', 'container': container_id}],
                tool_choice={'type': 'code_interpreter'}, include=['code_interpreter_call.outputs'],
                max_output_tokens=policy.max_output_tokens, timeout=policy.timeout_seconds)
            return self._receipt(response)
        except (APIConnectionError, APIStatusError) as exc:
            raise _failure(exc) from None

    def retrieve(self, response_id, *, policy):
        _policy(policy)
        _identifier(response_id, RESPONSE_ID)
        try:
            return self._receipt(self.client.responses.retrieve(response_id,
                include=['code_interpreter_call.outputs'], timeout=policy.timeout_seconds))
        except (APIConnectionError, APIStatusError) as exc:
            raise _failure(exc) from None

    def download(self, file_id, container_id, limit, *, policy):
        _policy(policy)
        _identifier(file_id, FILE_ID)
        _identifier(container_id, CONTAINER_ID)
        if type(limit) is not int or not 0 < limit <= 12 * 1024 * 1024:
            raise ModelProviderError('model_input_invalid')
        try:
            chunks, size = [], 0
            with self.client.containers.files.content.with_streaming_response.retrieve(file_id,
                    container_id=container_id, timeout=policy.timeout_seconds) as response:
                for chunk in response.iter_bytes(chunk_size=65536):
                    size += len(chunk)
                    if size > limit:
                        raise ModelProviderError('plot_output_limit')
                    chunks.append(chunk)
            return b''.join(chunks)
        except (APIConnectionError, APIStatusError) as exc:
            raise _failure(exc, container=True) from None
        except TransportError:
            raise ModelProviderError() from None
