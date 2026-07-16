from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

# Document schema containing common attributes
class DocumentResponse(BaseModel):
    document_id: int
    project_id: int
    file_name: str
    file_type: str
    chunk_count: int
    processing_status: str
    uploaded_at: datetime

    class Config:
        from_attributes = True

# Base schema containing common attributes
class ProjectBase(BaseModel):
    project_name: str
    description: Optional[str] = None

# Schema for creating a new project (what the frontend sends)
class ProjectCreate(ProjectBase):
    user_id: int

# Schema for reading a project (what the API returns)
class ProjectResponse(ProjectBase):
    project_id: int
    status: str
    created_at: datetime
    
    # This configuration tells Pydantic to read data even if it is a database object
    class Config:
        from_attributes = True


#Human in The Loop
#Schema For Attributes

class AttributeBase(BaseModel):
    attribute_name: str
    data_type: str = "String"
    visibility: str = "public"

class AttributeResponse(AttributeBase):
    attribute_id: int
    class_id: int

    class Config:
        from_attributes = True

#Method Schemas
class MethodBase(BaseModel):
    method_name: str
    return_type: str = "void"
    visibility: str = "public"

class MethodResponse(MethodBase):
    method_id: int
    class_id: int

    class Config:
        from_attributes = True

# Class Schemas
class ClassBase(BaseModel):
    class_name: str
    is_abstract: bool = False
    is_validated: bool = False

class ClassResponse(ClassBase):
    class_id: int
    model_id: int
    attributes: List[AttributeResponse] = []
    methods: List[MethodResponse] = []

    class Config:
        from_attributes = True

#Relationship Schemas
class RelationshipBase(BaseModel):
    relationship_type: str = "Association" # < Association, Aggregation, Composition, Inheritance >
    multiplicity_source: Optional[str] = None
    multiplicity_target: Optional[str] = None

class RelationshipCreate(RelationshipBase):
    source_class_id: int
    target_class_id: int

class RelationshipResponse(RelationshipBase):
    relationship_id: int
    model_id: int
    source_class_id: int
    target_class_id: int

    class Config:
        from_attributes = True

#Complete Model Response
class UMLModelResponse(BaseModel):
    model_id: int
    project_id: int
    document_id: int
    status: str
    created_at: datetime
    classes: List[ClassResponse] = []
    relationships: List[RelationshipResponse] = []

    class Config:
        from_attributes = True
##
## These Schema as a contract between the backend database models (databaase.py) and what the frontend will display/allows edits
## eg. When the ang front end request a full extracted UML Model via UMLModelResponse, Thats is where FastApi will then
## Automaticallly serialize rge classes, the nested attributes, nesred Methods and the lines for relationship from the sqlinto then a 
## json structure <should be type-safe>

