"""Extract source-independent clinical facts using versioned mapping metadata.

Input: consolidated patient JSON produced by patient_grouping.py.
Output: canonical patient dictionary + explicit unmapped / source lineage reports.
No clinical interpretations are inferred from free text.
"""
from __future__ import annotations
from collections import Counter
from typing import Any
import re


def get(obj: Any, path: str, default=None):
    """Minimal dot-path accessor, intentionally not a general expression evaluator."""
    current = obj
    for part in path.split('.'):
        if not isinstance(current, dict):
            return default
        current = current.get(part)
        if current is None:
            return default
    return current


def many(obj):
    if obj is None: return []
    return obj if isinstance(obj, list) else [obj]


def date(raw):
    if raw is None or raw == '': return None
    s = str(raw)
    if len(s) >= 8 and s[:8].isdigit(): return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    if len(s) >= 10 and re.fullmatch(r'\d{4}-\d\d-\d\d', s[:10]): return s[:10]
    return None


def numeric(raw):
    try:
        return float(str(raw).replace(',', '.').strip())
    except (ValueError, TypeError):
        return None


def _source_index(source, i, kind):
    return {'source_index': i, 'record_type': source.get('recordType'), 'kind': kind}


def patient_name_from_sources(patient: dict):
    """Find a patient name only in patient-labelled structures, never provider/user names.

    The normalized JSON has heterogeneous XML/JSON source payloads.  For now this
    searches explicit patient objects in sourceData/records; it does not guess
    names from adjacent metadata or attempt to split a full name.
    """
    found = []
    def walk(node, path, depth=0):
        if depth > 35:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                key_low = key.lower()
                child_path = f'{path}.{key}'
                if key_low == 'patient' and isinstance(value, dict):
                    for name_key in ('fullName', 'full_name', 'patientName', 'patient_name'):
                        name = value.get(name_key)
                        if isinstance(name, str) and name.strip():
                            found.append((name.strip(), f'{child_path}.{name_key}'))
                    # Also support explicitly identified given/family names.
                    given = value.get('firstName') or value.get('first_name')
                    family = value.get('lastName') or value.get('last_name')
                    if isinstance(given, str) or isinstance(family, str):
                        name = ' '.join(x.strip() for x in (given, family) if isinstance(x, str) and x.strip())
                        if name: found.append((name, child_path))
                walk(value, child_path, depth + 1)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f'{path}[{i}]', depth + 1)
    for i, source in enumerate(patient['sources']):
        # Avoid traversing redundant, lossless XML trees unless necessary.
        for field in ('sourceData', 'records'):
            if field in source:
                walk(source[field], f'$.sources[{i}].{field}')
    if not found:
        return None, None, []
    names = list(dict.fromkeys(name for name, _ in found))
    if len(names) > 1:
        return None, None, names
    return found[0][0], found[0][1], []


