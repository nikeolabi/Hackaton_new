"""Read official FHIR package artifacts (StructureDefinition JSON) from an on-disk .tgz.

This inspects profile metadata and required elements. It is not a substitute for the
FHIR Validator and does not auto-generate clinical mappings from profiles.
"""
from __future__ import annotations
import json
from pathlib import Path
import tarfile


def inspect_package(package_path: str | Path, canonical_urls: list[str], expected_package: str, expected_version: str):
    wanted = set(canonical_urls)
    found = {}
    with tarfile.open(package_path, 'r:gz') as tgz:
        manifest = next((m for m in tgz.getmembers() if m.name.endswith('package/package.json')), None)
        if not manifest: raise ValueError('FHIR package.json missing from package')
        pkg = json.load(tgz.extractfile(manifest))
        if pkg.get('name') != expected_package or pkg.get('version') != expected_version:
            raise ValueError(f'Wrong package: {pkg.get("name")}#{pkg.get("version")}, expected {expected_package}#{expected_version}')
        for member in tgz.getmembers():
            if not member.name.split('/')[-1].startswith('StructureDefinition-') or not member.name.endswith('.json'): continue
            try: obj = json.load(tgz.extractfile(member))
            except (ValueError, TypeError): continue
            if obj.get('resourceType') != 'StructureDefinition' or obj.get('url') not in wanted: continue
            elements = obj.get('snapshot', {}).get('element') or obj.get('differential', {}).get('element') or []
            found[obj['url']] = {
                'name': obj.get('name'), 'kind': obj.get('kind'), 'type':obj.get('type'),
                'derivation':obj.get('derivation'),
                'required_element_paths': sorted({x['path'] for x in elements if x.get('min', 0) >= 1 and x.get('path')}),
                'must_support_paths': sorted({x['path'] for x in elements if x.get('mustSupport') and x.get('path')}),
                'element_count':len(elements)}
    return {'package':f'{expected_package}#{expected_version}', 'found_profiles':found,
            'missing_profiles':sorted(wanted - found.keys()),
            'note':'Inspection only. HL7 FHIR Validator performs actual conformance and terminology validation.'}
