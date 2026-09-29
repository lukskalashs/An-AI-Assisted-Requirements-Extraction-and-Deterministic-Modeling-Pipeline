import re
from sqlalchemy.orm import Session
from models.database import UMLClass, UMLAttribute, UMLRelationship
from services.relationship_normalizer import canonicalize_relationship


def _normalize_multiplicity(value):
    if value is None:
        return "1"

    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"none", "null"}:
        return "1"

    if cleaned.lower() in {"many", "n", "*"}:
        return "0..*"

    if cleaned.startswith("0..") or cleaned.startswith("1.."):
        return cleaned

    if cleaned in {"0", "1"}:
        return cleaned

    return cleaned


def _is_many(value: str) -> bool:
    normalized = _normalize_multiplicity(value).lower()
    return "*" in normalized or "n" in normalized or normalized.endswith("..*")


def _safe_name(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _foreign_key_name(class_name: str) -> str:
    return f"{_safe_name(class_name).lower()}_id"


def _relationship_symbol(source_mult: str, target_mult: str):
    source_many = _is_many(source_mult)
    target_many = _is_many(target_mult)

    if source_many and target_many:
        return "}o--o{"  
    if source_many and not target_many:
        return "}o--||"
    if not source_many and target_many:
        return "||--o{"
    return "||--||"


def generate_plantuml_erd(db: Session, model_id: int) -> str:
    """
    Build a canonical ERD with proper entity tables and cardinality symbols.
    """
    all_classes = db.query(UMLClass).filter(UMLClass.model_id == model_id).all()
    excluded_terms = ("platform", "system", "application", "service", "engine")
    classes = [
        cls for cls in all_classes
        if (cls.entity_kind or "persistent_entity") == "persistent_entity"
        and not any(term in (cls.class_name or "").lower() for term in excluded_terms)
    ]
    if not classes:
        return ""

    entity_names = [_safe_name(c.class_name).lower() for c in classes]
    class_by_id = {c.class_id: c for c in classes}
    schema = {}

    for cls in classes:
        safe_name = _safe_name(cls.class_name)
        pk_name = f"{safe_name.lower()}_id"

        schema[safe_name] = {
            "pk": pk_name,
            "columns": [],
            "fks": [],
            "relations": [],
            "is_junction": False,
        }

        relationships = db.query(UMLRelationship).filter(
            UMLRelationship.model_id == model_id,
            UMLRelationship.target_class_id == cls.class_id,
        ).all()
        foreign_key_names = set()
        for rel in relationships:
            source_cls = class_by_id.get(rel.source_class_id)
            target_cls = class_by_id.get(rel.target_class_id)
            if not source_cls or not target_cls:
                continue
            canonical_source, canonical_target, _, _ = canonicalize_relationship(
                source_cls.class_name,
                target_cls.class_name,
                rel.multiplicity_source,
                rel.multiplicity_target,
            )
            canonical_target_key = _safe_name(canonical_target).lower()
            if canonical_target_key == safe_name.lower():
                foreign_key_names.add(_foreign_key_name(canonical_source))

        attributes = db.query(UMLAttribute).filter(UMLAttribute.class_id == cls.class_id).all()
        for attr in attributes:
            attr_name = attr.attribute_name.replace(" ", "_")
            data_type = attr.data_type if attr.data_type else "VARCHAR"
            clean_type = data_type.replace("List<", "").replace("Map<", "").replace(">", "").strip()

            if clean_type.lower() in entity_names:
                continue

            normalized_attr_name = attr_name.replace("_", "").lower()
            normalized_foreign_keys = {name.replace("_", "").lower() for name in foreign_key_names}
            normalized_pk_name = pk_name.replace("_", "").lower()
            if normalized_attr_name == normalized_pk_name or normalized_attr_name in normalized_foreign_keys:
                continue

            if normalized_attr_name in normalized_foreign_keys or (
                attr_name.lower().endswith("_id") and "id" in attr_name.lower()
            ):
                data_type = "INT"

            if "list" in data_type.lower() or "map" in data_type.lower():
                schema[safe_name]["columns"].append(f"{attr_name} : JSON")
            else:
                schema[safe_name]["columns"].append(f"{attr_name} : {data_type}")

    included_ids = {cls.class_id for cls in classes}
    relationships = [
        rel for rel in db.query(UMLRelationship).filter(UMLRelationship.model_id == model_id).all()
        if rel.source_class_id in included_ids and rel.target_class_id in included_ids
    ]

    for rel in relationships:
        source_cls = db.query(UMLClass).filter(UMLClass.class_id == rel.source_class_id).first()
        target_cls = db.query(UMLClass).filter(UMLClass.class_id == rel.target_class_id).first()

        if not source_cls or not target_cls:
            continue

        src_name, tgt_name, canonical_src_mult, canonical_tgt_mult = canonicalize_relationship(
            source_cls.class_name,
            target_cls.class_name,
            rel.multiplicity_source,
            rel.multiplicity_target,
        )
        src_name = _safe_name(src_name)
        tgt_name = _safe_name(tgt_name)

        src_mult = _normalize_multiplicity(canonical_src_mult)
        tgt_mult = _normalize_multiplicity(canonical_tgt_mult)

        is_many_to_many = _is_many(src_mult) and _is_many(tgt_mult)

        if is_many_to_many:
            junction_name = f"{src_name}_{tgt_name}_Link"
            if junction_name not in schema:
                schema[junction_name] = {
                    "pk": f"{junction_name.lower()}_id",
                    "columns": ["created_at : TIMESTAMP"],
                    "fks": [f"{_foreign_key_name(src_name)} <<FK>>", f"{_foreign_key_name(tgt_name)} <<FK>>"],
                    "relations": [],
                    "is_junction": True,
                }

            schema[src_name]["relations"].append(f"{src_name} ||--o{{ {junction_name}")
            schema[tgt_name]["relations"].append(f"{tgt_name} ||--o{{ {junction_name}")
            continue

        fk = f"{_foreign_key_name(src_name)} <<FK>>"
        if fk not in schema[tgt_name]["fks"]:
            schema[tgt_name]["fks"].append(fk)

        symbol = _relationship_symbol(src_mult, tgt_mult)
        schema[src_name]["relations"].append(f'{src_name} "{src_mult}" {symbol} "{tgt_mult}" {tgt_name}')

    puml = [
        "@startuml",
        "!theme plain",
        "hide circle",
        "left to right direction",
        "skinparam linetype ortho",
        "skinparam nodesep 70",
        "skinparam ranksep 100",
        "skinparam class {",
        "    BackgroundColor White",
        "    BorderColor #333333",
        "    ArrowColor #005599",
        "}",
        "",
    ]

    for table_name, data in schema.items():
        stereotype = "<<Junction>>" if data.get("is_junction") else ""
        puml.append(f'entity "{table_name}" as {table_name} {stereotype} {{')
        puml.append(f'  * {data["pk"]} : INT <<PK>>')
        puml.append("  --")
        for fk in data["fks"]:
            puml.append(f'  * {fk}')
        for col in data["columns"]:
            puml.append(f'  {col}')
        puml.append("}")
        puml.append("")

    for data in schema.values():
        for relation in data.get("relations", []):
            puml.append(relation)

    puml.append("@enduml")
    return "\n".join(puml)
