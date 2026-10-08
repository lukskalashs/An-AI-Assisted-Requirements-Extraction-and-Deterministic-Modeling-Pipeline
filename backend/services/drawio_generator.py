from html import escape
from types import SimpleNamespace
from xml.etree.ElementTree import Element, SubElement, tostring

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
        y += row_height + 70
    positions = {
        uml_class.class_id: (40 + (index % columns) * 330, row_y[index // columns], 280, class_heights[uml_class.class_id])
        for index, uml_class in enumerate(classes)
    }
    return rendered_members, positions, columns * 330 + 80, y


def generate_drawio_xml(db: Session, model_id: int, diagram_type: str = "uml") -> str:
    if diagram_type not in {"uml", "erd"}:
        raise ValueError("diagram_type must be 'uml' or 'erd'")

    classes = _classes_for_diagram(db, model_id, diagram_type)
    if not classes:
        return ""

    relationships = _relationships_for_diagram(db, model_id, {item.class_id for item in classes})
    if diagram_type == "erd":
        classes, relationships = _expand_erd_junctions(classes, relationships)

    mxfile = Element("mxfile", {"host": "app.diagrams.net", "version": "24.7.17"})
    diagram_name = "UML Class Diagram" if diagram_type == "uml" else "Entity Relationship Diagram"
    diagram = SubElement(mxfile, "diagram", {"id": f"{diagram_type}-{model_id}", "name": diagram_name})
    graph = SubElement(
        diagram,
        "mxGraphModel",
        {"dx": "1200", "dy": "800", "grid": "1", "gridSize": "10", "page": "1", "pageScale": "1"},
    )
    root = SubElement(graph, "root")
    SubElement(root, "mxCell", {"id": "0"})
    SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    class_ids = {uml_class.class_id: f"class-{uml_class.class_id}" for uml_class in classes}
    classes_by_id = {uml_class.class_id: uml_class for uml_class in classes}
    member_data_by_id, positions, width, height = _diagram_layout(
        classes, diagram_type, classes_by_id, relationships
    )
    graph.set("pageWidth", str(width))
    graph.set("pageHeight", str(height))
    for uml_class in classes:
        member_data = member_data_by_id[uml_class.class_id]
        if diagram_type == "uml":
            attributes, methods = member_data
            class_title = escape(uml_class.class_name or "")
            if uml_class.is_abstract:
                class_title = f"<i>{class_title}</i>"
            value = f"<b>{class_title}</b><hr/>{'<br/>'.join(escape(item) for item in attributes)}<hr/>{'<br/>'.join(escape(item) for item in methods)}"
            shape_style = "swimlane;html=1;startSize=30;horizontal=1;align=center;verticalAlign=top;whiteSpace=wrap;"
        else:
            junction_label = "<br/><i>&lt;&lt;Junction&gt;&gt;</i>" if getattr(uml_class, "is_junction", False) else ""
            value = f"<b>{escape(uml_class.class_name or '')}</b>{junction_label}<hr/>{'<br/>'.join(escape(item) for item in member_data)}"
            header_size = "48" if junction_label else "30"
            shape_style = f"swimlane;html=1;startSize={header_size};horizontal=1;align=left;verticalAlign=top;whiteSpace=wrap;"

        cell = SubElement(
            root,
            "mxCell",
            {
                "id": class_ids[uml_class.class_id],
                "value": value,
                "style": shape_style,
                "vertex": "1",
                "parent": "1",
            },
        )
        x, y, class_width, class_height = positions[uml_class.class_id]
        geometry = SubElement(cell, "mxGeometry", {
            "x": str(x), "y": str(y), "width": str(class_width), "height": str(class_height),
        })
        geometry.set("as", "geometry")

    for relationship in relationships:
        source = class_ids.get(relationship.source_class_id)
        target = class_ids.get(relationship.target_class_id)
        if not source or not target:
            continue
        source_x, source_y, _, _ = positions[relationship.source_class_id]
        target_x, target_y, _, _ = positions[relationship.target_class_id]
        relationship_type = (relationship.relationship_type or "").lower()
        if diagram_type == "erd":
            start_arrow = _arrow_for_multiplicity(relationship.multiplicity_source)
            end_arrow = _arrow_for_multiplicity(relationship.multiplicity_target)
            label = escape(relationship.relationship_label or "")
            arrow_style = f"startArrow={start_arrow};startFill=0;endArrow={end_arrow};endFill=0;"
        else:
            label = escape(relationship.relationship_label or "")
            arrow_style = {
                "inheritance": "endArrow=block;endFill=0;",
                "aggregation": "startArrow=diamond;startFill=0;endArrow=none;",
                "composition": "startArrow=diamond;startFill=1;endArrow=none;",
            }.get(relationship_type, "endArrow=none;")
        if source_x < target_x:
            anchors = "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"
        elif source_x > target_x:
            anchors = "exitX=0;exitY=0.5;entryX=1;entryY=0.5;"
        elif source_y <= target_y:
            anchors = "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"
        else:
            anchors = "exitX=0.5;exitY=0;entryX=0.5;entryY=1;"
        edge = SubElement(
            root,
            "mxCell",
            {
                "id": f"relationship-{relationship.relationship_id}",
                "value": label,
                "style": f"edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;{anchors}{arrow_style}",
                "edge": "1",
                "parent": "1",
                "source": source,
                "target": target,
            },
        )
        geometry = SubElement(edge, "mxGeometry", {"relative": "1"})
        geometry.set("as", "geometry")
        source_multiplicity = relationship.multiplicity_source or ("1" if diagram_type == "erd" else "")
        target_multiplicity = relationship.multiplicity_target or ("*" if diagram_type == "erd" else "")
        for endpoint, value, x in (
            ("source", source_multiplicity, "-0.45"),
            ("target", target_multiplicity, "0.45"),
        ):
            if not value:
                continue
            label = SubElement(
                root,
                "mxCell",
                {
                    "id": f"relationship-{relationship.relationship_id}-{endpoint}",
                    "value": escape(value),
                    "style": "edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];fontSize=12;labelBackgroundColor=#ffffff;",
                    "vertex": "1",
                    "connectable": "0",
                    "parent": f"relationship-{relationship.relationship_id}",
                },
            )
            label_geometry = SubElement(label, "mxGeometry", {"x": x, "y": "0", "relative": "1"})
            label_geometry.set("as", "geometry")

    return tostring(mxfile, encoding="unicode", xml_declaration=True)


def generate_diagram_svg(db: Session, model_id: int, diagram_type: str = "uml") -> str:
    if diagram_type not in {"uml", "erd"}:
        raise ValueError("diagram_type must be 'uml' or 'erd'")
    classes = _classes_for_diagram(db, model_id, diagram_type)
    if not classes:
        return ""

    relationships = _relationships_for_diagram(db, model_id, {item.class_id for item in classes})
    if diagram_type == "erd":
        classes, relationships = _expand_erd_junctions(classes, relationships)

    classes_by_id = {uml_class.class_id: uml_class for uml_class in classes}
    rendered_members, positions, width, height = _diagram_layout(
        classes, diagram_type, classes_by_id, relationships
    )
    svg = Element(
        "svg",
        {"xmlns": "http://www.w3.org/2000/svg", "width": str(width), "height": str(height), "viewBox": f"0 0 {width} {height}"},
    )
    SubElement(svg, "rect", {"width": "100%", "height": "100%", "fill": "#ffffff"})
    for relationship in relationships:
        sx, sy, source_width, source_height = positions[relationship.source_class_id]
        tx, ty, target_width, target_height = positions[relationship.target_class_id]
        if tx > sx:
            start_x, start_y = sx + source_width, sy + 55
            end_x, end_y = tx, ty + 55
        elif tx < sx:
            start_x, start_y = sx, sy + 55
            end_x, end_y = tx + target_width, ty + 55
        elif ty >= sy:
            start_x, start_y = sx + source_width // 2, sy + source_height
            end_x, end_y = tx + target_width // 2, ty
        else:
            start_x, start_y = sx + source_width // 2, sy
            end_x, end_y = tx + target_width // 2, ty + target_height
        middle_x = (start_x + end_x) // 2
        path = SubElement(svg, "path", {
            "d": f"M {start_x} {start_y} L {middle_x} {start_y} L {middle_x} {end_y} L {end_x} {end_y}",
            "fill": "none",
            "stroke": "#333333",
            "stroke-width": "2",
            "data-relationship": str(relationship.relationship_id),
        })
        path.set("data-type", relationship.relationship_type or "Association")
        source_label = SubElement(svg, "text", {
            "x": str(start_x + 4), "y": str(start_y - 7),
            "font-family": "Arial,sans-serif", "font-size": "12",
        })
        source_label.text = relationship.multiplicity_source or "1"
        target_label = SubElement(svg, "text", {
            "x": str(end_x - 4), "y": str(end_y - 7), "text-anchor": "end",
            "font-family": "Arial,sans-serif", "font-size": "12",
        })
        target_label.text = relationship.multiplicity_target or "*"
        if diagram_type == "uml":
            relation_label = SubElement(svg, "text", {
                "x": str(middle_x), "y": str((start_y + end_y) // 2 - 5), "text-anchor": "middle",
                "font-family": "Arial,sans-serif", "font-size": "12",
            })
            relation_label.text = relationship.relationship_label or relationship.relationship_type or "Association"

    for uml_class in classes:
        x, y, box_width, box_height = positions[uml_class.class_id]
        cell_id = f"class-{uml_class.class_id}"
        shape = "table" if diagram_type == "erd" else "uml-class"
        SubElement(svg, "rect", {
            "x": str(x), "y": str(y), "width": str(box_width), "height": str(box_height),
            "fill": "#ffffff", "stroke": "#333333", "stroke-width": "2",
            "data-shape": shape, "data-id": cell_id,
        })
        title = SubElement(svg, "text", {
            "x": str(x + box_width // 2), "y": str(y + 30), "text-anchor": "middle",
            "font-family": "Arial,sans-serif", "font-size": "18", "font-weight": "bold",
        })
        title.text = uml_class.class_name or ""
        is_junction = diagram_type == "erd" and getattr(uml_class, "is_junction", False)
        if is_junction:
            junction_label = SubElement(svg, "text", {
                "x": str(x + box_width // 2), "y": str(y + 48), "text-anchor": "middle",
                "font-family": "Arial,sans-serif", "font-size": "12", "font-style": "italic",
            })
            junction_label.text = "<<Junction>>"
        divider_y = y + (56 if is_junction else 42)
        SubElement(svg, "line", {
            "x1": str(x), "y1": str(divider_y), "x2": str(x + box_width), "y2": str(divider_y),
            "stroke": "#333333",
        })
        member_data = rendered_members[uml_class.class_id]
        if diagram_type == "uml":
            attributes, methods = member_data
            rows_to_render = attributes + methods
            divider_at = y + 52 + len(attributes) * 20
            SubElement(svg, "line", {
                "x1": str(x), "y1": str(divider_at), "x2": str(x + box_width), "y2": str(divider_at),
                "stroke": "#a0a0a0",
            })
            start_y = y + 67
        else:
            rows_to_render = member_data
            start_y = y + (77 if is_junction else 65)
        for row, member in enumerate(rows_to_render):
            label = SubElement(svg, "text", {
                "x": str(x + 12), "y": str(start_y + row * 20),
                "font-family": "Arial,sans-serif", "font-size": "13",
            })
            label.text = member

    return tostring(svg, encoding="unicode", xml_declaration=True)
