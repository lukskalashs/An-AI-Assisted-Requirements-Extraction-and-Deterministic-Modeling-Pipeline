import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

_ENTITY_KIND_ENUM = [
    "persistent_entity",
    "actor",
    "external_system",
    "platform_context",
    "service",
    "reporting_concept",
]
_RELATIONSHIP_TYPE_ENUM = [
    "Association",
    "Aggregation",
    "Composition",
    "Inheritance",
]

_CLASS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["classes"],
    "properties": {
        "classes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "class_name",
                    "entity_kind",
                    "is_abstract",
                    "evidence",
                    "attributes",
                    "methods",
                ],
                "properties": {
                    "class_name": {"type": "string"},
                    "entity_kind": {"type": "string", "enum": _ENTITY_KIND_ENUM},
                    "is_abstract": {"type": "boolean"},
                    "evidence": {"type": "string"},
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "data_type", "visibility", "evidence"],
                            "properties": {
                                "name": {"type": "string"},
                                "data_type": {"type": "string"},
                                "visibility": {"type": "string"},
                                "evidence": {"type": "string"},
                            },
                        },
                    },
                    "methods": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "return_type", "visibility", "evidence"],
                            "properties": {
                                "name": {"type": "string"},
                                "return_type": {"type": "string"},
                                "visibility": {"type": "string"},
                                "evidence": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
}

_RELATIONSHIP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relationships"],
    "properties": {
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_class",
                    "target_class",
                    "relationship_type",
                    "relationship_label",
                    "multiplicity_source",
                    "multiplicity_target",
                    "evidence",
                ],
                "properties": {
                    "source_class": {"type": "string"},
                    "target_class": {"type": "string"},
                    "relationship_type": {"type": "string", "enum": _RELATIONSHIP_TYPE_ENUM},
                    "relationship_label": {"type": "string"},
                    "multiplicity_source": {"type": "string"},
                    "multiplicity_target": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
    },
}


def _prompt(focus: str, class_names: list[str] | None = None) -> str:
    class_context = ""
    extraction_scope = """
For this pass, return only class definitions, attributes, and methods. Do not
extract relationships; relationship extraction is handled by a separate pass.
"""
    if class_names is not None:
        extraction_scope = """
For this pass, return only explicit relationships. Do not return classes,
attributes, methods, or any other requirement category.
"""
        class_context = f"""
The class-definition pass produced this canonical list of classes:
{json.dumps(class_names, ensure_ascii=False)}
Use only these exact strings as relationship endpoints. Do not invent,
rename, merge, or omit endpoints from this list when a supported relationship
is found.
"""

    return f"""You are an exacting requirements engineer extracting a UML model.
This is {focus}.
    {extraction_scope}

    Extract every explicitly named domain entity, actor, external system,
    business concept, attribute, method, and supported relationship relevant to
    this pass. Preserve the
exact terminology from this SRS: never replace a named entity with User,
System, Service, or another generic synonym. Distinguish similarly related
concepts when the document distinguishes them, and use one consistent class
name for each concept across all output.
For every class, set entity_kind to exactly one of persistent_entity, actor,
external_system, platform_context, service, or reporting_concept. Use
persistent_entity only when the SRS describes data that the system stores;
use actor for people/roles, external_system for integrated outside systems,
platform_context for the product/system itself, service for processing
components, and reporting_concept for analytical/reporting concepts. Keep all
these classifications in the UML extraction for analyst review, but only
persistent_entity classes should be used as database tables in the ERD.
Do not extract the document title, product/platform name, generic "system",
database, application, API, or infrastructure as a domain class unless the
requirements explicitly define it as a business entity with its own data or
behavior. A relationship is valid only when the source passage explicitly
supports both endpoints and their association; do not infer links merely
because two actors interact with the platform. Do not create a self-
relationship unless the requirements explicitly describe a recursive
relationship.
Only extract entities supported by the text; do not invent associations.
Every relationship must have a non-empty, verbatim sentence or paragraph as
evidence. Use the smallest complete source passage and preserve multiplicities
and direction. Relationship type must be exactly one of Association,
Aggregation, Composition, or Inheritance; put semantic wording such as
"applies to" or "recommends" in relationship_label and keep the structural
UML category in relationship_type.
Use standard UML multiplicities such as 1, 0..1, 1..*, or 0..*. Never use a
bare "*" and never invent a precise cardinality that the SRS does not support;
use 0..* when the source leaves the quantity unspecified. Use exact class
names in relationship endpoints. Foreign-key
attributes remain on the dependent entity and use Integer when appropriate.
Be exhaustive rather than summarizing.
{class_context}"""


def _call_model(
    text: str,
    focus: str,
    schema_name: str,
    schema: dict,
    class_names: list[str] | None = None,
) -> dict:
    if client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        },
        messages=[
            {"role": "system", "content": _prompt(focus, class_names)},
            {"role": "user", "content": text},
        ],
    )
    value = json.loads(response.choices[0].message.content or "{}")
    return value if isinstance(value, dict) else {}


