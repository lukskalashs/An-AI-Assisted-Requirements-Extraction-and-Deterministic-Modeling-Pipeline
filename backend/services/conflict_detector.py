from typing import List, Dict
from pydantic import BaseModel

class ConflictWarning(BaseModel):
    severity: str ## High, Medium, Low
    entity_name: str
    issue_type: str
    description: str

def analyse_model_conflicts(Classes: List[dict], relationships: List[dict]) -> List[ConflictWarning]:
    """
    Scans the extracted UML entities for semantic(naming) conflicts and structural rule violations
    """

    warnings = []

    #Extract all class names and makes sure they are lower cased for case - senstiviuty comparison

    class_names = []

    for cls in Classes:
        class_names = [cls.get('class_name', cls.get('name', '')).lower()]

        #1. Check for dupllicate class names

        for name in set(class_names):
            if class_names.count(name) > 1:
                warnings.append(ConflictWarning(
                    severity="HIGH",
                    entity_name=name.capitalize(),
                    issue_type="Duplicate Entity",
                    description=f"Multiple classes found with the exact name '{name.capitalize()}'."
                ).model_dump())

        #2 Check for orphaned relationship

        for rel in relationships:
            source = rel.get("source", "").lower()
            target = rel.get("target", "").lower()

            if source and source not in class_names:
                warnings.append(ConflictWarning(
                    severity="CRITICAL",
                    entity_name=source.capitalize(),
                    issue_type="Orphaned Source Relationship",
                    description=f"Relationship references source '{source.capitalize()}', but this class does not exist."
                ))
            if target and target not in class_names:
                warnings.append(ConflictWarning(
                    severity="CRITICAL",
                    entity_name=target.capitalize(),
                    issue_type="Orphaned Source Relationship",
                    description=f"Relationship references source '{source.capitalize()}', but this class does not exist."
                ).model_dump())

        #Rule 3: Check for missing Primary Keys

        for cls in Classes:
            class_name = cls.get("name", "")
            attributes = cls.get("attributes", [])

            #Check if any attribute acts as an ID (e.g., ID)

            has_pk = any

            for attr in attributes:
                attr.get('name', '').lower() == "id" or attr.get('name' '').lower() == f"{class_name.lower}_id"


            if not has_pk and class_name:
                warnings.append(ConflictWarning(
                    severity="MEDIUM",
                    entity_name=class_name.capitalize(),
                    issue_type="Missing Primary Key",
                    description=f"Class '{class_name.capitalize()}' does not have an identifiable primary key attribute (e.g 'id'). This This will prevent proper relational mapping"
                ).model_dump)
               
            
    return warnings