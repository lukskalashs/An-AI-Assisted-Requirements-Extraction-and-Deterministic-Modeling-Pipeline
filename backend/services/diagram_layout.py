from types import SimpleNamespace

from sqlalchemy.orm import Session

from models.database import UMLClass, UMLRelationship
from services.erd_visual_generator import _is_many, _normalize_multiplicity, _safe_name
from services.relationship_normalizer import canonicalize_relationship


def _classes_for_diagram(db: Session, model_id: int, diagram_type: str):
    classes = db.query(UMLClass).filter(UMLClass.model_id == model_id).all()
    if diagram_type == "erd":
        excluded_terms = ("platform", "system", "application", "service", "engine")
        classes = [
            item for item in classes
            if (item.entity_kind or "persistent_entity") == "persistent_entity"
            and not any(term in (item.class_name or "").lower() for term in excluded_terms)
        ]
    return classes


def _relationships_for_diagram(db: Session, model_id: int, class_ids: set[int]):
    return [
        item for item in db.query(UMLRelationship).filter(UMLRelationship.model_id == model_id).all()
        if item.source_class_id in class_ids and item.target_class_id in class_ids
    ]


def _expand_erd_junctions(classes, relationships):
    classes_by_id = {uml_class.class_id: uml_class for uml_class in classes}
    classes_by_name = {_safe_name(uml_class.class_name).lower(): uml_class for uml_class in classes}
    expanded_classes = list(classes)
    expanded_relationships = []
    junctions_by_name = {}
    junction_edges = set()
    next_class_id = -1
    next_relationship_id = -1

    for relationship in relationships:
        source_class = classes_by_id[relationship.source_class_id]
        target_class = classes_by_id[relationship.target_class_id]
        source_name, target_name, source_mult, target_mult = canonicalize_relationship(
            source_class.class_name,
            target_class.class_name,
            relationship.multiplicity_source,
            relationship.multiplicity_target,
        )
        source_mult = _normalize_multiplicity(source_mult)
        target_mult = _normalize_multiplicity(target_mult)

        if not (_is_many(source_mult) and _is_many(target_mult)):
            expanded_relationships.append(relationship)
            continue

        canonical_source = classes_by_name[_safe_name(source_name).lower()]
        canonical_target = classes_by_name[_safe_name(target_name).lower()]
        junction_name = f"{_safe_name(source_name)}_{_safe_name(target_name)}_Link"
        junction = junctions_by_name.get(junction_name)
        if junction is None:
            junction = SimpleNamespace(
                class_id=next_class_id,
                class_name=junction_name,
                attributes=[
                    SimpleNamespace(attribute_name="created_at", data_type="TIMESTAMP"),
                ],
                methods=[],
                is_abstract=False,
                is_junction=True,
            )
            junctions_by_name[junction_name] = junction
            expanded_classes.append(junction)
            next_class_id -= 1

        for endpoint_class in (canonical_source, canonical_target):
            edge_key = (junction_name, endpoint_class.class_id)
            if edge_key in junction_edges:
                continue
            expanded_relationships.append(SimpleNamespace(
                relationship_id=next_relationship_id,
                source_class_id=endpoint_class.class_id,
                target_class_id=junction.class_id,
                relationship_type="Association",
                relationship_label=None,
                multiplicity_source="1",
                multiplicity_target="0..*",
            ))
            next_relationship_id -= 1
            junction_edges.add(edge_key)

    return expanded_classes, expanded_relationships


def _erd_members(uml_class, classes, relationships):
    members = [f"PK  {uml_class.class_name.replace(' ', '_').lower()}_id : INT"]
    foreign_keys = [
        f"FK  {classes[relationship.source_class_id].class_name.replace(' ', '_').lower()}_id : INT"
        for relationship in relationships
        if relationship.target_class_id == uml_class.class_id
        and relationship.source_class_id in classes
    ]
    members.extend(foreign_keys)
    foreign_key_names = {item.split("  ", 1)[1].split(" :", 1)[0].lower() for item in foreign_keys}
    primary_key = f"{uml_class.class_name.replace(' ', '').lower()}id"
    for attribute in uml_class.attributes:
        name = (attribute.attribute_name or "").replace(" ", "_")
        normalized = name.replace("_", "").lower()
        if normalized == primary_key or normalized in {
            key.replace("_", "").lower() for key in foreign_key_names
        }:
            continue
        members.append(f"{name} : {attribute.data_type or 'VARCHAR'}")
    return members


def _members(uml_class, diagram_type, classes, relationships):
    if diagram_type == "erd":
        return _erd_members(uml_class, classes, relationships)
    attributes = [
        f"{_uml_visibility(attribute.visibility)}{attribute.attribute_name or ''} : {attribute.data_type or 'String'}"
        for attribute in uml_class.attributes
    ]
    methods = []
    for method in uml_class.methods:
        name = (method.method_name or "").strip()
        if name.endswith("()"):
            name = name[:-2].rstrip()
        methods.append(
            f"{_uml_visibility(method.visibility)}{name}() : {method.return_type or 'void'}"
        )
    return attributes, methods


def _uml_visibility(visibility: str | None) -> str:
    return {"public": "+ ", "private": "- ", "protected": "# ", "internal": "~ "}.get(
        (visibility or "public").lower(), "+ "
    )


def _arrow_for_multiplicity(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return {
        "1": "ERone",
        "0..1": "ERzeroToOne",
        "1..*": "ERoneToMany",
        "0..*": "ERzeroToMany",
        "*": "ERmany",
        "many": "ERmany",
    }.get(normalized, "ERmany" if "*" in normalized or "many" in normalized else "ERone")


def _diagram_layout(classes, diagram_type, classes_by_id, relationships):
    rendered_members = {
        uml_class.class_id: _members(uml_class, diagram_type, classes_by_id, relationships)
        for uml_class in classes
    }
    class_heights = {}
    for uml_class in classes:
        member_data = rendered_members[uml_class.class_id]
        line_count = len(member_data[0]) + len(member_data[1]) if diagram_type == "uml" else len(member_data)
        header_height = 74 if getattr(uml_class, "is_junction", False) else 58
        class_heights[uml_class.class_id] = max(130, header_height + line_count * 24)

    columns = min(3, len(classes))
    row_heights = [
        max(class_heights[uml_class.class_id] for uml_class in classes[row * columns:(row + 1) * columns])
        for row in range((len(classes) + columns - 1) // columns)
    ]
    row_y = []
    y = 40
    for row_height in row_heights:
        row_y.append(y)
        y += row_height + 130
    positions = {
        uml_class.class_id: (50 + (index % columns) * 460, row_y[index // columns], 360, class_heights[uml_class.class_id])
        for index, uml_class in enumerate(classes)
    }
    return rendered_members, positions, columns * 460 + 100, y


