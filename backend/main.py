from fastapi import FastAPI, Depends, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from models.database import engine, Base, SessionLocal, Project
from typing import List
import PyPDF2
import io
from models.database import Document
import schemas
from services.nlp_processor import chunk_text
from services.llm_pipeline import extracted_uml_entities_from_chunks
from models.database import UMLModel, UMLClass, UMLAttribute, UMLRelationship, UMLMethod, GeneratedDiagram
from services.uml_generator import generate_plantuml_syntax
from services.conflict_detector import analyse_model_conflicts
from services.erd_visual_generator import generate_plantuml_erd
from services.code_generator import generate_csharp_classes
from services.drawio_generator import generate_drawio_xml
from services.svg_generator import generate_diagram_svg
from services.yaml_generator import generate_openapi_yaml
from services.relationship_normalizer import canonicalize_relationship
from fastapi import Response 
import re
import os
import zipfile
# from generators.erd_generator import generate_sql_ddl


# Create the database tables
Base.metadata.create_all(bind=engine)


def ensure_provenance_columns():
    """Add provenance columns to existing SQLite databases created before traceability was added."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    migrations = [
        ("uml_classes", "source_evidence"),
        ("uml_classes", "entity_kind"),
        ("uml_attributes", "source_evidence"),
        ("uml_methods", "source_evidence"),
        ("uml_relationships", "source_evidence"),
        ("uml_relationships", "relationship_label"),
    ]
    with engine.begin() as connection:
        for table, column in migrations:
            existing_columns = {item["name"] for item in inspector.get_columns(table)}
            if column not in existing_columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} TEXT"))


ensure_provenance_columns()

app = FastAPI(
    title="AI-Assisted UML Extraction API",
    description="Backend for processing Software Requirements Specification (SRS) documents and generating UML diagrams",
    version="1.0.0",
)

def evidence_for(raw_text: str, subject: str, supplied: str | None = None) -> str | None:
    """Return source-backed evidence, with a deterministic sentence fallback."""
    normalised_text = re.sub(r"\s+", " ", raw_text or "").strip().lower()
    if supplied and supplied.strip():
        normalised_supplied = re.sub(r"\s+", " ", supplied).strip().lower()
        if normalised_supplied and normalised_supplied in normalised_text:
            return supplied.strip()
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", raw_text or "") if paragraph.strip()]
    subject_words = [word for word in re.findall(r"[A-Za-z0-9]+", subject or "") if len(word) > 2]
    for paragraph in paragraphs:
        if subject_words and all(word.lower() in paragraph.lower() for word in subject_words):
            return paragraph
    # PDF extraction and model output often disagree on paragraph boundaries.
    # Sentence-level matching is more reliable and keeps provenance non-empty.
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", normalised_text) if sentence.strip()]
    for sentence in sentences:
        if subject_words and all(word.lower() in sentence for word in subject_words):
            return sentence
    for sentence in sentences:
        if subject_words and any(word.lower() in sentence for word in subject_words):
            return sentence
    return None


def relationship_evidence_for(
    raw_text: str, source_class: str, target_class: str, supplied: str | None = None
) -> str:
    """Always retain a source passage for a persisted relationship."""
    evidence = evidence_for(raw_text, f"{source_class} {target_class}", supplied)
    if evidence:
        return evidence
    # A relationship can be expressed with pronouns or a heading, so use the
    # first source passage mentioning either endpoint before falling back to
    # the first non-empty passage. This is deterministic and never fabricated.
    source = (source_class or "").strip().lower()
    target = (target_class or "").strip().lower()
    passages = [p.strip() for p in re.split(r"\n\s*\n", raw_text or "") if p.strip()]
    for passage in passages:
        lowered = passage.lower()
        if (source and source in lowered) or (target and target in lowered):
            return passage
    return passages[0] if passages else (raw_text or "").strip()

# Database Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def mark_model_modified(db: Session, model_id: int) -> None:
    model = db.query(UMLModel).filter(UMLModel.model_id == model_id).first()
    if model:
        model.status = "pending review"


@app.get("/")
def root():
    return {"message": "Welcome to the UML Extraction API. System is running."}


@app.post("/projects/", response_model=schemas.ProjectResponse)
def create_project(project: schemas.ProjectCreate, db: Session = Depends(get_db)):
    """
    Create a new project workspace for requirement extraction.
    """
    db_project = Project(
        user_id=project.user_id,
        project_name=project.project_name,
        description=project.description
    )
    
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    
    return db_project

@app.get("/projects/", response_model=List[schemas.ProjectResponse])
def read_projects(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Retrieve a list of all project workspaces.
    """
    projects = db.query(Project).offset(skip).limit(limit).all()
    return projects

