"""Auditable code enrichment for EU EPS FHIR candidate resources.

Mappings are explicit and exact: no text similarity, no inferred medical facts.
Keep the original NPU/ICD-10-SE/ATC/KVÅ codes and append reviewed codes.
"""
from __future__ import annotations

SNOMED = "http://snomed.info/sct"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"


def _codeable_add(codeable: dict, system: str, code: str, display: str | None = None) -> bool:
    if not code or not system:
        return False
    coding = codeable.setdefault('coding', [])
    if any(c.get('system') == system and c.get('code') == str(code) for c in coding):
        return False
    entry = {'system': system, 'code': str(code)}
    if display:
        entry['display'] = str(display)
    coding.append(entry)
    return True


def _unit_matches(expected: str | None, actual: str | None) -> bool:
    return str(expected or '').strip() == str(actual or '').strip()


def enrich_laboratory(resource: dict, fact: dict, cfg: dict, report: list) -> None:
    """Requires exact source test name and source unit to avoid wrong specimen/unit coding."""
    name = str(fact.get('name') or '').strip()
    unit = str(fact.get('unit') or '').strip()
    mapping = cfg.get('terminology_enrichment', {}).get('laboratory_exact', {}).get(name+'|'+unit)
    if not mapping:
        return
    if _codeable_add(resource['code'], LOINC, mapping['loinc'], mapping.get('display')):
        report.append({'kind':'laboratory','source_path':fact.get('source_path'), 'target':'Observation.code',
                       'system':LOINC, 'code':mapping['loinc'], 'rule':name+'|'+unit})
    quantity = resource.get('valueQuantity')
    if quantity is not None and mapping.get('ucum') and _unit_matches(unit, mapping.get('ucum')):
        # Set UCUM only when the original unit string already matches exactly.
        quantity['system'] = UCUM
        quantity['code'] = mapping['ucum']


def enrich_medication(resource: dict, fact: dict, cfg: dict, report: list) -> None:
    """Add reviewed RxNorm product code, never code a Swedish brand by loose matching."""
    name = str(fact.get('name') or '').strip()
    mapping = cfg.get('terminology_enrichment', {}).get('medication_exact', {}).get(name)
    if not mapping:
        return
    if not mapping.get('rxcui'):
        return
    # An RxNorm *product* assertion is unsafe when strength/form differ.
    for field in ('strength', 'strength_unit', 'form'):
        expected = mapping.get(field)
        if expected is not None and str(fact.get(field) or '').strip() != str(expected).strip():
            report.append({'kind':'medication','source_path':fact.get('source_path'),
                           'status':'skipped_strength_or_form_mismatch', 'field':field,'name':name})
            return
    if _codeable_add(resource['code'], RXNORM, str(mapping['rxcui']), mapping.get('display')):
        report.append({'kind':'medication','source_path':fact.get('source_path'), 'target':'Medication.code',
                       'system':RXNORM, 'code':str(mapping['rxcui']), 'rule':name})


def enrich_procedure(resource: dict, fact: dict, cfg: dict, report: list) -> None:
    mapping = cfg.get('terminology_enrichment', {}).get('procedure_exact', {}).get(str(fact.get('code') or ''))
    if mapping and mapping.get('snomed'):
        if _codeable_add(resource['code'], SNOMED, str(mapping['snomed']),mapping.get('display')):
            report.append({'kind':'procedure','source_path':fact.get('source_path'), 'target':'Procedure.code',
                           'system':SNOMED, 'code':str(mapping['snomed'])})


def enrich_condition(resource: dict, fact: dict, cfg: dict, report: list) -> None:
    mapping = cfg.get('terminology_enrichment', {}).get('condition_icd10_exact', {}).get(str(fact.get('code') or ''))
    if mapping and mapping.get('snomed'):
        if _codeable_add(resource['code'], SNOMED, str(mapping['snomed']),mapping.get('display')):
            report.append({'kind':'condition','source_path':fact.get('source_path'), 'target':'Condition.code',
                           'system':SNOMED, 'code':str(mapping['snomed']), 'reviewed':True})
