from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, List, Set, Union

from domain_extractors import extract_xml_records
from pipeline_types import StructuredData
from xml_utils import (
    xml_element_to_dict,
    xml_element_to_keyed_value,
    xml_local_tag,
)

SUPPORTED_EXTENSIONS = {".json", ".xml"}
PATIENT_ID_PATTERN = re.compile(r"\d{12}")


def record_type_from_path(file_path: Path) -> str:
    return (
        file_path.stem.removesuffix("_stadad").removesuffix("_stadat")
    )


def normalize_json(file_path: Path) -> StructuredData:
    with file_path.open("r", encoding="utf-8") as file:
        source_data = json.load(file)

    return {
        "schemaVersion": "1.0",
        "recordType": record_type_from_path(file_path),
        "source": {
            "file": file_path.name,
            "format": "json",
        },
        "sourceData": source_data,
    }


def normalize_xml(file_path: Path) -> StructuredData:
    root = ET.parse(file_path).getroot()
    return {
        "schemaVersion": "1.0",
        "recordType": record_type_from_path(file_path),
        "source": {
            "file": file_path.name,
            "format": "xml",
        },
        "data": {
            xml_local_tag(root): xml_element_to_keyed_value(root),
        },
        "records": extract_xml_records(root),
        "sourceData": xml_element_to_dict(root),
    }


def patient_id_from_value(value: Any) -> Union[str, None]:
    candidate = str(value).strip()
    if PATIENT_ID_PATTERN.fullmatch(candidate):
        return candidate
    return None


def extract_json_patient_ids(value: Any) -> Set[str]:
    patient_ids: Set[str] = set()

    def add_patient_id(candidate: Any) -> None:
        patient_id = patient_id_from_value(candidate)
        if patient_id is not None:
            patient_ids.add(patient_id)

    def visit(current: Any) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                normalized_key = key.replace("_", "").casefold()

                if normalized_key in {
                    "patientid",
                    "patientnumber",
                    "personalnumber",
                }:
                    add_patient_id(child)
                elif normalized_key == "patient" and isinstance(child, dict):
                    add_patient_id(child.get("id"))
                elif normalized_key == "xid" and isinstance(child, str):
                    add_patient_id(child.split("-", 1)[0])

                visit(child)
        elif isinstance(current, list):
            for child in current:
                visit(child)

    visit(value)
    return patient_ids


def extract_xml_patient_ids(value: StructuredData) -> Set[str]:
    patient_ids: Set[str] = set()

    def add_patient_id(candidate: Any) -> None:
        patient_id = patient_id_from_value(candidate)
        if patient_id is not None:
            patient_ids.add(patient_id)

    def local_tag(node: StructuredData) -> str:
        return str(node.get("tag", "")).rsplit("}", 1)[-1].casefold()

    def visit(node: StructuredData) -> None:
        if local_tag(node) == "patientid":
            add_patient_id(node.get("text"))
            for child in node.get("children", []):
                if isinstance(child, dict) and local_tag(child) == "id":
                    add_patient_id(child.get("text"))

        for child in node.get("children", []):
            if isinstance(child, dict):
                visit(child)

    visit(value)
    return patient_ids


def extract_patient_ids(data: StructuredData) -> Set[str]:
    source = data["source"]
    source_data = data["sourceData"]

    if source["format"] == "json":
        return extract_json_patient_ids(source_data)
    if source["format"] == "xml" and isinstance(source_data, dict):
        return extract_xml_patient_ids(source_data)
    return set()


def normalize_file(file_path: Path) -> StructuredData:
    if file_path.suffix.lower() == ".json":
        normalized_data = normalize_json(file_path)
    elif file_path.suffix.lower() == ".xml":
        normalized_data = normalize_xml(file_path)
    else:
        raise ValueError(f"Unsupported file extension: {file_path.suffix}")

    patient_ids = extract_patient_ids(normalized_data)
    if len(patient_ids) > 1:
        raise ValueError(
            f"{file_path.name} contains multiple patient identifiers: "
            f"{sorted(patient_ids)}"
        )

    normalized_data["patientId"] = (
        next(iter(patient_ids)) if patient_ids else None
    )
    return normalized_data


def normalized_output_path(
    file_path: Path,
    output_directory: Path,
) -> Path:
    return output_directory / f"{file_path.stem}_normalized.json"


def write_json(
    data: StructuredData,
    output_path: Path,
    overwrite: bool = False,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"

    with output_path.open(mode, encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def normalize_directory(
    input_directory: Path,
    records_directory: Path,
    overwrite: bool = False,
) -> List[Path]:
    normalized_files = []

    for file_path in input_directory.iterdir():
        if (
            not file_path.is_file()
            or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS
        ):
            continue

        output_path = normalized_output_path(file_path, records_directory)
        write_json(normalize_file(file_path), output_path, overwrite)
        logging.info("Created %s", output_path)
        normalized_files.append(output_path)

    return normalized_files
