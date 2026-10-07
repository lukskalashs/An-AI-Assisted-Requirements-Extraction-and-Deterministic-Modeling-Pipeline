from sqlalchemy.orm import Session
from models.database import UMLModel, GeneratedDiagram
from services.relationship_normalizer import canonicalize_relationship, inheritance_child_parent


def _class_key(name: str) -> str:
    return name.replace(" ", "").lower()


def _plantuml_label(name: str) -> str:
    return name.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")


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

    class_aliases = {
        _class_key(cls.class_name): f"UmlClass{cls.class_id}"
        for cls in model.classes
    }

    for cls in model.classes:
        alias = class_aliases[_class_key(cls.class_name)]
        label = _plantuml_label(cls.class_name)
        #check if abstract
        if cls.is_abstract:
            class_decl = f'abstract class "{label}" as {alias}'
            puml_lines.append(class_decl + " {")
        else:
            class_decl = f'class "{label}" as {alias}'
            puml_lines.append(class_decl + " {")

        reverse_foreign_key_names = set()
        for relationship in model.relationships:
            if relationship.target_class_id != cls.class_id or not relationship.source_class or not relationship.target_class:
                continue
            _, canonical_target, _, _ = canonicalize_relationship(
                relationship.source_class.class_name,
                relationship.target_class.class_name,
                relationship.multiplicity_source,
                relationship.multiplicity_target,
            )
            if canonical_target.replace(" ", "").lower() != cls.class_name.replace(" ", "").lower():
                reverse_foreign_key_names.add(f"{relationship.source_class.class_name.replace(' ', '')}Id".lower())

        #Attributes
        for attr in cls.attributes:
            if attr.attribute_name.replace(" ", "").lower() in reverse_foreign_key_names:
                continue
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
            method_name = method.method_name.strip()
            if method_name.endswith("()"):
                method_name = method_name[:-2].rstrip()
            puml_lines.append(f"    {vis}{method_name}() : {method.return_type}")
        
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

        canonical_source, canonical_target, canonical_source_mult, canonical_target_mult = canonicalize_relationship(
            rel.source_class.class_name,
            rel.target_class.class_name,
            rel.multiplicity_source,
            rel.multiplicity_target,
        )

        if canonical_source_mult and canonical_source_mult != "None":
            src_mult = f'"{canonical_source_mult}"'
        else:
            src_mult = ""

        if canonical_target_mult and canonical_target_mult != "None":
            tgt_mult = f'"{canonical_target_mult}"'
        else:
            tgt_mult = ""

        if rel_type == "inheritance":
            child_name, parent_name = inheritance_child_parent(
                rel.source_class.class_name,
                rel.target_class.class_name,
                rel.source_evidence,
            )
            source_alias = class_aliases.get(_class_key(parent_name))
            target_alias = class_aliases.get(_class_key(child_name))
        else:
            source_alias = class_aliases.get(_class_key(canonical_source))
            target_alias = class_aliases.get(_class_key(canonical_target))

        if not source_alias or not target_alias:
            raise ValueError(
                "Cannot generate UML relationship because an endpoint does not "
                f"match a class in model {model_id}: "
                f"{canonical_source!r}, {canonical_target!r}"
            )

        if rel_type == "inheritance":
            line = f"{source_alias} {arrow} {target_alias}"
        else:
            line = f'{source_alias} {src_mult} {arrow} {tgt_mult} {target_alias}'
        
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
            
