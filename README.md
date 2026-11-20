# Hackaton — XML/JSON to European Patient Summary (EU EPS)

> **Prototype / hackathon use.** Generates candidate FHIR R4 European Patient Summary documents from heterogeneous source records. The output is **not automatically clinically verified or certified EU EPS-compliant**. Validate with the official HL7 validator and review source-derived clinical assertions before use.

## Overview

The original pipeline normalizes XML/JSON records and consolidates records by patient. The additional dynamic converter extracts clinical facts into a canonical representation, then builds an EU EPS FHIR document Bundle.

```text
source_data/ (disparate XML and JSON files)
   │
   ▼
normalizers.py + patient_grouping.py  (run by data_pipeline.py)
   │
   ▼
patients/patient_<id>/
   ├── patient_<id>.json          (consolidated {"patientId": ..., "sources": [...]})
   └── other normalized source files belonging to that patient
   │
   ▼
process_patient.py (reads only the consolidated patient_<id>.json)
   ├── dynamic_eps/canonical.py     → canonical clinical facts
   ├── dynamic_eps/fhir.py          → FHIR R4 EU EPS candidate Bundle
   ├── dynamic_eps/enrichment.py    → configured terminology enrichment
   ├── dynamic_eps/terminology.py   → optional Snowstorm check
   └── dynamic_eps/standards.py     → optional EPS package inspection
   │
   ▼
output/patient_<id>_canonical.json
output/patient_<id>_eu_eps.json
output/patient_<id>_mapping_report.json
```

**The original normalization and grouping code has not been replaced.** `data_pipeline.py` and `process_patient.py` are currently two separate steps; there is no implemented `--generate-fhir` option on `data_pipeline.py`.

## Requirements

- Python **3.10+**.
- No third-party Python package is required for the default offline conversion path.
- `config/mappings.json` must be present.
- `dynamic_eps/` must contain `__init__.py`, `canonical.py`, `fhir.py`, `enrichment.py`, `standards.py` and `terminology.py`.
- Java and the HL7 `validator_cli.jar` are needed **only** to run official FHIR profile validation.

## Running the pipeline

### Step 1 — normalize and group the source data

Run this when source XML/JSON records have been added or changed, or when you changed normalization/grouping logic:

```bash
python3 data_pipeline.py \
  --input-directory ./source_data \
  --output-directory . \
  --overwrite
```

With `--output-directory .` executed from the project root, the output includes `normalized_records/` and `patients/patient_<id>/`. Each patient folder contains the consolidated `patient_<id>.json` **and** all normalized source records assigned to that patient. Only the consolidated file is passed to `process_patient.py`. If you already have these folders, do not rerun normalization just to regenerate EPS Bundles.

### Step 2 — convert one consolidated patient

```bash
python3 process_patient.py ./patients/patient_196607113146/patient_196607113146.json \
  --output-dir ./output
```

`process_patient.py` reads `config/mappings.json` by default. It writes three files to `output/` per patient: `<input-stem>_canonical.json`, `<input-stem>_eu_eps.json` and `<input-stem>_mapping_report.json`.

### Step 3 — convert all consolidated patients (macOS/Linux)

```bash
mkdir -p ./output
for dir in ./patients/patient_*/; do
    [ -d "$dir" ] || continue
    name=$(basename "${dir%/}")
    file="${dir}${name}.json"
    [ -f "$file" ] || continue
    python3 process_patient.py "$file" --output-dir ./output
done
```

**When only terminology mappings change, rerun Step 2/3. Do not rerun normalization or patient grouping.**

> Do not feed `_canonical.json`, `_eu_eps.json` or `_mapping_report.json` files back into `process_patient.py`—it expects consolidated patient input containing `patientId` and `sources`.

## Terminology enrichment — configuration v0.3.0

`dynamic_eps/enrichment.py` applies **exact, configured** mappings during FHIR generation. The source code/value is retained and, where configured, another coded representation is appended. This is not a generic terminology search, automatic clinical inference, or an ICD-10-to-SNOMED crosswalk service.

