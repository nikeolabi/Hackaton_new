"""Configuration-driven EHR patient JSON -> canonical facts -> EU EPS FHIR candidate.

This is an incremental prototype, not a certified EHDS/EPS-conformant converter.
To use the real EU EPS StructureDefinitions provide --eps-package, then validate
FHIR output separately with the official HL7 validator.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import json
from collections import Counter
from dynamic_eps.canonical import extract
from dynamic_eps.fhir import build
from dynamic_eps.standards import inspect_package
from dynamic_eps.terminology import reviewed_mapping_checks

BASE = Path(__file__).resolve().parent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('patient_file', type=Path, help='Consolidated JSON with patientId and sources[]')
    ap.add_argument('--output-dir', type=Path, default=Path('output'))
    ap.add_argument('--mapping',type=Path,default=BASE/'config'/'mappings.json')
    ap.add_argument('--eps-package',type=Path,help='Official downloaded hl7.fhir.eu.eps#1.0.0-ballot .tgz')
    ap.add_argument('--snowstorm-url',help='Opt-in Snowstorm Lite FHIR base URL, e.g. http://localhost:8080/fhir')
    ap.add_argument('--structured-vitals', action='store_true', help='Experimental: emit separate vital-sign Observation resources; may fail IPS slice validation')
    ap.add_argument('--document-date', help='ISO timestamp with timezone')
    args=ap.parse_args(argv)
    cfg=json.loads(args.mapping.read_text(encoding='utf-8'))
    patient=json.loads(args.patient_file.read_text(encoding='utf-8'))
    canonical=extract(patient,cfg)
    terminology=reviewed_mapping_checks(canonical,cfg,args.snowstorm_url)
    bundle, fhir_report=build(canonical,cfg,vitals_as_narrative=not args.structured_vitals,document_date=args.document_date,verified_snomed=terminology.get('verified_mappings'))
    official_profiles={}
    if args.eps_package:
        eps=cfg['eps']
        official_profiles=inspect_package(args.eps_package,
           [eps['bundle_profile'],eps['composition_profile'],eps['patient_profile'],eps['medication_statement_profile']],
           eps['package_id'],eps['version'])
    coverage={
      'medicationSummary.medicationUse':len(canonical['medications']),
      'problemList.problem':len(canonical['conditions']),
      'observationResults.result':len(canonical['laboratory'])+len(canonical['vitals']),
      'procedures.procedure':len(canonical['procedures']),
      'planOfCare':len(canonical['plans'])}
    result={'status':'candidate_not_officially_validated','mapping_version':cfg['mapping_version'],
      'eps_package_required_for_official_validation':cfg['eps']['package_id']+'#'+cfg['eps']['version'],
      'source_records':canonical['source_summary'],
      'ehds_coverage_counts':coverage, 'ehds_reference_urls':cfg['ehds'],
      'ignored_sources':canonical['unknown_sources'], 'clinical_review':canonical['review'],
      'fhir':fhir_report,'eps_package_inspection':official_profiles,
      'snomed':terminology,
      'notes':['EHDS model mappings are curated, not executed automatically from web pages.',
               'Only explicitly reviewed SNOMED mappings are checked; no diagnosis is inferred.',
               'Run the official HL7 validator independently.']}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    stem=args.patient_file.stem
    paths={'canonical':args.output_dir/(stem+'_canonical.json'),
           'fhir':args.output_dir/(stem+'_eu_eps.json'),
           'report':args.output_dir/(stem+'_mapping_report.json')}
    for typ,obj in [('canonical',canonical),('fhir',bundle),('report',result)]:
        paths[typ].write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'outputs':{key:str(path) for key,path in paths.items()},
                      'resources':fhir_report['resource_counts'],
                      'unknown_source_types':list(sorted(set(x['record_type'] for x in canonical['unknown_sources']))),
                      'clinical_review_items':len(canonical['review'])},indent=2))
    return paths

if __name__=='__main__':main()
