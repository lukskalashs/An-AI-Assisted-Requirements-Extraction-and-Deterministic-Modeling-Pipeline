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
from models.database import UMLModel, UMLClass, UMLAttribute, UMLRelationship, UMLMethod
from services.uml_generator import generate_plantuml_syntax


# Create the database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AI-Assisted UML Extraction API",
    description="Backend for processing Software Requirements Specification (SRS) documents and generating UML diagrams",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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
    text_chunks = chunk_text(raw_text)
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

    return new_document

@app.post("/documents/{document_id}/extract")
def extract_uml_entities_from_document(document_id: int, db: Session = Depends(get_db)):
    """
    Trigger the NLP and LLM pipeline to extract UML entities from a saved document.
    Also make the persistebr in our db
    """

    # 1stly fetch the document from the database
    document = db.query(Document).filter(Document.document_id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if not document.raw_text:
        raise HTTPException(status_code=400, detail="Document has no raw text to process.")
    
    # 2ndly chunk the text(using the sliding window approach
    chunks = chunk_text(document.raw_text)

    # Send to the LLM pipeline to extract UML entities
    extracted_json = extracted_uml_entities_from_chunks(chunks)

    # Mapping, Primary UMLModel container

    new_model = UMLModel(
        project_id = document.project_id,
        document_id = document.document_id,
        status = "pending review"
    )
    db.add(new_model)
    db.flush()

    #Populate database with Extracted Classes, Attr and Methods

    class_name_map = {}

    for cls_data in extracted_json.get("classes", []):
        db_class = UMLClass(
            model_id = new_model.model_id,
            class_name=cls_data.get("class_name"),
            is_abstract=cls_data.get("is_abstract", False),
            is_validated=False

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
                visibility=attr.get("visibility", "public")

            )
            db.add(db_attribute)

        #Insert Methods
        for method in cls_data.get("methods", []):
            db_method = UMLMethod(
                class_id = db_class.class_id,
                method_name = method.get("name"),
                return_type = method.get("return_type", "void"),
                visibility=method.get("visibility", "public")
            )
            db.add(db_method)
    
    # Populate The relationship extracted
    relationships_saved = 0
    for relationship_data in extracted_json.get("relationships", []):
        src_name = relationship_data.get("source_class", "").strip().lower()
        tgt_name = relationship_data.get("target_class", "").strip().lower()

        src_id = class_name_map.get(src_name)
        tgt_id = class_name_map.get(tgt_name)

        if src_id and tgt_id:
            db_relationship = UMLRelationship(
                model_id=new_model.model_id,
                source_class_id = src_id,
                target_class_id = tgt_id,
                relationship_type=relationship_data.get("relationship_type", "Association"),
                multiplicity_source=relationship_data.get("multiplicity_source"),
                multiplicity_target=relationship_data.get("multiplicity_target")
            )
            db.add(db_relationship)
            relationships_saved +=1
        else:
            print(f"Warning: Dropped relationship between '{src_name}' and '{tgt_name}' due to class mismatch.")
    
    document.processing_status = "extracted"
    db.commit()

    return {
        "message": "UML Metamodel extraction successfully processed and committed to relational tables.",
        "model_id": new_model.model_id,
        "document_id": document.document_id,
        "classes_extracted_count": len(class_name_map),
        "relationships_extracted_count": relationships_saved
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

# Human - In - The - Loop - endpoints

@app.get("/Models/{model_id}", response_model=schemas.UMLModelResponse)
def get_uml_model(model_id: int, db:Session = Depends(get_db)):
    """
    We Fetch The completed extracted UML model (tbhis includes nested class, atttributes,
    Methods, relationships) the populaytes the Front end<<Angular>> human in the loop Dashboard)
    """
    #Via Pytdantics and sqlAcl <Fetches and formats all the nested tables to the model
    db_model = db.query(UMLModel).filter(UMLModel.model_id == model_id).first()

    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    

    return db_model
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
    db_rel.multiplicity_source = rel_update.multiplicity_source
    db_rel.multiplicity_target = rel_update.multiplicity_target

    db.commit()
    db.refresh(db_rel)
    return db_rel

@app.put("/classes/{class_id", response_model=schemas.ClassResponse)
def update_uml_class(class_id:int, class_update: schemas.ClassBase, db: Session = Depends(get_db)):
    """
    Update a specific class (eg. Change name, Mark it as abstract all of that during The HITL review Process)
    """

    db_class = db.query(UMLClass).filter(UMLClass.class_id == class_id).firist()

    if not db_class:
        raise HTTPException(status_code=404, detail="Class Not Found")
    
    #Update The databse with fileds that the user input after checking what the Model looks like and feels the need o uopdate what the ai ouputedd

    db_class.class_name = class_update.class_name
    db_class.is_abstract = class_update.is_abstract
    db_class.is_validated = class_update.is_validated

    db.commit()
    db.refresh(db_class)
    return db_class




if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)