The current `config/mappings.json` contains:

| Configuration field | Active mappings | What it adds |
| --- | ---: | --- |
| `terminology_enrichment.laboratory_exact` | **24** | LOINC codes for particular Swedish test-name + source-unit combinations; UCUM only when the source unit matches the configured UCUM text exactly |
| `terminology_enrichment.condition_icd10_exact` | **4** | SNOMED CT coding alongside existing ICD-10-SE diagnoses |
| `terminology_enrichment.procedure_exact` | **1** | SNOMED CT coding alongside a source KVÅ procedure code |
| `terminology_enrichment.medication_exact` | **0** | RxNorm support exists, but no verified RxCUI product mappings are currently active |

Additional existing source codes—such as ICD-10-SE, ATC and NPU—remain in the output where available. The converter also uses LOINC section codes and configured vital-sign codes; these are separate from the 24 laboratory enrichment entries.

### Sample exact-match mappings

A laboratory mapping is keyed by **source test name + `|` + source unit**. For instance:

```json
"laboratory_exact": {
  "P-Natrium|mmol/L": {
    "loinc": "2951-2",
    "display": "Sodium [Moles/volume] in Serum or Plasma",
    "ucum": "mmol/L"
  }
}
```

If the source uses another unit spelling or the test's name differs, this entry won't match. A LOINC code must be checked against the actual specimen, analyte, property, method and unit before being treated as a clinically validated mapping. Adding a LOINC code is **not the same thing** as converting a numerical result.

The diagnosis dictionary uses source ICD-10-SE codes; examples currently configured include `I109`, `I495`, `E109`, `I633`. The procedure dictionary contains `JEA01`. These are reviewed **candidate** equivalences for the prototype, not a complete or universally one-to-one terminology crosswalk.

### RxNorm limitations

`medication_exact` is presently empty. An entry must supply a verified RxCUI and should constrain the source product's exact strength, strength unit and dose form. The enrichment code checks these supplied constraints and skips mismatches. A Swedish brand or ATC code by itself is insufficient to assert an exact RxNorm product equivalence.

### Optional Snowstorm Lite

```bash
python3 process_patient.py ./patients/patient_196607113146/patient_196607113146.json \
  --output-dir ./output \
  --snowstorm-url http://localhost:8080/fhir
```

Snowstorm checks separately configured `reviewed_snomed_mappings`; it is **not required for the default exact-match enrichment** and does not automatically discover or certify all ICD-10-SE/SNOMED equivalences. Only connect to a terminology service permitted by your organization's data-handling policies.

## Mapping reports and coverage

The converter automatically creates one `<patient>_mapping_report.json` next to its generated FHIR Bundle. This contains mapping/version information, source coverage, clinical review items and the `fhir.terminology_enrichment` log of applied codes.

The separately supplied **`coverage_report.json`** is a diagnostic summary generated when the mappings were assembled/tested. It is **not read at runtime**. You can optionally put it under `reports/coverage_report.json`; it does not belong in `config/` and is not needed for conversion. It is a snapshot, not a continuously updated report.

To check whether enrichment was applied, inspect the new per-patient report's `fhir.terminology_enrichment` array or the FHIR resource's `code.coding` array; the total number of FHIR resources may remain unchanged even after new codes are added.

## FHIR generation choices and constraints

- FHIR version: **R4 / 4.0.1**.
- Configured EPS implementation guide: `hl7.fhir.eu.eps#1.0.0-ballot`.
- The default mode includes vital signs in the Composition narrative; `--structured-vitals` is experimental and may encounter profile slicing errors.
- Patient-name extraction uses explicitly patient-labelled source objects. When no name is found, the generator outputs a missing-name marker and flags the issue for review, **not a real patient name**.
- The Bundle may include narrative-only sections for source information without supported structured-resource mapping. Do not equate `unavailable` with “no known condition/allergy”: absence of documentation and documented absence are different clinical statements.
- The converter does not resolve all duplicate diagnoses/medications or create additional clinicians, encounters, allergies, devices or care plans when these facts are not structured in the source.
- Only exact configured enrichment rules run. No scores are guaranteed by code coverage or resource counts.

