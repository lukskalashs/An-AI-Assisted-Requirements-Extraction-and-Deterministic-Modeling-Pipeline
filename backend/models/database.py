import os

from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace(
        "postgres://", "postgresql+psycopg://", 1
    )
elif SQLALCHEMY_DATABASE_URL.startswith("postgresql://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )

engine_options = {}
if SQLALCHEMY_DATABASE_URL.startswith("sqlite:"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(SQLALCHEMY_DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
session_local = SessionLocal
Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")

class Project(Base):
    __tablename__ = "projects"

    project_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    project_name = Column(String, index=True)
    description = Column(Text)
    status = Column(String, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="projects")
    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")
    models = relationship("UMLModel", back_populates="project", cascade="all, delete-orphan")

class Document(Base):
    __tablename__ = "documents"

    document_id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.project_id"))
    file_name = Column(String)
    file_type = Column(String)
    raw_text = Column(Text)
    chunk_count = Column(Integer, default=0)
    processing_status = Column(String, default="uploaded")
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", back_populates="documents")
    requirements = relationship("ExtractedRequirements", back_populates="document", cascade="all, delete-orphan")
    extracted_model = relationship("UMLModel", back_populates="document", uselist=False, cascade="all, delete-orphan")

class UMLModel(Base):
    __tablename__ = "uml_models"

    model_id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.project_id"))
    document_id = Column(Integer, ForeignKey("documents.document_id"))
    status = Column(String, default="pending_review")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    document = relationship("Document", back_populates="extracted_model")

    project = relationship("Project", back_populates="models")
    classes = relationship("UMLClass", back_populates="model", cascade="all, delete-orphan")
    relationships = relationship("UMLRelationship", back_populates="model", cascade="all, delete-orphan")
    generated_diagram = relationship("GeneratedDiagram", back_populates="model", uselist=False, cascade="all, delete-orphan")

class UMLClass(Base):
    __tablename__ = "uml_classes"

    class_id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("uml_models.model_id"))
    class_name = Column(String)
    is_abstract = Column(Boolean, default=False)
    is_validated = Column(Boolean, default=False)
    entity_kind = Column(String, default="persistent_entity")
    source_evidence = Column(Text, nullable=True)

    model = relationship("UMLModel", back_populates="classes")
    attributes = relationship("UMLAttribute", back_populates="uml_class", cascade="all, delete-orphan")
    methods = relationship("UMLMethod", back_populates="uml_class", cascade="all, delete-orphan")

class ExtractedRequirements(Base):
    __tablename__ = "extracted_requirements"

    requirement_id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.document_id"))
    requirement_type = Column(String)
    quality_attribute = Column(String, nullable=True)
    description = Column(Text)
    is_validated = Column(Boolean, default=False)

    document = relationship("Document", back_populates="requirements")

class UMLAttribute(Base):
    __tablename__ = "uml_attributes"

    attribute_id = Column(Integer, primary_key=True, index=True)
    class_id = Column(Integer, ForeignKey("uml_classes.class_id"))
    attribute_name = Column(String)
    data_type = Column(String)
    visibility = Column(String, default="public")
    source_evidence = Column(Text, nullable=True)

    uml_class = relationship("UMLClass", back_populates="attributes")

class UMLMethod(Base):
    __tablename__ = "uml_methods"

    method_id = Column(Integer, primary_key=True, index=True)
    class_id = Column(Integer, ForeignKey("uml_classes.class_id"))
    method_name = Column(String)
    return_type = Column(String)
    visibility = Column(String, default="public")
    source_evidence = Column(Text, nullable=True)

    uml_class = relationship("UMLClass", back_populates="methods")


class UMLRelationship(Base):
    __tablename__ = "uml_relationships"

    relationship_id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("uml_models.model_id"))
    source_class_id = Column(Integer, ForeignKey("uml_classes.class_id"))
    target_class_id = Column(Integer, ForeignKey("uml_classes.class_id"))
    relationship_type = Column(String)
    relationship_label = Column(String, nullable=True)

    multiplicity_source = Column(String, nullable=True)
    multiplicity_target = Column(String, nullable=True)
    source_evidence = Column(Text, nullable=True)

    model = relationship("UMLModel", back_populates="relationships")

    source_class = relationship("UMLClass", foreign_keys=[source_class_id])
    target_class = relationship("UMLClass", foreign_keys=[target_class_id])

class GeneratedDiagram(Base):
    __tablename__ = "generated_diagrams"

    diagram_id = Column(Integer, primary_key=True, index=True)
    model_id = Column(Integer, ForeignKey("uml_models.model_id"))
    plantuml_syntax = Column(String)
    export_format = Column(String)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Link back to the model
    model = relationship("UMLModel", back_populates="generated_diagram")
    