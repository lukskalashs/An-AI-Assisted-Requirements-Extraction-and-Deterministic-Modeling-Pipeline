from sqlalchemy.orm import Session
from models.database import UMLClass, UMLAttribute, UMLRelationship

def generate_plantuml_erd(db: Session, model_id: int) -> str:
    """
    A 4-Pass Semantic Engine that builds a production-grade 3NF ERD.
    It consolidates JSON primitives and dynamically handles many-to-many 
    relationships
    """
    classes = db.query(UMLClass).filter(UMLClass.model_id == model_id).all()
    if not classes:
        return ""

    entity_names = [c.class_name.lower().replace(" ", "") for c in classes]
    schema = {} 

    # ======================================================
    # PASS 1: Build the Schema and Consolidate Primitives
    # ======================================================
    for cls in classes:
        safe_name = cls.class_name.replace(" ", "")
        pk_name = f"{safe_name.lower()}_id"
        
        schema[safe_name] = {
            "pk": pk_name,
            "columns": [],
            "fks": [],
            "relations": [],
            "is_junction": False
        }
        
        attributes = db.query(UMLAttribute).filter(UMLAttribute.class_id == cls.class_id).all()
        for attr in attributes:
            attr_name = attr.attribute_name.replace(" ", "_")
            data_type = attr.data_type if attr.data_type else "VARCHAR"
            clean_type = data_type.replace("List<", "").replace("Map<", "").replace(">", "").strip()
            
            # Skip Entity arrays since they are handled by relationships
            if clean_type.lower() in entity_names:
                continue
                
            # Compress Primitives into JSON columns
            if "list" in data_type.lower() or "map" in data_type.lower():
                schema[safe_name]["columns"].append(f"{attr_name} : JSON")
            else:
                schema[safe_name]["columns"].append(f"{attr_name} : {data_type}")

    # ---------------------------------------------------------
    # PASS 2: Semantic Relationship Normalisation
    # ---------------------------------------------------------
    relationships = db.query(UMLRelationship).filter(UMLRelationship.model_id == model_id).all()

    for rel in relationships:
        source_cls = db.query(UMLClass).filter(UMLClass.class_id == rel.source_class_id).first()
        target_cls = db.query(UMLClass).filter(UMLClass.class_id == rel.target_class_id).first()
        
        if source_cls and target_cls:
            src_name = source_cls.class_name.replace(" ", "")
            tgt_name = target_cls.class_name.replace(" ", "")
            
            src_mult = rel.multiplicity_source or "1"
            tgt_mult = rel.multiplicity_target or "*"
            
            # Detect Many-to-Many relationships dynamically
            is_many_to_many = ("*" in src_mult or "n" in src_mult.lower()) and ("*" in tgt_mult or "n" in tgt_mult.lower())
            
            if is_many_to_many:
                # Dynamically name junction tables for any generic SRS document
                junction_table = f"{src_name}_{tgt_name}_Link"
                
                if junction_table not in schema:
                    schema[junction_table] = {
                        "pk": f"{junction_table.lower()}_id",
                        "columns": ["created_at : TIMESTAMP"], # Generic useful audit column for any link
                        "fks": [f"{src_name.lower()}_id <<FK>>", f"{tgt_name.lower()}_id <<FK>>"],
                        "relations": [],
                        "is_junction": True
                    }
                
                # Link both parent tables to the new junction table
                schema[src_name]["relations"].append(f"{src_name} ||--o{{ {junction_table}")
                schema[tgt_name]["relations"].append(f"{tgt_name} ||--o{{ {junction_table}")
            
            else:
                # Standard One-to-Many relationship normalisation
                if f"{src_name.lower()}_id <<FK>>" not in schema[tgt_name]["fks"]:
                    schema[tgt_name]["fks"].append(f"{src_name.lower()}_id <<FK>>")
                    schema[src_name]["relations"].append(f"{src_name} ||--o{{ {tgt_name}")

    # ------------------------------------------------------
    # PASS 3: Professional PlantUML Rendering
    # -----------------------------------------------------
    puml = []
    puml.append("@startuml")
    puml.append("!theme plain")
    puml.append("hide circle")
    puml.append("left to right direction")
    puml.append("skinparam linetype ortho")
    puml.append("skinparam nodesep 70")
    puml.append("skinparam ranksep 100")
    puml.append("skinparam class {")
    puml.append("    BackgroundColor White")
    puml.append("    BorderColor #333333")
    puml.append("    ArrowColor #005599")
    puml.append("}")
    puml.append("")

    for table_name, data in schema.items():
        stereotype = "<<Junction>>" if data.get("is_junction") else ""
        puml.append(f'entity "{table_name}" as {table_name} {stereotype} {{')
        puml.append(f'  * {data["pk"]} : INT <<PK>>')
        puml.append("  --")
        for fk in data["fks"]: puml.append(f'  * {fk}')
        for col in data["columns"]: puml.append(f'  {col}')
        puml.append("}")
        puml.append("")

    for table_name, data in schema.items():
        for relation in data["relations"]:
            puml.append(relation)

    puml.append("@enduml")
    return "\n".join(puml)