"""Optional SNOMED CT checks using a local Snowstorm Lite FHIR endpoint.

No automatic coding of arbitrary text, ICD-10 -> SNOMED crosswalk, or network
calls unless the user explicitly configures a Snowstorm URL.
"""
from __future__ import annotations
import json
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

SNOMED = 'http://snomed.info/sct'


def validate_snomed_code(base_url: str, code: str, *, timeout: float=8.0):
    """Call FHIR R4 CodeSystem/$validate-code; return a structured result.

    Backend routing differs by Snowstorm deployment; configure --snowstorm-url
    as its FHIR API base, e.g. http://localhost:8080/fhir.
    """
    if not str(code).isdigit():
        return {'code':code, 'status':'skipped', 'reason':'Not a numeric SNOMED CT concept identifier'}
    parsed = urlsplit(base_url)
    if parsed.scheme not in ('http','https') or not parsed.netloc:
        raise ValueError('Snowstorm URL must be an HTTP(S) URL')
    params = urlencode({'url': SNOMED, 'code': str(code)})
    endpoint = base_url.rstrip('/') + '/CodeSystem/$validate-code?' + params
    req = Request(endpoint, headers={'Accept':'application/fhir+json'})
    try:
        with urlopen(req, timeout=timeout) as response:
            data = json.load(response)
        values = {x.get('name'):x.get('valueBoolean',x.get('valueString')) for x in data.get('parameter', [])}
        return {'code':str(code), 'status':'checked', 'valid':values.get('result'),
                'message':values.get('message'), 'display':values.get('display')}
    except Exception as exc:
        return {'code':str(code), 'status':'unavailable', 'error':str(exc)}


def reviewed_mapping_checks(canonical: dict, cfg: dict, snowstorm_url: str | None):
    """Only review explicitly approved code mappings; never guess text matches."""
    mapping = cfg.get('reviewed_snomed_mappings', {})
    entries = sorted((k, str(v)) for k, v in mapping.items() if v)
    codes = sorted(set(v for _, v in entries))
    if not codes:
        return {'enabled':bool(snowstorm_url), 'results':[], 'verified_mappings':{},
                'note':'No approved SNOMED mappings configured; source codes retained unchanged.'}
    if not snowstorm_url:
        return {'enabled':False, 'verified_mappings':{}, 'results':[{'code':c,'status':'not_checked'} for c in codes],
                'note':'Pass --snowstorm-url to check reviewed SNOMED mappings.'}
    results = [validate_snomed_code(snowstorm_url,c) for c in codes]
    accepted = {r['code'] for r in results if r.get('status') == 'checked' and r.get('valid') is True}
    verified = {key: val for key, val in entries if val in accepted}
    return {'enabled':True, 'results':results, 'verified_mappings':verified}
