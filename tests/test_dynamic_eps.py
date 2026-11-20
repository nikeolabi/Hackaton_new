import unittest
from dynamic_eps.canonical import extract
from dynamic_eps.fhir import build
import json
from pathlib import Path

CONFIG=json.loads((Path(__file__).resolve().parents[1]/'config/mappings.json').read_text())

class ConverterTests(unittest.TestCase):
    def test_multiple_medication_sources(self):
        source={'recordType':'medlist','records':[{'document_id':'1','drugs':{'drug':{'preparation_text':'Test medication','atc_code':'A01AA01'}},'prescription':{}}]}
        canonical=extract({'patientId':'197001010000','sources':[source,dict(source,recordType='medlist2')]}, CONFIG)
        self.assertEqual(len(canonical['medications']),2)
        bundle,report=build(canonical,CONFIG,document_date='2026-11-19T10:00:00+01:00')
        self.assertEqual(report['resource_counts']['MedicationStatement'],2)
        self.assertEqual(bundle['entry'][0]['resource']['resourceType'],'Composition')
        self.assertIn('identifier',bundle['entry'][0]['resource'])
    def test_null_unit_omitted(self):
        canonical=extract({'patientId':'197001010000','sources':[{'recordType':'kemlab4','sourceData':{'samples':[{'analyses':[{'analysis':'test','analysisId':'NPU12345','value':'0,86','unit':None}]}]}}]},CONFIG)
        bundle,_=build(canonical,CONFIG,document_date='2026-11-19T10:00:00+01:00')
        obs=next(e['resource'] for e in bundle['entry'] if e['resource']['resourceType']=='Observation')
        self.assertEqual(obs['valueQuantity']['value'],.86)
        self.assertNotIn('unit',obs['valueQuantity'])
    def test_name_from_laboratory_patient_only(self):
        source={'recordType':'kemlab', 'sourceData': {'attestation': {
            'patient': {'fullName': 'Example Patient'},
            'responsibleAttester': {'fullName':'Doctor Wrong'}},
            'samples': []}}
        canonical=extract({'patientId':'197001010000','sources':[source]}, CONFIG)
        self.assertEqual(canonical['patient_name'], 'Example Patient')
        bundle,_=build(canonical,CONFIG,document_date='2026-11-19T10:00:00+01:00')
        self.assertEqual(bundle['entry'][1]['resource']['name'][0]['text'], 'Example Patient')
        # An empty narrative-only section still needs emptyReason.
        for section in bundle['entry'][0]['resource']['section']:
            if not section.get('entry'):
                self.assertIn('emptyReason',section)

    def test_no_name_is_explicitly_flagged(self):
        canonical=extract({'patientId':'197001010000','sources':[{'recordType':'medlist','records':[]}]}, CONFIG)
        self.assertIsNone(canonical['patient_name'])
        self.assertTrue(any('Patient name not present' in r['reason'] for r in canonical['review']))
        bundle,_=build(canonical,CONFIG,document_date='2026-11-19T10:00:00+01:00')
        name=bundle['entry'][1]['resource']['name'][0]
        self.assertEqual(name['extension'][0]['valueCode'],'unknown')

    def test_conflicting_patient_names_not_silently_selected(self):
        sources=[{'recordType':'kemlab', 'sourceData':{'attestation':{'patient':{'fullName':n}},'samples':[]}}
                 for n in ('First Person','Different Person')]
        canonical=extract({'patientId':'197001010000','sources':sources},CONFIG)
        self.assertIsNone(canonical['patient_name'])
        self.assertTrue(any('Conflicting patient names' in r['reason'] for r in canonical['review']))

    def test_unknown_types_reported(self):
        result=extract({'patientId':'197001010000','sources':[{'recordType':'bokningar'}]},CONFIG)
        self.assertEqual(result['unknown_sources'][0]['record_type'],'bokningar')

    def test_loinc_enrichment_preserves_npu(self):
        fact={'name':'P-Natrium','code':'NPU03429','value':139.0,'original_value':'139','unit':'mmol/L',
              'source_path':'$.sources[0]'}
        canonical={'patient_id':'197001010000','patient_name':'Example','conditions':[], 'medications':[],
                   'laboratory':[fact], 'vitals':[], 'procedures':[], 'plans':[]}
        bundle,report=build(canonical,CONFIG,document_date='2026-11-19T10:00:00+01:00')
        obs=next(e['resource'] for e in bundle['entry'] if e['resource']['resourceType']=='Observation')
        codings=obs['code']['coding']
        self.assertTrue(any(c['code']=='NPU03429' for c in codings))
        self.assertTrue(any(c['system']=='http://loinc.org' and c['code']=='2951-2' for c in codings))
        self.assertEqual(obs['valueQuantity']['code'],'mmol/L')
        self.assertEqual(len(report['terminology_enrichment']),1)

    def test_unmatched_lab_does_not_guess_loinc(self):
        canonical={'patient_id':'197001010000','patient_name':'Example','conditions':[], 'medications':[],
                   'laboratory':[{'name':'P-Natrium','code':'NPU03429','value':139,'original_value':'139','unit':'foo',
                                  'source_path':'$.sources[0]'}], 'vitals':[], 'procedures':[], 'plans':[]}
        bundle,report=build(canonical,CONFIG,document_date='2026-11-19T10:00:00+01:00')
        obs=next(e['resource'] for e in bundle['entry'] if e['resource']['resourceType']=='Observation')
        self.assertFalse(any(c.get('system')=='http://loinc.org' for c in obs['code']['coding']))
        self.assertNotIn('code',obs['valueQuantity'])
        self.assertEqual(report['terminology_enrichment'],[])

    def test_reviewed_medication_rxnorm(self):
        import copy
        cfg=copy.deepcopy(CONFIG)
        cfg['terminology_enrichment']['medication_exact']={'Test pill': {'rxcui':'12345','strength':'20','form':'tablet'}}
        canonical={'patient_id':'197001010000','patient_name':'Example','conditions':[],
                   'medications':[{'name':'Test pill','atc':'A01AA01','strength':'20','form':'tablet',
                                   'instructions':[],'source_path':'$.sources[0]'}],
                   'laboratory':[], 'vitals':[], 'procedures':[], 'plans':[]}
        bundle,report=build(canonical,cfg,document_date='2026-11-19T10:00:00+01:00')
        med=next(e['resource'] for e in bundle['entry'] if e['resource']['resourceType']=='Medication')
        self.assertEqual(len(med['code']['coding']),2)
        self.assertEqual(med['code']['coding'][1]['code'],'12345')
        canonical['medications'][0]['strength']='40'
        bundle,report=build(canonical,cfg,document_date='2026-11-19T10:00:00+01:00')
        med=next(e['resource'] for e in bundle['entry'] if e['resource']['resourceType']=='Medication')
        self.assertEqual(len(med['code']['coding']),1)

if __name__=='__main__':unittest.main()
