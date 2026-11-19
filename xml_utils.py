from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Union

BOOLEAN_XML_TAGS = {
    "ApprovedForPatient",
    "HasOrdinationReason",
    "IsApproved",
    "IsDispensionAllowed",
    "IsGivenOnFridays",
    "IsGivenOnMondays",
    "IsGivenOnSaturdays",
    "IsGivenOnSundays",
    "IsGivenOnThursdays",
    "IsGivenOnTuesdays",
    "IsGivenOnWednesdays",
    "IsMixture",
    "IsReplaceable",
    "IsSelfAdministered",
    "IsStdSolution",
    "IsTriggeredByATC",
}
NUMERIC_XML_TAGS = {
    "DilutionAmount",
    "DoseNumerical",
    "Rate",
    "SolutionStrength",
    "StdSolutionAmount",
    "Strength",
    "TotalAmount",
    "Val",
}
LIST_XML_TAGS = {
    "Administration",
    "Casenote",
    "Day",
    "Dosage",
    "DosageDrug",
    "Drug",
    "Infusion",
    "Keyword",
    "Medication",
    "Preparation",
    "Value",
}


def xml_element_to_dict(element: ET.Element) -> Dict[str, Any]:
    return {
        "tag": element.tag,
        "attributes": dict(element.attrib),
        "text": element.text,
        "tail": element.tail,
        "children": [xml_element_to_dict(child) for child in element],
    }


def xml_local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def xml_children(element: ET.Element, tag: str) -> List[ET.Element]:
    return [
        child
        for child in element
        if xml_local_tag(child) == tag
    ]


def xml_child(element: ET.Element, tag: str) -> Union[ET.Element, None]:
    children = xml_children(element, tag)
    return children[0] if children else None


def xml_text(element: ET.Element, tag: str) -> Union[str, None]:
    child = xml_child(element, tag)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def xml_element_to_keyed_value(element: ET.Element) -> Any:
    children = list(element)
    text = element.text.strip() if element.text and element.text.strip() else None

    if not children and not element.attrib:
        return text

    value: Dict[str, Any] = {}
    if element.attrib:
        value["_attributes"] = dict(element.attrib)
    if text is not None:
        value["_text"] = text

    for child in children:
        child_tag = xml_local_tag(child)
        child_value = xml_element_to_keyed_value(child)

        if child_tag not in value:
            value[child_tag] = child_value
        elif isinstance(value[child_tag], list):
            value[child_tag].append(child_value)
        else:
            value[child_tag] = [value[child_tag], child_value]

    return value


def xml_tag_to_snake_case(tag: str) -> str:
    first_pass = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", tag)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first_pass).lower()


def xml_scalar_value(tag: str, text: Union[str, None]) -> Any:
    if text is None:
        return None
    if tag in BOOLEAN_XML_TAGS:
        if text == "1":
            return True
        if text == "0":
            return False
        raise ValueError(f"Invalid boolean value for {tag}: {text!r}")
    if tag in NUMERIC_XML_TAGS:
        normalized = text.replace(",", ".")
        try:
            return int(normalized)
        except ValueError:
            try:
                return float(normalized)
            except ValueError as error:
                raise ValueError(
                    f"Invalid numeric value for {tag}: {text!r}"
                ) from error
    return text


def xml_element_to_ml_value(element: ET.Element) -> Any:
    children = list(element)
    tag = xml_local_tag(element)
    text = element.text.strip() if element.text and element.text.strip() else None

    if not children and not element.attrib:
        return xml_scalar_value(tag, text)

    value: Dict[str, Any] = {}
    if element.attrib:
        value["_attributes"] = dict(element.attrib)
    if text is not None:
        value["_text"] = xml_scalar_value(tag, text)

    for child in children:
        child_tag = xml_local_tag(child)
        key = xml_tag_to_snake_case(child_tag)
        child_value = xml_element_to_ml_value(child)

        if child_tag in LIST_XML_TAGS:
            value.setdefault(key, []).append(child_value)
        elif key not in value:
            value[key] = child_value
        elif isinstance(value[key], list):
            value[key].append(child_value)
        else:
            value[key] = [value[key], child_value]

    return value