## Validate the output

### Local tests

```bash
python3 -m unittest discover -s tests -p 'test_dynamic*.py' -v
```

### Official HL7 validator

After obtaining the official HL7 FHIR validator JAR, run:

```bash
python3 validate_eps.py \
  ./output/patient_196607113146_eu_eps.json \
  --validator-jar /path/to/validator_cli.jar
```

`validate_eps.py` invokes the validator against FHIR R4 and the configured EPS ballot IG. The official validator is a separate step; creating well-formed JSON and successful local tests does **not** prove compliance with the EPS/IPS profiles. Pay attention to required `Bundle.entry` Composition/Patient slices, clinical resource constraints, terminology and reference resolution.

For optional inspection of the official machine-readable EPS package (not full validation):

```bash
python3 process_patient.py ./patients/patient_196607113146/patient_196607113146.json \
  --output-dir ./output \
  --eps-package /path/to/hl7.fhir.eu.eps-1.0.0-ballot.tgz
```

## Project files relevant to recent changes

```text
Hackaton-main/
├── README.md
├── source_data/                     # Original heterogeneous XML/JSON inputs
├── normalized_records/              # Intermediate normalized records
├── patients/                        # Grouped patient records
│   └── patient_<id>/
│       ├── patient_<id>.json         # Consolidated input for FHIR conversion
│       └── ...                       # Normalized JSON/XML-derived source records
├── output/                          # Generated canonical, EPS and mapping report files
│   ├── patient_<id>_canonical.json
│   ├── patient_<id>_eu_eps.json
│   └── patient_<id>_mapping_report.json
├── data_pipeline.py                  # Original normalization/grouping entry point
├── normalizers.py
├── patient_grouping.py
├── process_patient.py               # Converts one consolidated patient
├── validate_eps.py                  # Wrapper for official HL7 validator
├── config/
│   └── mappings.json                # Latest active mapping config (v0.3.0)
├── dynamic_eps/
│   ├── __init__.py
│   ├── canonical.py                  # Source → canonical model
│   ├── enrichment.py                 # LOINC/SNOMED/RxNorm/UCUM enrichment
│   ├── fhir.py                       # Canonical model → FHIR Bundle
│   ├── standards.py                  # Optional EPS package inspection
│   └── terminology.py                # Optional Snowstorm validation
├── tests/
│   └── test_dynamic_eps.py
└── reports/
    └── coverage_report.json         # Optional snapshot, not loaded by code
```

## Privacy and safety

Generated patient Bundles can contain personal and sensitive health data. Keep source and generated records outside version control and comply with applicable organizational and legal requirements. Do **not** commit patient files or real identifiers to a public repository. Guessed clinical values, medication statuses or units must not be presented as source-derived facts; if synthetic test data are introduced, mark them as synthetic and preserve provenance.

## References

- [HL7 Europe EPS Implementation Guide](https://hl7.eu/fhir/eps/)
- [Xt-EHR EHDSPatientSummary information model](https://www.xt-ehr.eu/fhir/models/en/StructureDefinition-EHDSPatientSummary.html)
- [EHDS → FHIR EPS mapping overview](https://hl7.eu/fhir/eps/map-ehdspatientsummary.html)
- [LOINC](https://loinc.org/)
- [SNOMED CT](https://www.snomed.org/)
- [RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/)
- [UCUM](https://unitsofmeasure.org/)
- [Snowstorm Lite](https://github.com/IHTSDO/snowstorm-lite)

**Last documentation update:** 2026-11-20. Paths reflect the `patients/patient_<id>/` source layout and `output/` FHIR output layout; mapping claims are based on configuration version `0.3.0`.
