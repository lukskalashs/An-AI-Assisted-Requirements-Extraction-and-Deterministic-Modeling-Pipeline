import os
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session
from models.database import UMLClass, UMLAttribute, UMLRelationship
from services.relationship_normalizer import canonicalize_relationship

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

def map_to_openapi_type(raw_type: str) -> dict:
    """Maps UML types to standard OpenAPI 3.0 type schemas."""
    t = raw_type.lower()
    if t in ["int", "integer", "number"]: 
        return {"type": "integer"}
    if t in ["float", "double", "decimal"]: 
        return {"type": "number", "format": "decimal"}
    if t in ["bool", "boolean"]: 
        return {"type": "boolean"}
    if "date" in t or "timestamp" in t: 
        return {"type": "string", "format": "date-time"}
    if "list" in t or "[]" in t: 
        return {"type": "array", "items": {"type": "string"}} # Defaulting to string items for primitive JSON arrays
    if "map" in t or "dict" in t: 
        return {"type": "object"}
    
    return {"type": "string"}


def is_monetary_attribute(attribute_name: str) -> bool:
    monetary_names = {"price", "subtotal", "tax", "total", "amount", "unitprice"}
    return attribute_name.lower().replace("_", "") in monetary_names

def generate_openapi_yaml(db: Session, model_id: int) -> str:
    """
    Generates a semantically routed OpenAPI 3.0 YAML specification.
    """
    classes_db = db.query(UMLClass).filter(UMLClass.model_id == model_id).all()
    if not classes_db:
        return ""

    entity_names = {c.class_name.lower().replace(" ", ""): c.class_name.replace(" ", "") for c in classes_db}
    
    template = env.get_template("openapi.yaml.jinja2")

    classes_data = []
    nested_routes = [] # Store nested routes like /employers/{id}/jobpostings
    relationships = db.query(UMLRelationship).filter(UMLRelationship.model_id == model_id).all()
    class_by_id = {c.class_id: c for c in classes_db}
    foreign_key_names_by_class = {}
    for rel in relationships:
        source_cls = class_by_id.get(rel.source_class_id)
        target_cls = class_by_id.get(rel.target_class_id)
        if source_cls and target_cls:
            canonical_source, canonical_target, _, _ = canonicalize_relationship(
                source_cls.class_name,
                target_cls.class_name,
                rel.multiplicity_source,
                rel.multiplicity_target,
            )
            canonical_target_cls = next(
                (item for item in classes_db if item.class_name.replace(" ", "").lower() == canonical_target.replace(" ", "").lower()),
                target_cls,
            )
            foreign_key_names_by_class.setdefault(canonical_target_cls.class_id, set()).add(
                f"{canonical_source.replace(' ', '').lower()}id"
            )
    
    for cls in classes_db:
        safe_class_name = cls.class_name.replace(" ", "")
        pk_name = f"{safe_class_name.lower()}Id"
        
        attributes_data = []
        seen_attrs = {pk_name.lower()} # Track seen attributes to prevent duplicates

        attributes = db.query(UMLAttribute).filter(UMLAttribute.class_id == cls.class_id).all()
        for attr in attributes:
            safe_attr_name = attr.attribute_name.replace(" ", "")
            safe_attr_name = safe_attr_name[0].lower() + safe_attr_name[1:] if safe_attr_name else "unknown"
            
            # 1. Deduplication and Security
            if safe_attr_name.lower() in seen_attrs:
                continue
            if "password" in safe_attr_name.lower():
                continue # Never expose passwords in schemas
                
            seen_attrs.add(safe_attr_name.lower())
            
            raw_type = attr.data_type if attr.data_type else "String"
            clean_type = raw_type.replace("List<", "").replace("Map<", "").replace(">", "").strip()
            
            # Skip entity references in schema properties (handled by relationships)
            if clean_type.lower() in entity_names:
                continue

            schema_def = map_to_openapi_type(raw_type)
            if safe_attr_name.lower() in foreign_key_names_by_class.get(cls.class_id, set()):
                schema_def = {"type": "integer"}
            if is_monetary_attribute(safe_attr_name):
                schema_def = {"type": "number", "format": "decimal"}
            enum_values = {
                ("order", "status"): ["PENDING", "PAID", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED"],
                ("payment", "status"): ["PENDING", "SUCCEEDED", "FAILED", "REFUNDED"],
                ("shipment", "status"): ["PENDING", "IN_TRANSIT", "DELIVERED", "RETURNED"],
                ("user", "role"): ["Customer", "Admin", "Guest"],
            }.get((safe_class_name.lower(), safe_attr_name.lower()))
            if enum_values:
                schema_def["enum"] = enum_values
            attributes_data.append({"name": safe_attr_name, "schema": schema_def})

        classes_data.append({
            "name": safe_class_name,
            "pk_name": pk_name,
            "attributes": attributes_data
        })

    # ---------------------------------------------------------
    # PASS 2: Semantic Sub-Routing
    # ---------------------------------------------------------
    transient_entities = ["admin", "aiengine", "reporting", "integrationpartner"]

    for rel in relationships:
        source_cls = db.query(UMLClass).filter(UMLClass.class_id == rel.source_class_id).first()
        target_cls = db.query(UMLClass).filter(UMLClass.class_id == rel.target_class_id).first()
        
        if source_cls and target_cls:
            src_name, tgt_name, canonical_src_mult, canonical_tgt_mult = canonicalize_relationship(
                source_cls.class_name,
                target_cls.class_name,
                rel.multiplicity_source,
                rel.multiplicity_target,
            )
            src_name = src_name.replace(" ", "")
            tgt_name = tgt_name.replace(" ", "")
            
            if src_name.lower() in transient_entities or tgt_name.lower() in transient_entities:
                continue

            src_mult = canonical_src_mult or "1"
            tgt_mult = canonical_tgt_mult or "*"
            is_many_to_many = ("*" in src_mult or "n" in src_mult.lower()) and ("*" in tgt_mult or "n" in tgt_mult.lower())
            
            if is_many_to_many:
                # E.g., /jobseekers/{id}/applications
                if set([src_name.lower(), tgt_name.lower()]) == set(["jobseeker", "jobposting"]):
                    nested_routes.append({
                        "parent": src_name,
                        "parent_path": f"{src_name.lower()}s",
                        "child": "Application",
                        "child_path": "applications",
                        "is_junction": True
                    })
            else:
                # Standard One-to-Many nested route (e.g., /employers/{id}/jobpostings)
                if "*" in tgt_mult:
                     nested_routes.append({
                        "parent": src_name,
                        "parent_path": f"{src_name.lower()}s",
                        "child": tgt_name,
                        "child_path": f"{tgt_name.lower()}s",
                        "is_junction": False
                    })

    # Render the YAML
    auth_enabled = any(cls.class_name.replace(" ", "").lower() == "user" for cls in classes_db)
    yaml_content = template.render(
        classes=classes_data,
        nested_routes=nested_routes,
        auth_enabled=auth_enabled,
    )
    return yaml_content