def _key(value: object) -> str:
    return re.sub(r"[\s_-]+", "", str(value or "")).lower()


def _normalise_relationship(item: dict) -> dict:
    """Keep persisted relationships within the UML type/cardinality vocabulary."""
    normalised = dict(item)
    if normalised.get("relationship_type") not in _RELATIONSHIP_TYPE_ENUM:
        normalised["relationship_type"] = "Association"
    normalised["relationship_label"] = str(normalised.get("relationship_label") or "").strip() or None
    for field in ("multiplicity_source", "multiplicity_target"):
        value = str(normalised.get(field) or "").strip()
        normalised[field] = "0..*" if value in ("", "*") else value
    return normalised


def _merge_extractions(primary: dict, supplement: dict, source_text: str) -> dict:
    """Merge bounded passes without losing evidence or explicitly named terms."""
    merged = dict(primary or {})
    classes = {}
    for item in (primary.get("classes", []) if isinstance(primary, dict) else []) + (
        supplement.get("classes", []) if isinstance(supplement, dict) else []
    ):
        if not isinstance(item, dict) or not item.get("class_name"):
            continue
        key = _key(item["class_name"])
        existing = classes.setdefault(key, dict(item))
        existing.setdefault("entity_kind", item.get("entity_kind", "persistent_entity"))
        for field in ("evidence",):
            if not existing.get(field) and item.get(field):
                existing[field] = item[field]
        for field in ("attributes", "methods"):
            values = existing.setdefault(field, [])
            seen = {_key(v.get("name")) for v in values if isinstance(v, dict)}
            for value in item.get(field, []) or []:
                if isinstance(value, dict) and _key(value.get("name")) not in seen:
                    values.append(value)
                    seen.add(_key(value.get("name")))
    merged["classes"] = list(classes.values())

    class_keys = set(classes)
    relationships = []
    seen_relationships = set()
    for item in (primary.get("relationships", []) if isinstance(primary, dict) else []) + (
        supplement.get("relationships", []) if isinstance(supplement, dict) else []
    ):
        if not isinstance(item, dict) or not item.get("source_class") or not item.get("target_class"):
            continue
        item = _normalise_relationship(item)
        source_key = _key(item["source_class"])
        target_key = _key(item["target_class"])
        if source_key not in class_keys or target_key not in class_keys:
            continue
        if source_key == target_key:
            evidence = str(item.get("evidence") or "").lower()
            recursive_terms = ("parent", "child", "self", "recursive", "subordinate", "hierarch")
            if not any(term in evidence for term in recursive_terms):
                continue
        relationship_type = str(item.get("relationship_type", "Association")).lower()
        endpoint_key = (
            (source_key, target_key)
            if relationship_type == "inheritance"
            else tuple(sorted((source_key, target_key)))
        )
        key = (endpoint_key, relationship_type)
        # Keep relationship endpoints aligned with canonical class names.
        item = dict(item)
        for endpoint in ("source_class", "target_class"):
            canonical = classes.get(_key(item.get(endpoint)))
            if canonical:
                item[endpoint] = canonical["class_name"]
        if key not in seen_relationships:
            relationships.append(dict(item))
            seen_relationships.add(key)
        elif item.get("evidence"):
            for existing in relationships:
                existing_type = str(existing.get("relationship_type", "Association")).lower()
                existing_endpoints = (
                    (_key(existing.get("source_class")), _key(existing.get("target_class")))
                    if existing_type == "inheritance"
                    else tuple(sorted((_key(existing.get("source_class")), _key(existing.get("target_class")))))
                )
                if (existing_endpoints, existing_type) == key and not existing.get("evidence"):
                    existing["evidence"] = item["evidence"]
    merged["relationships"] = relationships
    return merged


def extracted_uml_entities_from_chunks(chunks: list[str]) -> dict:
    """Extract class definitions first, then relationships between those classes."""
    if not chunks:
        return {"classes": [], "relationships": []}
    source = "\n\n--- Next Section ---\n\n".join(chunks)
    try:
        primary = _call_model(
            source,
            "the class-definition pass; extract classes, attributes, and methods only",
            "uml_class_extraction",
            _CLASS_SCHEMA,
        )
        class_names = [
            item.get("class_name")
            for item in primary.get("classes", [])
            if isinstance(item, dict) and item.get("class_name")
        ]
        relationship_context = (
            source
            + "\n\n--- Canonical classes from Pass 1 ---\n\n"
            + json.dumps(class_names, ensure_ascii=False)
        )
        try:
            supplement = _call_model(
                relationship_context,
                "the relationship-only pass; extract only explicit relationship linkages",
                "uml_relationship_extraction",
                _RELATIONSHIP_SCHEMA,
                class_names,
            )
        except Exception as ex:
            print(f"Supplemental extraction pass failed: {ex}")
            supplement = {}
        return _merge_extractions(primary, supplement, source)
    except Exception as ex:
        print(f"Error during LLM processing: {ex}")
        return {"classes": [], "relationships": []}
