import pytest
from impurity_leads.execution.tasks import fingerprint, validate_payload, CHECKPOINT_LIMIT
from impurity_leads.execution.retry import classify_error, TaskFailure
import httpx
import ssl


def test_checkpoint_rejects_large_body_and_sensitive_keys():
    for data in [{'cursor':'x'*(CHECKPOINT_LIMIT+1)}, {'headers':{}}, {'raw_html':'<p>'}, {'token':'secret'}]:
        with pytest.raises(ValueError):
            validate_payload(data)
    validate_payload({'page_token':'public-pagination-cursor','index':3})


def test_run_fingerprint_is_order_stable_excludes_workers_and_secrets():
    assert fingerprint({'seeds':['a'], 'workers':1, 'supabase_secret_key':'a'}) == fingerprint({'supabase_secret_key':'b','workers':6,'seeds':['a']})
    assert fingerprint({'seeds':['a']}) != fingerprint({'seeds':['b']})


@pytest.mark.parametrize('status,retryable,skip', [(403,False,True),(429,True,False),(503,True,False),(404,False,True)])
def test_http_failure_classification(status,retryable,skip):
    response=httpx.Response(status,request=httpx.Request('GET','https://example.com'))
    error=httpx.HTTPStatusError('sensitive content',request=response.request,response=response)
    failure=classify_error(error)
    assert failure.retryable is retryable
    assert failure.skipped is skip
    assert 'sensitive' not in failure.code


def test_tls_never_retried_or_weakened():
    assert not classify_error(ssl.SSLError('handshake')).retryable
    outer=httpx.ConnectError('do not log')
    outer.__cause__=ssl.SSLCertVerificationError('certificate')
    assert classify_error(outer).code == 'tls_error'


@pytest.mark.parametrize('exception', [httpx.ReadError, httpx.WriteError, httpx.CloseError, httpx.RemoteProtocolError])
def test_transient_stream_network_failures_are_retryable(exception):
    failure = classify_error(exception('sensitive connection contents'))
    assert failure.retryable
    assert failure.code == 'connect_error'
    assert 'sensitive' not in failure.code


def test_local_protocol_misuse_remains_permanent():
    assert not classify_error(httpx.LocalProtocolError('invalid caller request')).retryable
