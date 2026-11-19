"""FHIR R4 EU EPS document candidate builder from canonical patient facts.

FHIR structure needs human-reviewed implementation logic; the metadata config governs
codes/profile URLs/source mappings, not magic schema-to-clinical-semantic inference.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, date
from html import escape
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo
import re

NAMESPACE = UUID('a1d266b0-22bb-4c54-9d8d-28c2435024c1')
SECTIONS = [
 ('Allergies and intolerances', '48765-2'), ('Problem list', '11450-4'),
 ('Medication list', '10160-0'), ('Immunizations', '11369-6'),
 ('Relevant diagnostic tests and laboratory data', '30954-2'),
 ('Medical devices', '46264-8'), ('Plan of care', '18776-5'),
 ('History of procedures', '47519-4')]


def narrative(text):
    return {'status': 'generated', 'div': '<div xmlns="http://www.w3.org/1999/xhtml"><p>' + escape(str(text)) + '</p></div>'}


def codeable(system, code, display=None):
    result = {'text': str(display or code or '')}
    if code:
        coding = {'code': str(code)}
        if system: coding['system'] = system
        if display: coding['display'] = str(display)
        result['coding'] = [coding]
    return result


def build(canonical: dict, cfg: dict, *, vitals_as_narrative=True, document_date=None, verified_snomed=None):
    pid = canonical['patient_id']
    verified_snomed = verified_snomed or {}
    eps = cfg['eps']; systems = cfg['terminology_systems']
    document_date = document_date or datetime.now(ZoneInfo('Europe/Stockholm')).replace(microsecond=0).isoformat()
    dt = datetime.fromisoformat(document_date)
    if not dt.tzinfo or dt.utcoffset() is None: raise ValueError('--document-date must include timezone')
    def rid(name): return str(uuid5(NAMESPACE, pid + ':dynamic:' + name))
    def urn(name): return 'urn:uuid:' + rid(name)
    entries = []; fhir_paths = {}; report = []
    patient_ref = urn('patient'); org_ref = urn('organization')
    def add(resource, key, source=None):
        resource['id'] = rid(key)
        ref = urn(key)
        entries.append({'fullUrl': ref, 'resource': resource})
        if source: fhir_paths[ref] = source
        return ref
    sections = {title: {'title': title, 'code': codeable('http://loinc.org', code),
                          'text': narrative('Not documented in supplied source records.')}
                for title, code in SECTIONS}
    texts = defaultdict(list)
    refs = defaultdict(list)
    def attach(section, reference, text):
        if reference: refs[section].append({'reference': reference})
        texts[section].append(str(text))
    patient = {'resourceType': 'Patient', 'meta': {'profile': [eps['patient_profile']]},
               'identifier': [{'system': 'http://electronichealth.se/identifier/personnummer', 'value': pid}],
               'text': narrative('Patient summary; patient identifier recorded in source.')}
    if canonical.get('patient_name'):
        patient['name'] = [{'text': canonical['patient_name']}]
    else:
        # The IPS/EPS patient profile requires name.text/given/family. Never
        # represent a placeholder as an actual personal name: mark it clearly
        # as an unavailable value and preserve this issue in the mapping report.
        patient['name'] = [{
            'text': 'Name not provided in source',
            'extension': [{
                'url': 'http://hl7.org/fhir/StructureDefinition/data-absent-reason',
                'valueCode': 'unknown'
            }]
        }]
    # Only derive birth date from a format-valid identifier; don't infer sex.
    if re.fullmatch(r'\d{12}', pid):
        try: patient['birthDate'] = date(int(pid[:4]), int(pid[4:6]), int(pid[6:8])).isoformat()
        except ValueError: pass
    org = {'resourceType': 'Organization', 'name': 'Source healthcare organization (not identified)',
           'text': narrative('Source healthcare organization not identified')}
    add(patient, 'patient', '$.patientId')
    add(org, 'organization')

    for i, fact in enumerate(canonical['conditions']):
        resource = {'resourceType': 'Condition',
                    'meta': {'profile': ['http://hl7.eu/fhir/base/StructureDefinition/condition-eu-core']},
                    'code': codeable(systems['icd10_se'], fact['code'], fact['display']),
                    'subject': {'reference': patient_ref}, 'text': narrative(fact['display'])}
        verified_code = verified_snomed.get('ICD10SE:' + str(fact['code']))
        if verified_code:
            resource['code']['coding'].append({'system': systems['snomed'], 'code': str(verified_code)})
        if fact.get('date'): resource['recordedDate'] = fact['date']
        ref = add(resource, f'condition:{i}', fact['source_path'])
        attach('Problem list', ref, f"{fact['code']} {fact['display']}")

    for i, fact in enumerate(canonical['medications']):
        name = fact.get('name') or fact.get('atc') or 'Unspecified medication'
        desc = ' '.join(str(x) for x in (name, fact.get('strength'), fact.get('strength_unit'), fact.get('form')) if x is not None and str(x).strip())
        med = {'resourceType': 'Medication',
               'meta': {'profile': ['http://hl7.eu/fhir/base/StructureDefinition/medication-eu-core']},
               'code': codeable(systems['atc'], fact.get('atc'), desc), 'text': narrative(desc)}
        med_ref = add(med, f'medication:{i}', fact['source_path'])
        statement = {'resourceType': 'MedicationStatement', 'meta': {'profile': [eps['medication_statement_profile']]},
                     'status': 'completed' if fact.get('end') else 'unknown',
                     'subject': {'reference': patient_ref},
                     'medicationReference': {'reference': med_ref, 'display': desc},
                     'text': narrative(desc),
                     'dosage': [{'text': '; '.join(fact['instructions']) or 'Dosage not documented'}]}
        period = {k: fact[v] for k, v in [('start','start'), ('end','end')] if fact.get(v)}
        if period: statement['effectivePeriod'] = period
        if fact.get('reason_original'): statement['reasonCode'] = [{'text': fact['reason_original']}]
        if fact.get('source_document_id'): statement['identifier'] = [{'value': str(fact['source_document_id'])}]
        ref = add(statement, f'medication-statement:{i}', fact['source_path'])
        attach('Medication list', ref, desc + '; ' + ('; '.join(fact['instructions']) or 'dosage unspecified'))

    for i, fact in enumerate(canonical['laboratory']):
        system = systems['npu'] if str(fact.get('code') or '').startswith('NPU') else None
        resource = {'resourceType': 'Observation',
                    'meta': {'profile': ['http://hl7.eu/fhir/base/StructureDefinition/medicalTestResult-eu-core']},
                    'status': 'preliminary' if fact.get('is_final') is False else 'final',
                    'category': [codeable('http://terminology.hl7.org/CodeSystem/observation-category', 'laboratory', 'Laboratory')],
                    'code': codeable(system, fact.get('code'), fact.get('name')),
                    'subject': {'reference': patient_ref},
                    'performer': [{'reference': org_ref}],
                    'text': narrative(f"{fact.get('name')}: {fact.get('original_value')} {fact.get('unit') or ''}")}
        if fact.get('date'): resource['effectiveDateTime'] = fact['date']
        if fact.get('value') is not None:
            quantity = {'value': fact['value']}
            if fact.get('unit') and str(fact['unit']).strip(): quantity['unit'] = str(fact['unit']).strip()
            resource['valueQuantity'] = quantity
        else:
            resource['valueString'] = str(fact['original_value'])
        if fact.get('reference_range'): resource['referenceRange'] = [{'text': str(fact['reference_range'])}]
        ref = add(resource, f'laboratory:{i}', fact['source_path'])
        attach('Relevant diagnostic tests and laboratory data', ref,
               f"{fact.get('name')}: {fact.get('original_value')} {fact.get('unit') or ''}")

    vitals = cfg['vital_signs']
    bp_by_date = defaultdict(dict)
    for i, fact in enumerate(canonical['vitals']):
        mapping = vitals[fact['name']]
        label = fact['name']
        if label.startswith('Blodtryck'):
            bp_by_date[(fact.get('date'), fact.get('source_document_id'))][mapping['loinc']] = fact
            continue
        text = f"{label}: {fact['value']} {mapping['unit']}"
        if vitals_as_narrative:
            attach('Relevant diagnostic tests and laboratory data', None, text)
            continue
        obs = {'resourceType':'Observation', 'meta': {'profile':['http://hl7.org/fhir/StructureDefinition/vitalsigns']},
               'status': 'final', 'category':[codeable('http://terminology.hl7.org/CodeSystem/observation-category','vital-signs','Vital Signs')],
               'code': codeable(systems['loinc'],mapping['loinc'],mapping['display']),
               'subject': {'reference': patient_ref},
               'valueQuantity': {'value': fact['value'], 'unit': mapping['unit'], 'system':'http://unitsofmeasure.org', 'code':mapping['ucum']},
               'text': narrative(text)}
        if fact.get('date'): obs['effectiveDateTime'] = fact['date']
        ref = add(obs, f'vital:{i}', fact['source_path'])
        attach('Relevant diagnostic tests and laboratory data',ref,text)
    for i, ((when, doc), bp) in enumerate(bp_by_date.items()):
        if '8480-6' not in bp or '8462-4' not in bp:
            for x in bp.values(): attach('Relevant diagnostic tests and laboratory data',None,f"{x['name']}: {x['value']} mmHg (incomplete BP pair)")
            continue
        text = f"Blood pressure: {bp['8480-6']['value']}/{bp['8462-4']['value']} mmHg"
        if vitals_as_narrative:
            attach('Relevant diagnostic tests and laboratory data',None,text)
            continue
        ob={'resourceType':'Observation','meta':{'profile':['http://hl7.org/fhir/StructureDefinition/bp']},
            'status':'final', 'category':[codeable('http://terminology.hl7.org/CodeSystem/observation-category','vital-signs','Vital Signs')],
            'code':codeable(systems['loinc'],'85354-9','Blood pressure panel'), 'subject':{'reference':patient_ref},
            'component':[{'code':codeable(systems['loinc'], c), 'valueQuantity':{'value':bp[c]['value'], 'unit':'mmHg','system':'http://unitsofmeasure.org','code':'mm[Hg]'}} for c in ('8480-6','8462-4')],
            'text':narrative(text)}
        if when:ob['effectiveDateTime']=when
        ref=add(ob, f'blood-pressure:{i}', bp['8480-6']['source_path']+'; '+bp['8462-4']['source_path'])
        attach('Relevant diagnostic tests and laboratory data',ref,text)

    for i, fact in enumerate(canonical['procedures']):
        resource={'resourceType':'Procedure','status':'completed','code':codeable(systems['kva'] if fact.get('code') else None,fact.get('code'),fact['description']),
                  'subject':{'reference':patient_ref}, 'text':narrative(fact['description'])}
        if fact.get('date'):resource['performedDateTime']=fact['date']
        ref=add(resource,f'procedure:{i}',fact['source_path'])
        attach('History of procedures',ref,fact['description'])
        if 'pacemaker' in fact['description'].lower():
            attach('Medical devices',None, 'Pacemaker implantation documented; current device-use status not established')
    for fact in canonical['plans']:
        attach('Plan of care',None,f"{fact['name']}: {fact['text']}")

    for title, sec in sections.items():
        if refs[title]:sec['entry']=refs[title]
        if texts[title]:
            sec['text']={'status':'generated','div':'<div xmlns="http://www.w3.org/1999/xhtml"><ul>'+''.join('<li>'+escape(s)+'</li>' for s in texts[title])+'</ul></div>'}
        if not refs[title]:
            sec['emptyReason']=codeable('http://terminology.hl7.org/CodeSystem/list-empty-reason','unavailable','Unavailable')

    composition={'resourceType':'Composition','meta':{'profile':[eps['composition_profile']]},
                 'status':'preliminary', 'identifier':{'system':'urn:ietf:rfc:3986','value':urn('identifier')},
                 'type':codeable('http://loinc.org','60591-5','Patient summary Document'),
                 'subject':{'reference':patient_ref}, 'date':document_date,
                 'author':[{'reference':org_ref}], 'custodian':{'reference':org_ref},
                 'title':'European Patient Summary (source-derived candidate)',
                 'section':list(sections.values()), 'text':narrative('Automatically mapped candidate; requires clinical review and official EU EPS validation.')}
    composition['id']=rid('composition')
    bundle={'resourceType':'Bundle','id':rid('bundle'), 'meta':{'profile':[eps['bundle_profile']]},
            'type':'document','language':'sv','identifier':{'system':'urn:ietf:rfc:3986','value':urn('identifier')},
            'timestamp':document_date,
            'entry':[{'fullUrl':urn('composition'),'resource':composition}] + entries}
    known={e['fullUrl'] for e in bundle['entry']}
    def check_refs(node):
        if isinstance(node,dict):
            if 'reference' in node and str(node['reference']).startswith('urn:uuid:') and node['reference'] not in known:
                raise ValueError('Missing referenced resource '+node['reference'])
            for x in node.values():check_refs(x)
        elif isinstance(node,list):
            for x in node:check_refs(x)
    if len(known)!=len(bundle['entry']):raise ValueError('Non-unique FHIR fullUrl')
    check_refs(bundle)
    return bundle, {'resource_counts':dict(Counter(e['resource']['resourceType'] for e in bundle['entry'])),
                    'resource_source_paths':fhir_paths, 'vitals_as_narrative':vitals_as_narrative}