@app.get("/projects/{project_id}", response_model=schemas.ProjectResponse)
def read_project(project_id: int, db: Session = Depends(get_db)):
    """
    Get details of a specific project workspace by its ID
    """

    db_project = db.query(Project).filter(Project.project_id == project_id).first()

    if db_project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return db_project

@app.post("/projects/{project_id}/documents/", response_model=schemas.DocumentResponse)
async def upload_document(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload an SRS document (TXT or pdf) to a specific project workspace and extract its raw text
    """

    # Check if the project exits
    db_project = db.query(Project).filter(Project.project_id == project_id).first()
    
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check the file extension (only allow .txt and .pdf)
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in ["txt", "pdf"]:
        raise HTTPException(status_code=400, detail="Invalid file type. Only .txt and .pdf files are allowed.")
    
    raw_text = ""

    # Read the file content based on its type

    content = await file.read()

    if file_extension == "txt":
        raw_text = content.decode("utf-8", errors='ignore')

    elif file_extension == "pdf":
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
        for page in pdf_reader.pages:
            extracted = page.extract_text()
            if extracted:
                raw_text += extracted + "\n"

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract any text from the document.")
    
    raw_text = raw_text.encode("utf-8", "ignore").decode("utf-8")
    
    #Process the text
    pipeline_stats = {}
    text_chunks = chunk_text(raw_text, pipeline_stats=pipeline_stats)
    calculated_chunk_count = len(text_chunks)
    
    # Save the Document and extracted text to the database

    new_document = Document(
        project_id=project_id,
        file_name=file.filename,
        file_type=file_extension,
        raw_text=raw_text,
        chunk_count= calculated_chunk_count,  # This will be updated later after processing
        processing_status="chunked"
    )
    db.add(new_document)
    db.commit()
    db.refresh(new_document)

    return {
        "document_id": new_document.document_id,
        "project_id": new_document.project_id,
        "file_name": new_document.file_name,
        "file_type": new_document.file_type,
        "chunk_count": new_document.chunk_count,
        "processing_status": new_document.processing_status,
        "uploaded_at": new_document.uploaded_at,
        "nlp_pipeline": pipeline_stats,
    }

@app.post("/documents/{document_id}/extract")
def extract_uml_entities_from_document(document_id: int, db: Session = Depends(get_db)):
    """
    Trigger the NLP and LLM pipeline to extract UML entities from a saved document.
    Also make the persistebr in our db
    """

    document = db.query(Document).filter(Document.document_id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if not document.raw_text:
        raise HTTPException(status_code=400, detail="Document has no raw text to process.")

    return extract_model_from_documents([document], db)


@app.post("/projects/{project_id}/extract")
def extract_uml_entities_from_project(project_id: int, db: Session = Depends(get_db)):
    documents = (
        db.query(Document)
        .filter(Document.project_id == project_id)
        .order_by(Document.document_id)
        .all()
    )
    if not documents:
        raise HTTPException(status_code=404, detail="No specification documents were uploaded to this project.")
    if any(not document.raw_text for document in documents):
        raise HTTPException(status_code=400, detail="Every specification document must contain extractable text.")

    return extract_model_from_documents(documents, db)


def extract_model_from_documents(documents: list[Document], db: Session):
    document = documents[0]
    source_text = "\n\n".join(item.raw_text for item in documents)
    pipeline_stats = {}
    chunks = chunk_text(source_text, pipeline_stats=pipeline_stats)

    extracted_json = extracted_uml_entities_from_chunks(chunks)

    extracted_classes = extracted_json.get("classes", [])
    extacted_relationships = extracted_json.get("relationships",[])
    model_warnings = analyse_model_conflicts(extracted_classes, extacted_relationships)


    new_model = UMLModel(
        project_id = document.project_id,
        document_id = document.document_id,
        status = "pending review"
    )
    db.add(new_model)
    db.flush()

    class_name_map = {}

    for cls_data in extracted_json.get("classes", []):
        db_class = UMLClass(
            model_id = new_model.model_id,
            class_name=cls_data.get("class_name"),
            is_abstract=cls_data.get("is_abstract", False),
            is_validated=False,
            entity_kind=cls_data.get("entity_kind", "persistent_entity"),
            source_evidence=evidence_for(source_text, cls_data.get("class_name", ""), cls_data.get("evidence"))

        )
        db.add(db_class)
        db.flush()
        


        # Saving the reference for the relationship index lookup for later
        safe_class_name = str(db_class.class_name).strip().lower()
        class_name_map[safe_class_name] = db_class.class_id

       
       

        #Insert Attributes
        for attr in cls_data.get("attributes", []):
            db_attribute = UMLAttribute(
                class_id=db_class.class_id,
                attribute_name=attr.get("name"),
                data_type=attr.get("data_type", "String"),
                visibility=attr.get("visibility", "public"),
                source_evidence=evidence_for(source_text, attr.get("name", ""), attr.get("evidence"))

            )
            db.add(db_attribute)

        #Insert Methods
        for method in cls_data.get("methods", []):
            db_method = UMLMethod(
                class_id = db_class.class_id,
                method_name = method.get("name"),
                return_type = method.get("return_type", "void"),
                visibility=method.get("visibility", "public"),
                source_evidence=evidence_for(source_text, method.get("name", ""), method.get("evidence"))
            )
            db.add(db_method)
    
    # Populate The relationship extracted
    relationships_saved = 0
    persisted_relationship_keys = set()
    for relationship_data in extracted_json.get("relationships", []):
        src_name = relationship_data.get("source_class", "").strip().lower()
        tgt_name = relationship_data.get("target_class", "").strip().lower()

        canonical_src, canonical_tgt, source_mult, target_mult = canonicalize_relationship(
            src_name,
            tgt_name,
            relationship_data.get("multiplicity_source"),
            relationship_data.get("multiplicity_target"),
        )
        src_name = canonical_src.strip().lower()
        tgt_name = canonical_tgt.strip().lower()

        src_id = class_name_map.get(src_name)
        tgt_id = class_name_map.get(tgt_name)

        if src_id and tgt_id:
            relationship_type = relationship_data.get("relationship_type", "Association")
            endpoint_key = (
                (src_id, tgt_id)
                if relationship_type == "Inheritance"
                else tuple(sorted((src_id, tgt_id)))
            )
            relationship_key = (endpoint_key, relationship_type)
            if relationship_key in persisted_relationship_keys:
                continue
            db_relationship = UMLRelationship(
                model_id=new_model.model_id,
                source_class_id = src_id,
                target_class_id = tgt_id,
                relationship_type=relationship_data.get("relationship_type", "Association"),
                relationship_label=relationship_data.get("relationship_label"),
                multiplicity_source=source_mult,
                multiplicity_target=target_mult,
                source_evidence=relationship_evidence_for(
                    source_text,
                    relationship_data.get("source_class", ""),
                    relationship_data.get("target_class", ""),
                    relationship_data.get("evidence"),
                )
            )
            db.add(db_relationship)
            persisted_relationship_keys.add(relationship_key)
            relationships_saved +=1
        else:
            print(f"Warning: Dropped relationship between '{src_name}' and '{tgt_name}' due to class mismatch.")
    
    for item in documents:
        item.processing_status = "extracted"
    db.commit()

    return {
        "message": "UML Metamodel extraction successfully processed and committed to relational tables.",
        "model_id": new_model.model_id,
        "document_id": document.document_id,
        "document_ids": [item.document_id for item in documents],
        "classes_extracted_count": len(class_name_map),
        "relationships_extracted_count": relationships_saved,
        "warnings": model_warnings,
        "nlp_pipeline": pipeline_stats
    }


@app.post("/models/{model_id}/generate")
def generate_diagram(model_id: int, db: Session = Depends(get_db)):
    """
    Compile the extracted database entities into PlanyUml diagram.
    """

    syntax = generate_plantuml_syntax(db, model_id)

    if not syntax:
        raise HTTPException(status_code=404, detail="Model not found!!")
    
    return {
        "message": "PlantUML diagram successfully generated",
        "model_id": model_id,
        "plantuml_syntax": syntax
    }


@app.get("/models/{model_id}/generated-diagram")
def get_generated_diagram(model_id: int, db: Session = Depends(get_db)):
    model = db.query(UMLModel).filter(UMLModel.model_id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.status != "diagram_generated":
        raise HTTPException(status_code=409, detail="The model has changed. Confirm and generate the diagrams again.")
    diagram = (
        db.query(GeneratedDiagram)
        .filter(GeneratedDiagram.model_id == model_id)
        .order_by(GeneratedDiagram.diagram_id.desc())
        .first()
    )
    if not diagram:
        raise HTTPException(status_code=404, detail="Generated diagram not found")
    return {
        "message": "Generated PlantUML diagram retrieved.",
        "model_id": model_id,
        "plantuml_syntax": diagram.plantuml_syntax,
    }


# Human - In - The - Loop - endpoints

@app.get("/Models/{model_id}")
def get_uml_model(model_id: int, db: Session = Depends(get_db)):
    """
    Fetches the completed extracted UML model and forces deep serialisation
    so the Angular frontend doesn't crash on undefined arrays.
    """
    db_model = db.query(UMLModel).filter(UMLModel.model_id == model_id).first()

    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found")

    source_documents = (
        db.query(Document)
        .filter(Document.project_id == db_model.project_id)
        .order_by(Document.document_id)
        .all()
    )
    source_text = "\n\n".join(item.raw_text or "" for item in source_documents)
    pipeline_stats = {}
    chunk_text(source_text, pipeline_stats=pipeline_stats)

    # Manually construct the dictionary to guarantee exact frontend match
    return {
        "model_id": db_model.model_id,
        "status": db_model.status,
        "nlp_pipeline": pipeline_stats,
        "classes": [
            {
                "class_id": c.class_id,
                "class_name": c.class_name,
                "is_abstract": c.is_abstract,
                "is_validated": c.is_validated,
                "entity_kind": c.entity_kind or "persistent_entity",
                "source_evidence": evidence_for(source_text, c.class_name, c.source_evidence),
                "attributes": [{
                    "attribute_id": a.attribute_id,
                    "class_id": a.class_id,
                    "attribute_name": a.attribute_name,
                    "data_type": a.data_type,
                    "visibility": a.visibility,
                    "source_evidence": evidence_for(source_text, a.attribute_name, a.source_evidence)
                } for a in c.attributes],
                "methods": [{
                    "method_id": m.method_id,
                    "class_id": m.class_id,
                    "method_name": m.method_name,
                    "return_type": m.return_type,
                    "visibility": m.visibility,
                    "source_evidence": evidence_for(source_text, m.method_name, m.source_evidence)
                } for m in c.methods]
            } for c in db_model.classes
        ],
        "relationships": [
            {
                "relationship_id": r.relationship_id,
                "source_class": {
                    "class_id": r.source_class.class_id if r.source_class else None,
                    "class_name": r.source_class.class_name if r.source_class else ""
                },
                "target_class": {
                    "class_id": r.target_class.class_id if r.target_class else None,
                    "class_name": r.target_class.class_name if r.target_class else ""
                },
                "relationship_type": r.relationship_type if r.relationship_type in {
                    "Association", "Aggregation", "Composition", "Inheritance"
                } else "Association",
                "relationship_label": r.relationship_label or (
                    r.relationship_type if r.relationship_type not in {
                        "Association", "Aggregation", "Composition", "Inheritance"
                    } else None
                ),
                "multiplicity_source": r.multiplicity_source,
                "multiplicity_target": r.multiplicity_target,
                "source_evidence": evidence_for(
                    source_text,
                    f"{r.source_class.class_name if r.source_class else ''} {r.target_class.class_name if r.target_class else ''}",
                    r.source_evidence
                )
            } for r in db_model.relationships
        ]
    }


@app.get("/models/{model_id}/source-documents")
def get_model_source_documents(model_id: int, db: Session = Depends(get_db)):
    db_model = db.query(UMLModel).filter(UMLModel.model_id == model_id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found")
    documents = (
        db.query(Document)
        .filter(Document.project_id == db_model.project_id)
        .order_by(Document.document_id)
        .all()
    )
    return [
        {"document_id": item.document_id, "file_name": item.file_name, "raw_text": item.raw_text}
        for item in documents
    ]


@app.put("/relationships/{relationship_id}", response_model=schemas.RelationshipResponse)


def update_uml_relationship(relationship_id: int, rel_update: schemas.RelationshipBase, db:Session = Depends(get_db)):
    """
    Here You Able to update relationships (e.g. Fix a multiplicity or Change Association to composition)
    All That happens During the the HITL reviewing process


    """

    db_rel = db.query(UMLRelationship).filter(UMLRelationship.relationship_id == relationship_id).first()

    if not db_rel:
        raise HTTPException(status_code=404, detail="Relationship not found")
    
    db_rel.relationship_type = rel_update.relationship_type
    db_rel.relationship_label = rel_update.relationship_label
    db_rel.multiplicity_source = rel_update.multiplicity_source
    db_rel.multiplicity_target = rel_update.multiplicity_target
    mark_model_modified(db, db_rel.model_id)

    db.commit()
    db.refresh(db_rel)
    return db_rel

@app.post("/models/{model_id}/relationships", response_model=schemas.RelationshipResponse)
def create_uml_relationship(model_id: int, relationship: schemas.RelationshipCreate, db: Session = Depends(get_db)):
    """Create a relationship between two classes in the selected UML model."""
    db_model = db.query(UMLModel).filter(UMLModel.model_id == model_id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found")

    source_class = db.query(UMLClass).filter(
        UMLClass.class_id == relationship.source_class_id,
        UMLClass.model_id == model_id
    ).first()
    target_class = db.query(UMLClass).filter(
        UMLClass.class_id == relationship.target_class_id,
        UMLClass.model_id == model_id
    ).first()
    if not source_class or not target_class:
        raise HTTPException(status_code=400, detail="Source and target must belong to the selected model")

    db_relationship = UMLRelationship(
        model_id=model_id,
        **relationship.model_dump()
    )
    db.add(db_relationship)
    db_model.status = "pending review"
    db.commit()
    db.refresh(db_relationship)
    return db_relationship

@app.put("/classes/{class_id}", response_model=schemas.ClassResponse)
def update_uml_class(class_id:int, class_update: schemas.ClassBase, db: Session = Depends(get_db)):
    """
    Update a specific class (eg. Change name, Mark it as abstract all of that during The HITL review Process)
    """

    db_class = db.query(UMLClass).filter(UMLClass.class_id == class_id).first()

    if not db_class:
        raise HTTPException(status_code=404, detail="Class Not Found")
    
    #Update The databse with fileds that the user input after checking what the Model looks like and feels the need o uopdate what the ai ouputedd

    db_class.class_name = class_update.class_name
    db_class.is_abstract = class_update.is_abstract
    db_class.is_validated = class_update.is_validated
    db_class.entity_kind = class_update.entity_kind
    mark_model_modified(db, db_class.model_id)

    db.commit()
    db.refresh(db_class)
    return db_class

@app.post("/models/{model_id}/classes", response_model=schemas.ClassResponse)
def create_uml_class(model_id: int, class_data: schemas.ClassBase, db: Session = Depends(get_db)):
    """Create a class during human-in-the-loop model review."""
    db_model = db.query(UMLModel).filter(UMLModel.model_id == model_id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found")
    if not class_data.class_name.strip():
        raise HTTPException(status_code=400, detail="Class name is required")

    db_class = UMLClass(model_id=model_id, **class_data.model_dump())
    db.add(db_class)
    db_model.status = "pending review"
    db.commit()
    db.refresh(db_class)
    return db_class


@app.delete("/classes/{class_id}")
def delete_uml_class(class_id: int, db: Session = Depends(get_db)):
    db_class = db.query(UMLClass).filter(UMLClass.class_id == class_id).first()
    if not db_class:
        raise HTTPException(status_code=404, detail="Class not found")

    model_id = db_class.model_id
    db.query(UMLRelationship).filter(
        (UMLRelationship.source_class_id == class_id) |
        (UMLRelationship.target_class_id == class_id)
    ).delete(synchronize_session=False)
    db.delete(db_class)
    mark_model_modified(db, model_id)
    db.commit()
    return {"message": "Class deleted", "class_id": class_id}


@app.post("/classes/{class_id}/attributes", response_model=schemas.AttributeResponse)
def create_uml_attribute(class_id: int, attribute: schemas.AttributeBase, db: Session = Depends(get_db)):
    db_class = db.query(UMLClass).filter(UMLClass.class_id == class_id).first()
    if not db_class:
        raise HTTPException(status_code=404, detail="Class not found")

    db_attribute = UMLAttribute(class_id=class_id, **attribute.model_dump())
    db.add(db_attribute)
    mark_model_modified(db, db_class.model_id)
    db.commit()
    db.refresh(db_attribute)
    return db_attribute


@app.put("/attributes/{attribute_id}", response_model=schemas.AttributeResponse)
def update_uml_attribute(attribute_id: int, attribute: schemas.AttributeBase, db: Session = Depends(get_db)):
    db_attribute = db.query(UMLAttribute).filter(UMLAttribute.attribute_id == attribute_id).first()
    if not db_attribute:
        raise HTTPException(status_code=404, detail="Attribute not found")

    for field, value in attribute.model_dump().items():
        setattr(db_attribute, field, value)
    mark_model_modified(db, db_attribute.uml_class.model_id)
    db.commit()
    db.refresh(db_attribute)
    return db_attribute


@app.delete("/attributes/{attribute_id}")
def delete_uml_attribute(attribute_id: int, db: Session = Depends(get_db)):
    db_attribute = db.query(UMLAttribute).filter(UMLAttribute.attribute_id == attribute_id).first()
    if not db_attribute:
        raise HTTPException(status_code=404, detail="Attribute not found")
    mark_model_modified(db, db_attribute.uml_class.model_id)
    db.delete(db_attribute)
    db.commit()
    return {"message": "Attribute deleted", "attribute_id": attribute_id}


@app.post("/classes/{class_id}/methods", response_model=schemas.MethodResponse)
def create_uml_method(class_id: int, method: schemas.MethodBase, db: Session = Depends(get_db)):
    db_class = db.query(UMLClass).filter(UMLClass.class_id == class_id).first()
    if not db_class:
        raise HTTPException(status_code=404, detail="Class not found")

    db_method = UMLMethod(class_id=class_id, **method.model_dump())
    db.add(db_method)
    mark_model_modified(db, db_class.model_id)
    db.commit()
    db.refresh(db_method)
    return db_method


@app.put("/methods/{method_id}", response_model=schemas.MethodResponse)
def update_uml_method(method_id: int, method: schemas.MethodBase, db: Session = Depends(get_db)):
    db_method = db.query(UMLMethod).filter(UMLMethod.method_id == method_id).first()
    if not db_method:
        raise HTTPException(status_code=404, detail="Method not found")

    for field, value in method.model_dump().items():
        setattr(db_method, field, value)
    mark_model_modified(db, db_method.uml_class.model_id)
    db.commit()
    db.refresh(db_method)
    return db_method


@app.delete("/methods/{method_id}")
def delete_uml_method(method_id: int, db: Session = Depends(get_db)):
    db_method = db.query(UMLMethod).filter(UMLMethod.method_id == method_id).first()
    if not db_method:
        raise HTTPException(status_code=404, detail="Method not found")
    mark_model_modified(db, db_method.uml_class.model_id)
    db.delete(db_method)
    db.commit()
    return {"message": "Method deleted", "method_id": method_id}


@app.delete("/relationships/{relationship_id}")
def delete_uml_relationship(relationship_id: int, db: Session = Depends(get_db)):
    db_relationship = db.query(UMLRelationship).filter(UMLRelationship.relationship_id == relationship_id).first()
    if not db_relationship:
        raise HTTPException(status_code=404, detail="Relationship not found")
    mark_model_modified(db, db_relationship.model_id)
    db.delete(db_relationship)
    db.commit()
    return {"message": "Relationship deleted", "relationship_id": relationship_id}


@app.get("/models/{model_id}/erd-visual")
def get_visual_erd_diagram(model_id: int, db: Session = Depends(get_db)):
    """
    Phase 2: Generates a normalized Entity-Relationship Diagram (ERD) (Crow's Foot) notation.
    Automatically resolves Many-to-Many relationships into Junction Tables.
    """
    # Verify the model exists
    db_model = db.query(UMLModel).filter(UMLModel.model_id == model_id).first()
    
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found!")
    
    # Run the 4-Pass Schema Compiler to get the Visual Syntax
    plantuml_syntax = generate_plantuml_erd(db, model_id)
    
    if not plantuml_syntax:
        raise HTTPException(status_code=400, detail="Could not generate ERD. Ensure the model has extracted classes.")
    
    return {
        "message": "Visual ERD syntax successfully generated.",
        "model_id": model_id,
        "plantuml_erd_syntax": plantuml_syntax
    }

@app.get("/models/{model_id}/code/csharp")
def export_csharp_code(model_id: int, db: Session = Depends(get_db)):
    """
    Phase 2 (Tier 2): Generates C# Entity classes based on the validated UML model.
    Proves the system can generate application-layer boilerplate deterministically.
    """
    # Verify the model exists
    db_model = db.query(UMLModel).filter(UMLModel.model_id == model_id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found!")
    
    try:
        generated_classes = generate_csharp_classes(db, model_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot generate C# classes: {exc}",
        ) from exc
    
    if not generated_classes:
        raise HTTPException(status_code=400, detail="Could not generate code. Ensure the model has extracted classes.")
    
    return {
        "message": "C# Code successfully generated.",
        "model_id": model_id,
        "classes": generated_classes
    }


@app.get("/models/{model_id}/code/csharp/download")
def download_csharp_classes(model_id: int, db: Session = Depends(get_db)):
    db_model = db.query(UMLModel).filter(UMLModel.model_id == model_id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found!")

    try:
        generated_classes = generate_csharp_classes(db, model_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot generate C# classes: {exc}",
        ) from exc
    if not generated_classes:
        raise HTTPException(status_code=400, detail="Could not generate code. Ensure the model has extracted classes.")

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for class_name, class_code in generated_classes.items():
            safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", class_name).strip("_") or "GeneratedClass"
            bundle.writestr(f"{safe_name}.cs", class_code)

    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="DomainModels_{model_id}.zip"'},
    )


@app.get("/models/{model_id}/diagram/{diagram_type}/drawio")
def export_drawio_diagram(model_id: int, diagram_type: str, db: Session = Depends(get_db)):
    if not db.query(UMLModel).filter(UMLModel.model_id == model_id).first():
        raise HTTPException(status_code=404, detail="Model not found")
    if diagram_type not in {"uml", "erd"}:
        raise HTTPException(status_code=422, detail="Diagram type must be 'uml' or 'erd'.")
    diagram = generate_drawio_xml(db, model_id, diagram_type)
    if not diagram:
        raise HTTPException(status_code=400, detail=f"Could not generate the {diagram_type.upper()} diagram for this model.")
    return Response(
        content=diagram,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{diagram_type.upper()}_Model_{model_id}.drawio"'},
    )


@app.get("/models/{model_id}/diagram/{diagram_type}/svg")
def export_diagram_svg(model_id: int, diagram_type: str, db: Session = Depends(get_db)):
    if not db.query(UMLModel).filter(UMLModel.model_id == model_id).first():
        raise HTTPException(status_code=404, detail="Model not found")
    if diagram_type not in {"uml", "erd"}:
        raise HTTPException(status_code=422, detail="Diagram type must be 'uml' or 'erd'.")
    diagram = generate_diagram_svg(db, model_id, diagram_type)
    if not diagram:
        raise HTTPException(status_code=400, detail=f"Could not generate the {diagram_type.upper()} diagram for this model.")
    return Response(
        content=diagram,
        media_type="image/svg+xml",
        headers={"Content-Disposition": f'attachment; filename="{diagram_type.upper()}_Model_{model_id}.svg"'},
    )


@app.get("/models/{model_id}/openapi")
def export_openapi_contract(model_id: int, db: Session = Depends(get_db)):
    """
    Phase 2 (Tier 2): Generates the OpenAPI 3.0 YAML Contract for the extracted models.
    """
    # Verify the model exists
    db_model = db.query(UMLModel).filter(UMLModel.model_id == model_id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found!")
    
    yaml_string = generate_openapi_yaml(db, model_id)
    
    if not yaml_string:
        raise HTTPException(status_code=400, detail="Could not generate OpenAPI spec.")
    
    # We return it as a raw text response so the browser/frontend can save it as a .yaml file easily
    return Response(content=yaml_string, media_type="text/yaml")


app = CORSMiddleware(
    app=app,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:4200").split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)