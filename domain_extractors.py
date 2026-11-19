from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List

from pipeline_types import StructuredData
from xml_utils import (
    xml_child,
    xml_children,
    xml_element_to_ml_value,
    xml_local_tag,
    xml_scalar_value,
    xml_text,
)


def extract_medication_records(root: ET.Element) -> List[StructuredData]:
    records = []

    for element in root.iter():
        if xml_local_tag(element) != "Medication":
            continue

        record = xml_element_to_ml_value(element)
        if not isinstance(record, dict):
            raise ValueError("Medication must contain structured fields.")
        record["record_type"] = "medication"
        records.append(record)

    return records


def extract_keyword_values(value_element: ET.Element) -> List[StructuredData]:
    values = []
    value_term_id = xml_text(value_element, "TermId")

    for text_element in xml_children(value_element, "TextVal"):
        text = text_element.text.strip() if text_element.text else None
        values.append(
            {
                "type": "text",
                "value": text,
                "term_id": value_term_id,
            }
        )

    for number_element in xml_children(value_element, "NumVal"):
        number_text = xml_text(number_element, "Val")
        values.append(
            {
                "type": "number",
                "value": xml_scalar_value("Val", number_text),
                "unit": xml_text(number_element, "Unit"),
                "term_id": value_term_id,
            }
        )

    if not values:
        values.append(
            {
                "type": "structured",
                "value": xml_element_to_ml_value(value_element),
                "term_id": value_term_id,
            }
        )

    return values


def extract_keyword_records(
    keyword: ET.Element,
    parent_path: List[str],
) -> List[StructuredData]:
    name = xml_text(keyword, "Name")
    path_part = name or xml_text(keyword, "TermId") or "unnamed"
    keyword_path = [*parent_path, path_part]
    values = [
        value
        for value_element in xml_children(keyword, "Value")
        for value in extract_keyword_values(value_element)
    ]
    record: StructuredData = {
        "path": keyword_path,
        "name": name,
        "term_id": xml_text(keyword, "TermId"),
        "values": values,
        "comment": xml_text(keyword, "Comment"),
    }
    records = [record]

    for child_keyword in xml_children(keyword, "Keyword"):
        records.extend(
            extract_keyword_records(child_keyword, keyword_path)
        )

    return records


def extract_care_document_records(root: ET.Element) -> List[StructuredData]:
    records = []

    for element in root.iter():
        if xml_local_tag(element) != "Casenote":
            continue

        content = xml_child(element, "Content")
        keywords = []
        if content is not None:
            for keyword in xml_children(content, "Keyword"):
                keywords.extend(extract_keyword_records(keyword, []))

        records.append(
            {
                "record_type": "care_document",
                "document_id": xml_text(element, "DocumentId"),
                "created_by_user_id": xml_text(
                    element,
                    "DocCreatedByUserId",
                ),
                "created_by_profession_id": xml_text(
                    element,
                    "DocCreatedByProfessionId",
                ),
                "created_at_care_unit_id": xml_text(
                    element,
                    "DocCreatedAtCareUnitId",
                ),
                "created_at": xml_text(element, "DocCreatedTimestamp"),
                "saved_by_user_id": (
                    xml_text(element, "DocSavedByUSerId")
                    or xml_text(element, "DocSavedByUserId")
                ),
                "saved_at": xml_text(element, "DocSavedTimestamp"),
                "signer_id": xml_text(element, "SignerId"),
                "signed_by_id": xml_text(element, "SignedById"),
                "signed_at": xml_text(element, "SignedTimestamp"),
                "approved_for_patient": xml_scalar_value(
                    "ApprovedForPatient",
                    xml_text(element, "ApprovedForPatient"),
                ),
                "event_date_time": xml_text(element, "EventDateTime"),
                "document_title": xml_text(element, "DocumentTitle"),
                "template_name": xml_text(element, "TemplateName"),
                "template_id": xml_text(element, "TemplateId"),
                "document_code": xml_text(element, "DocumentCode"),
                "header_term": xml_text(element, "HeaderTerm"),
                "keywords": keywords,
            }
        )

    return records


def extract_xml_records(root: ET.Element) -> List[StructuredData]:
    method = root.attrib.get("Method", "")
    if method.startswith("Medications."):
        return extract_medication_records(root)
    if method.startswith("CaseNote."):
        return extract_care_document_records(root)
    return []
