import os
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session
from models.database import UMLClass, UMLAttribute, UMLRelationship
from services.relationship_normalizer import canonicalize_relationship

# Set up the Jinja2 Environment to look in the templates folder
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

def map_to_csharp_type(raw_type: str) -> str:
    """Maps gemeric uml types to C# equivalents"""

    t = raw_type.lower()
    if t in ["string", "str", "text"]: return "string"
    if t in ["int", "integer", "number"]: return "int"
    if t in ["float", "double", "decimal"]: return "decimal"
    if t in ["bool", "boolean"]: return "bool"
    if t in ["date", "datetime"]: return "DateTime"

    # Handle generic Lists/Maps from the AI
    if "list<" in raw_type:
        inner_type = map_to_csharp_type(raw_type.replace("List<", "").replace(">", "").strip())
        return f"List<{inner_type}>"
    if "map<" in raw_type:
        return "Dictionary<string, string>" # Simplified fallback for generic maps
        
    return "string" # Fallback

def generate_csharp_classes(db: Session, model_id: int) -> dict:
    """
    Generates C# class files (as strings) for all entities in a given model.
    Returns a dictionary mapping class names to their generated source code.
    """
    classes = db.query(UMLClass).filter(UMLClass.model_id == model_id).all()
    if not classes:
        return {}

    # Load the template
    template = env.get_template("csharp_class.jinja2")
    
    generated_code = {}
    relationships = db.query(UMLRelationship).filter(UMLRelationship.model_id == model_id).all()
    class_by_id = {c.class_id: c for c in classes}

    for cls in classes:
        safe_class_name = cls.class_name.replace(" ", "")
        
        # 1. Prepare Attributes
        properties = []
        initializers = [] # Now this will hold dictionaries
        foreign_key_names = set()
        reverse_foreign_key_names = set()
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
            canonical_target_id = next(
                (item.class_id for item in classes if item.class_name.replace(" ", "").lower() == canonical_target.replace(" ", "").lower()),
                target_cls.class_id,
            )
            if canonical_target_id == cls.class_id:
                foreign_key_names.add(f"{canonical_source.replace(' ', '')}Id".lower())
            elif rel.target_class_id == cls.class_id:
                reverse_foreign_key_names.add(f"{source_cls.class_name.replace(' ', '')}Id".lower())
        
        attributes = db.query(UMLAttribute).filter(UMLAttribute.class_id == cls.class_id).all()
        for attr in attributes:
            attr_name = attr.attribute_name.replace(" ", "")
            if attr_name.lower() in reverse_foreign_key_names:
                continue
            if attr_name.lower() in foreign_key_names:
                cs_type = "int"
            else:
                cs_type = map_to_csharp_type(attr.data_type if attr.data_type else "String")
            
            # Capitalize property names for C# conventions
            pascal_name = attr_name[0].upper() + attr_name[1:] if attr_name else "Unknown"
            properties.append({"type": cs_type, "name": pascal_name})
            
            # Append a dictionary containing both name and type
            if cs_type.startswith("List") or cs_type.startswith("Dictionary"):
                initializers.append({"name": pascal_name, "type": cs_type})

        # 2. Prepare Navigation Properties (Relationships)
        navigation_properties = []
        for rel in relationships:
            source_cls = class_by_id.get(rel.source_class_id)
            target_cls = class_by_id.get(rel.target_class_id)
            if not source_cls or not target_cls:
                continue
            canonical_source, canonical_target, _, canonical_target_mult = canonicalize_relationship(
                source_cls.class_name,
                target_cls.class_name,
                rel.multiplicity_source,
                rel.multiplicity_target,
            )
            canonical_source_id = next(
                (item.class_id for item in classes if item.class_name.replace(" ", "").lower() == canonical_source.replace(" ", "").lower()),
                source_cls.class_id,
            )
            if canonical_source_id == cls.class_id:
                tgt_name = canonical_target.replace(" ", "")

                if "*" in (canonical_target_mult or ""):
                    navigation_properties.append({"type": f"List<{tgt_name}>", "name": f"{tgt_name}s"})
                    initializers.append({"name": f"{tgt_name}s", "type": f"List<{tgt_name}>"})
                else:
                    navigation_properties.append({"type": tgt_name, "name": tgt_name})

        # 3. Render the Template
        
        class_code = template.render(
            class_name=safe_class_name,
            properties=properties,
            navigation_properties=navigation_properties,
            initializers=initializers
        )
        
        generated_code[safe_class_name] = class_code

    return generated_code