"""Versioned execution identities and bounded, credential-free payloads."""
import hashlib
import json
from pathlib import Path

CHECKPOINT_LIMIT = 16 * 1024
RESULT_LIMIT = 4 * 1024 * 1024
VERSION = 1
TERMINAL = {'completed', 'skipped', 'permanent_failed'}
STAGES = ('structured_sources', 'company_crawling', 'processing_scoring',
          'contact_enrichment', 'supabase_persistence', 'export')
_FORBIDDEN = {'headers', 'raw_html', 'html', 'authorization', 'password', 'secret',
              'supabase_secret_key', 'api_key', 'access_token', 'refresh_token', 'token'}


def validate_payload(value: dict, *, result: bool = False) -> None:
    if not isinstance(value, dict):
        raise ValueError('payload must be an object')
    def walk(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key.lower() in _FORBIDDEN:
                    raise ValueError('forbidden payload field')
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(value)
    # Default separators mirror jsonb's textual spacing conservatively.
    if len(json.dumps(value, ensure_ascii=False).encode()) > (RESULT_LIMIT if result else CHECKPOINT_LIMIT):
        raise ValueError('result_too_large' if result else 'checkpoint_too_large')


def fingerprint(config: dict) -> str:
    safe = {k:v for k,v in config.items() if k not in {
        'workers', 'supabase_secret_key', 'supabase_url', 'interactive', 'fresh'}}
    return hashlib.sha256(json.dumps(safe, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def behavior_version() -> str:
    root = Path(__file__).resolve().parents[1]
    files = [*root.glob('*.py'), *root.glob('adapters/*.py'), *root.glob('contacts/*.py'),
             *root.glob('crawling/*.py'), *root.glob('execution/*.py'), *root.glob('storage/*.py')]
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def task(key, stage, *, identifier='', domain=None, checkpoint=None):
    return {'task_key': key, 'task_type': stage, 'stage': stage,
            'identifier': identifier, 'domain': domain, 'checkpoint_json': checkpoint or {}}
