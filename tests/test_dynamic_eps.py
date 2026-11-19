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

if __name__=='__main__':unittest.main()
