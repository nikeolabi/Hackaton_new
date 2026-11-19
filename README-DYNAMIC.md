# Config-driven EU EPS prototype

This addition **does not replace** the original normalization scripts. It takes their consolidated patient JSON (`patientId`, `sources[]`) and creates a canonical representation, an EU EPS FHIR R4 **candidate**, and a machine-readable report.

## Run

Python 3.10+; no additional Python packages required for the default offline workflow.

```bash
python process_patient.py /path/to/patient_195906113187.json --output-dir ./output
```

Produces `<patient>_canonical.json`, `<patient>_eu_eps.json`, `<patient>_mapping_report.json`.

By default, vital signs are included in Composition narrative, as in the prior *conservative* converter. Try `--structured-vitals` only as an experimental variant; it can trigger bundle slice issues in the current EU EPS / IPS ballot packages.

## What is actually dynamic?

- Source record-family patterns (`medlist*`, `vardokument*`, `kemlab*`) and individual source-field extraction paths are read from `config/mappings.json`.
- All matching source families are processed; no single-first-source selection.
- Known terms / codes and profile canonical URLs are configured, not scattered through the extractor.
- The code can inspect **real machine-readable** EPS profile `StructureDefinition` artifacts from a separately downloaded, pinned FHIR package (`--eps-package /path/to/hl7.fhir.eu.eps-1.0.0-ballot.tgz`). It checks package identity/version and reports required paths. It does not magically convert required paths into correct clinical mappings.
- An explicitly configured Snowstorm Lite terminology server (`--snowstorm-url http://localhost:8080/fhir`) can validate **reviewed** SNOMED CT code mappings. This is opt-in and currently limited to mapping values in `reviewed_snomed_mappings`; it is not ICD-10->SNOMED translation or automatic text coding.

## What is NOT automated?

- Full Xt-EHR logical-model runtime validation and full EHDS semantic compliance.
- Automatic derivation of EHR-to-FHIR clinical semantics from arbitrary source schemas.
- Terminology crosswalks that have not been reviewed.
- Official HL7 FHIR package validation (use the official validator, with pinned `hl7.fhir.eu.eps#1.0.0-ballot` and dependencies).
- Reconciliation of medication duplicates or clinical correctness.

### Suggested official references

- Xt-EHR logical model: https://www.xt-ehr.eu/fhir/models/en/StructureDefinition-EHDSPatientSummary.html
- Mapping explanation: https://hl7.eu/fhir/eps/map-ehdspatientsummary.html
- EPS IG: https://hl7.eu/fhir/eps/
- Snowstorm Lite: https://github.com/IHTSDO/snowstorm-lite

## Privacy

Patient JSON and generated FHIR data can contain confidential medical information. Do not commit them to GitHub. Do not transmit them to a remote terminology server unless your security review permits it. By default, this pipeline makes **no** network requests.

## Testing

```bash
python -m unittest discover -s tests -p 'test_dynamic*.py' -v
```

### Run the official HL7 validator (separately)

After obtaining the official HL7 FHIR `validator_cli.jar`:

```bash
python validate_eps.py output/patient_195906113187_eu_eps.json --validator-jar /path/to/validator_cli.jar
```

It invokes `java -jar validator_cli.jar ... -version 4.0.1 -ig hl7.fhir.eu.eps#1.0.0-ballot` and reports the validator's actual result. A locally valid JSON document is **not** automatically a profile-conformant document.

### SNOMED use (optional)

If you have verified SNOMED mappings such as `"ICD10SE:I489": "49436004"`, add them to `config/mappings.json` under `reviewed_snomed_mappings`. Those are only examples of the required key/value format, **not** assertions about code equivalence. Configure `--snowstorm-url` to check each proposed SNOMED code against your local Snowstorm Lite instance. Only terminology-server-confirmed codes will be added as secondary `Condition.code.coding`; original ICD-10-SE coding is always preserved. A human must approve both the mapping and its applicability to the patient.

### 2026-11-19 EPS patient/section regression fix

The FHIR layer now extracts `Patient.name` from explicitly patient-labelled source
objects (for example `sourceData.attestation.patient.fullName`). It never uses a
clinician's `fullName` as the patient's name. Conflicting names are flagged for
review rather than selecting one. When no name is provided, the Patient resource
uses the explicit marker `Name not provided in source` with the FHIR
`data-absent-reason` extension and the mapping report flags the missing name.
This is a placeholder, **not** an assertion of the patient's legal name.

Composition sections without structured resource references again get
`emptyReason`, even if there is source-derived narrative. This restores the
section layout used in the previously validated conservative output.

Run `python3 -m unittest discover -s tests -p 'test_dynamic*.py' -v` and
validate the generated Bundle with the official HL7 FHIR validator. Local
structural checks do not establish EU EPS profile conformance. In particular,
re-check the Bundle composition and patient slices under the exact pinned
implementation-guide versions.
