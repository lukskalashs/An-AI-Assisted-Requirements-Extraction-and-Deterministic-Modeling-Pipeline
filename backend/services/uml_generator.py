from sqlalchemy.orm import Session
from models.database import UMLModel, GeneratedDiagram

def generate_plantuml_syntax(db: Session, model_id:int) -> str:
    """
    Compiles a UML model from the nrelational database
    into a valid PlantUML string representation.
    """

    model = db.query(UMLModel).filter(UMLModel.model_id == model_id).first()
    if not model:
        return None
    
    #Initialise Document Setip

    puml_lines = [
        "@startuml",
        "skinparam classAttributeIconSize 0", #forces +,0, # instead of symbols
        "top to bottom direction",
        ""
    ]

    #Compilation of Classes, attributes and methods.....

    for cls in model.classes:
        #check if abstract
        if cls.is_abstract:
            class_decl = f"abstract class {cls.class_name}"
        else:
            class_decl = f"class {cls.class_name}"
            puml_lines.append(class_decl + " {")

        #Attributes
        for attr in cls.attributes:
            if attr.visibility == "public":
                vis = "+"
            elif attr.visibility == "private":
                vis = "-"

            else:
                vis = "#"
            puml_lines.append(f"    {vis}{attr.attribute_name} : {attr.data_type}")

        #Methods
        for method in cls.methods:
            if method.visibility == "public":
                vis = "+"
            elif method.visibility == "private":
                vis = "-"
            else:
                vis = "#" 
            puml_lines.append(f"    {vis}{method.method_name}() : {method.return_type}")
        
        puml_lines.append("}")
        puml_lines.append("")
    
        

    # Relationships
    for rel in model.relationships:
        rel_type = (rel.relationship_type or "Association").lower()


        #Rule engine for Arrow Types

        arrow = "--"
        if rel_type == "aggregation":
            arrow = "o--"
        elif rel_type == "composition":
            arrow = "*--"
        elif rel_type == "inheritance":
            arrow = "<|--"  # Target <|-- Source means Our souce inherits from target


        # Multiplicity setting (eg 1 or 0..* or 1..* etc)

        if rel.multiplicity_source and rel.multiplicity_source != "None":
            src_mult = f'"{rel.multiplicity_source}"'
        else:
            src_mult = ""

        if rel.multiplicity_target and rel.multiplicity_target != "None":
            tgt_mult = f'"{rel.multiplicity_target}"'
        else:
            tgt_mult = ""

        if rel_type == "inheritance":
            line = f"{rel.target_class.class_naem} {arrow} {rel.source_class.class_name}"
        else:
            line = f"{rel.source_class.class_name} {src_mult} {arrow} {tgt_mult} {rel.target_class.class_name}"
        
        puml_lines.append(line)

    #close documen

    puml_lines.append("")
    puml_lines.append("@enduml")

    final_syntax = "\n".join(puml_lines)

    db.query(GeneratedDiagram).filter(GeneratedDiagram.model_id == model_id).delete()

    #Diagram sent/Persists to the database

    diagram = GeneratedDiagram(
        model_id=model_id,
        plantuml_syntax = final_syntax,
        export_format="plantuml"
       
    )

    db.add(diagram)
    model.status = "diagram_generated"
    db.commit()
    return final_syntax
            
