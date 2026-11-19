from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, Dict, List

from normalizers import normalized_output_path, write_json
from pipeline_types import StructuredData

PATIENT_ASSIGNMENTS_FILE = "patient_assignments.json"


def read_normalized_file(file_path: Path) -> StructuredData:
    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"{file_path.name} must contain a JSON object.")

    required_fields = {
        "schemaVersion",
        "recordType",
        "patientId",
        "source",
        "sourceData",
    }
    missing_fields = required_fields.difference(data)
    if missing_fields:
        raise ValueError(
            f"{file_path.name} is missing normalized fields: "
            f"{sorted(missing_fields)}"
        )

    return data


def read_patient_assignments(
    assignment_path: Path,
) -> Dict[str, StructuredData]:
    if not assignment_path.exists():
        return {}

    with assignment_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict) or not isinstance(
        data.get("assignments"),
        list,
    ):
        raise ValueError(f"{assignment_path.name} must contain an assignments array.")

    assignments: Dict[str, StructuredData] = {}
    for assignment in data["assignments"]:
        if not isinstance(assignment, dict):
            raise ValueError(
                f"{assignment_path.name} contains a non-object assignment."
            )

        patient_id = assignment.get("patientId")
        source_files = assignment.get("sourceFiles")
        confidence = assignment.get("confidence")
        evidence = assignment.get("evidence")
        if (
            not isinstance(patient_id, str)
            or len(patient_id) != 12
            or not patient_id.isdigit()
        ):
            raise ValueError(f"{assignment_path.name} contains an invalid patientId.")
        if (
            not isinstance(source_files, list)
            or not source_files
            or not all(isinstance(item, str) for item in source_files)
        ):
            raise ValueError(f"{assignment_path.name} contains invalid sourceFiles.")
        if confidence not in {"high", "medium", "low"}:
            raise ValueError(f"{assignment_path.name} contains invalid confidence.")
        if (
            not isinstance(evidence, list)
            or not evidence
            or not all(isinstance(item, str) for item in evidence)
        ):
            raise ValueError(f"{assignment_path.name} contains invalid evidence.")

        assignment_details: StructuredData = {
            "patientId": patient_id,
            "confidence": confidence,
            "evidence": evidence,
        }
        for source_file in source_files:
            if source_file in assignments:
                raise ValueError(f"{source_file} has multiple inferred assignments.")
            assignments[source_file] = assignment_details

    return assignments


def extract_record_ids(data: StructuredData) -> List[str]:
    if data["source"]["format"] != "json":
        return []

    source_data = data["sourceData"]
    records = source_data if isinstance(source_data, list) else [source_data]
    return [
        str(record["id"])
        for record in records
        if isinstance(record, dict) and record.get("id") is not None
    ]


def consolidate_normalized_records(
    records_directory: Path,
    output_directory: Path,
    overwrite: bool = False,
) -> List[Path]:
    inferred_assignments = read_patient_assignments(
        output_directory.parent / PATIENT_ASSIGNMENTS_FILE
    )
    patient_sources: DefaultDict[str, List[StructuredData]] = defaultdict(list)
    unassigned_sources: List[StructuredData] = []
    seen_source_files = set()

    for file_path in records_directory.iterdir():
        if not file_path.is_file() or file_path.suffix.lower() != ".json":
            continue

        normalized_data = read_normalized_file(file_path)
        source_file = str(normalized_data["source"]["file"])
        seen_source_files.add(source_file)
        patient_id = normalized_data["patientId"]
        inferred_assignment = inferred_assignments.get(source_file)
        if inferred_assignment is not None:
            inferred_patient_id = inferred_assignment["patientId"]
            if patient_id is not None and patient_id != inferred_patient_id:
                raise ValueError(
                    f"{source_file} explicitly identifies patient "
                    f"{patient_id}, but the inferred assignment identifies "
                    f"{inferred_patient_id}."
                )
            if patient_id is None:
                patient_id = inferred_patient_id
                normalized_data["patientId"] = patient_id
                normalized_data["patientIdAssignment"] = {
                    "method": "timeline-and-record-link-correlation",
                    "confidence": inferred_assignment["confidence"],
                    "evidence": inferred_assignment["evidence"],
                }

        if patient_id is None:
            unassigned_sources.append(normalized_data)
        elif isinstance(patient_id, str):
            patient_sources[patient_id].append(normalized_data)
        else:
            raise ValueError(
                f"{file_path.name} has an invalid patientId: " f"{patient_id!r}"
            )

    missing_assignment_sources = set(inferred_assignments).difference(seen_source_files)
    if missing_assignment_sources:
        raise ValueError(
            "Inferred assignments reference missing normalized sources: "
            f"{sorted(missing_assignment_sources)}"
        )

    output_files: List[Path] = []
    patients_directory = output_directory / "patients"

    for patient_id, sources in sorted(patient_sources.items()):
        patient_directory = patients_directory / f"patient_{patient_id}"
        patient_output = patient_directory / f"patient_{patient_id}.json"
        sorted_sources = sorted(
            sources,
            key=lambda source: source["source"]["file"],
        )
        patient_data: StructuredData = {
            "schemaVersion": "1.0",
            "patientId": patient_id,
            "sources": sorted_sources,
        }
        write_json(patient_data, patient_output, overwrite)
        logging.info("Created %s", patient_output)
        output_files.append(patient_output)

        for source in sorted_sources:
            source_file_name = str(source["source"]["file"])
            source_output = normalized_output_path(
                Path(source_file_name),
                patient_directory,
            )
            write_json(source, source_output, overwrite)
            logging.info("Created %s", source_output)
            output_files.append(source_output)

    unassigned_directory = output_directory / "unassigned"
    record_id_files: DefaultDict[str, List[str]] = defaultdict(list)
    unassigned_manifest_entries = []

    for source in sorted(
        unassigned_sources,
        key=lambda item: item["source"]["file"],
    ):
        source_file_name = str(source["source"]["file"])
        unassigned_output = normalized_output_path(
            Path(source_file_name),
            unassigned_directory,
        )
        write_json(source, unassigned_output, overwrite)
        logging.info("Created %s", unassigned_output)
        output_files.append(unassigned_output)

        record_ids = extract_record_ids(source)
        unassigned_manifest_entries.append(
            {
                "sourceFile": source_file_name,
                "outputFile": unassigned_output.name,
                "recordType": source["recordType"],
                "recordIds": record_ids,
            }
        )
        for record_id in record_ids:
            record_id_files[record_id].append(source_file_name)

    if unassigned_sources:
        manifest_output = unassigned_directory / "manifest.json"
        manifest_data: StructuredData = {
            "schemaVersion": "1.0",
            "reason": "No explicit patient identifier was found.",
            "files": unassigned_manifest_entries,
            "sharedRecordIds": [
                {
                    "recordId": record_id,
                    "sourceFiles": sorted(source_files),
                }
                for record_id, source_files in sorted(record_id_files.items())
                if len(source_files) > 1
            ],
        }
        write_json(manifest_data, manifest_output, overwrite)
        logging.info("Created %s", manifest_output)
        output_files.append(manifest_output)

    return output_files
