from html import escape
from xml.etree.ElementTree import Element, SubElement, tostring

from sqlalchemy.orm import Session

from services.diagram_layout import (
    _arrow_for_multiplicity,
    _classes_for_diagram,
    _diagram_layout,
    _expand_erd_junctions,
    _relationships_for_diagram,
)


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