def extract(patient: dict, cfg: dict):
    if not isinstance(patient.get('sources'), list):
        raise ValueError('Expected consolidated patient with sources[]')
    pid = str(patient.get('patientId') or '').strip()
    if not pid: raise ValueError('Missing patientId')
    result = {'patient_id': pid, 'medications': [], 'conditions': [],
              'laboratory': [], 'procedures': [], 'vitals': [], 'plans': [],
              'unknown_sources': [], 'review': [], 'provenance': [],
              'source_summary': dict(Counter(str(s.get('recordType')) for s in patient['sources']))}
    name, name_source, conflicts = patient_name_from_sources(patient)
    result['patient_name'] = name
    result['patient_name_source'] = name_source
    if conflicts:
        result['review'].append({'reason': 'Conflicting patient names in source records', 'values': conflicts})
    elif not name:
        result['review'].append({'reason': 'Patient name not present in source records; export uses explicit missing-name placeholder'})
    pat = cfg['source_patterns']
    for si, source in enumerate(patient['sources']):
        record_type = str(source.get('recordType', ''))
        if re.fullmatch(pat['medications'], record_type):
            mapping = cfg['medication']
            for ri, record in enumerate(many(source.get('records'))):
                for di, drug in enumerate(many(get(record, mapping['drug_list']))):
                    if not isinstance(drug, dict): continue
                    rx = get(record, mapping['prescription'], {}) or {}
                    lines = [get(day, mapping['instruction_text']) for day in many(get(record, mapping['instructions']))]
                    lines = [str(t) for t in lines if t]
                    item = {'name': drug.get(mapping['name']), 'atc': drug.get(mapping['atc']),
                            'strength': drug.get(mapping['strength']), 'strength_unit': drug.get(mapping['strength_unit']),
                            'form': drug.get(mapping['dose_form']), 'start': date(rx.get(mapping['start'])),
                            'end': date(rx.get(mapping['end'])), 'reason_original': rx.get(mapping['treatment_reason']),
                            'instructions': list(dict.fromkeys(lines)), 'source_document_id': record.get('document_id'),
                            'source_path': f'$.sources[{si}].records[{ri}].drugs.drug[{di}]'}
                    if item['name'] or item['atc']:
                        result['medications'].append(item)
                        result['provenance'].append({'kind': 'medication', 'source_path': item['source_path']})
                    if item['reason_original'] and 'pacemaker' in str(item['reason_original']).lower():
                        result['review'].append({'reason': 'Medication indication may describe a device, not a medical indication', 'source_path': item['source_path']})
        elif re.fullmatch(pat['care_documents'], record_type):
            mapping = cfg['care']
            for ri, record in enumerate(many(source.get('records'))):
                keywords = many(get(record, mapping['keywords']))
                op_date = next((date(get(v, mapping['value'])) for k in keywords if get(k, mapping['name']) in mapping['procedure_date_labels'] for v in many(get(k,mapping['values'])) if date(get(v,mapping['value']))), None)
                for ki, keyword in enumerate(keywords):
                    label = get(keyword, mapping['name'])
                    values = many(get(keyword, mapping['values']))
                    for vi, val in enumerate(values):
                        raw = get(val, mapping['value'])
                        if raw is None: continue
                        source_path = f'$.sources[{si}].records[{ri}].keywords[{ki}].values[{vi}]'
                        fact = {'source_path': source_path, 'source_document_id': record.get('document_id')}
                        if label in mapping['diagnosis_labels']:
                            m = re.match(r'^([A-Z]\d{2}\d{0,2})\s+(.+)$', str(raw))
                            if m: result['conditions'].append({**fact, 'code': m.group(1), 'display': m.group(2), 'date': date(get(record,mapping['event_date']))})
                            else: result['review'].append({'reason': 'Cannot parse diagnosis code', 'source_path': source_path, 'raw': raw})
                        elif label in mapping['procedure_labels']:
                            m = re.match(r'^([A-Z]{2,3}[0-9]{2})\s+(.+)$', str(raw))
                            result['procedures'].append({**fact, 'code': m.group(1) if m else None,
                                'description': m.group(2) if m else str(raw), 'date': op_date or date(get(record,mapping['event_date']))})
                        elif label in cfg['vital_signs'] and numeric(raw) is not None:
                            result['vitals'].append({**fact, 'name': label, 'value': numeric(raw),
                                'date': date(get(record,mapping['event_date'])), 'unit_source': val.get('unit')})
                        elif label in mapping['plan_labels']:
                            result['plans'].append({**fact, 'name': label, 'text': str(raw), 'date': date(get(record,mapping['event_date']))})
        elif re.fullmatch(pat['laboratory'], record_type):
            mapping = cfg['laboratory']
            for ai, sample in enumerate(many(get(source, mapping['samples']))):
                for aj, analysis in enumerate(many(get(sample, mapping['analyses']))):
                    raw = get(analysis, mapping['value'])
                    if raw is None: continue
                    item = {'name': get(analysis, mapping['name']), 'code': get(analysis, mapping['code']),
                            'value': numeric(raw), 'original_value': raw,
                            'unit': get(analysis, mapping['unit']),
                            'reference_range': get(analysis, mapping['reference_range']),
                            'date': date(get(source, mapping['date'])),
                            'source_path': f'$.sources[{si}].sourceData.samples[{ai}].analyses[{aj}]',
                            'source_record_type': record_type,
                            'is_final': get(source, mapping['final'])}
                    result['laboratory'].append(item)
                    if item['value'] is not None and not item['unit']:
                        result['review'].append({'reason': 'Numeric lab result has no reported unit', 'source_path': item['source_path']})
        else:
            result['unknown_sources'].append(_source_index(source, si, 'unmapped'))
    return result
