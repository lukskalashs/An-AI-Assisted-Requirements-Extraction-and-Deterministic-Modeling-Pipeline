# AI-Assisted Requirements Extraction and Deterministic Modeling Pipeline

**Author:** Lukhanyo Floris Kalashe (2023575000)
**Project:** CSIS6809 Honours Project
**Supervisor:** Mr W.S.J Marais

## Mid-Year Demo 1 Update
The core backend architecture for this Model-Driven Architecture (MDA) pipeline is now fully operational. The system successfully bridges the gap between unconstrained natural language and deterministic software modeling.

### Proof of Execution
To review the results of the pipeline without needing to execute the API locally, please view the `/Demo_1_Outputs` directory which contains the raw input and intermediate files:
* **Input Document:** `Annex-A-Detailed-Software-Requirements-Specification-SRS.pdf`
* **Compiled Rule Engine Text:** `generated_model.puml`

Below is the visual proof of the system's successful end-to-end execution.

#### 1. RESTful API Documentation (Swagger UI)
This FastAPI backend exposes a fully documented, interactive API. The endpoints manage the entire lifecycle from document ingestion to extraction and diagram generation.
![Swagger API Endpoints](Demo_1_Outputs/Swagger_API_Endpoints.png)

#### 2. Database to PlantUML Compilation
This image demonstrates the FastAPI pipeline successfully fetching the nested entities from the SQLite database and deterministically compiling them into syntactically perfect PlantUML text.
![Database PlantUML Output Text](Demo_1_Outputs/Database_plantuml_output_text.png)

#### 3. Final Rendered Domain Model
This image shows the final rendered diagram generated directly from the pipeline's output. It proves the backend rule engine accurately handled and mapped access modifiers, complex data types, and structural relationship multiplicities.
I copied the producted PlantUML syntax and pasted on "https://www.planttext.com/" to produce this. This won't be needed in the next demos as i would have implemented it within my system for rendering the produced Diagram
![Generated Diagram From Text](Demo_1_Outputs/Generated_Diagram_from_Text.png)

---

## System Architecture & Workflow
This FastAPI backend executes the following multi-stage pipeline:

1. **Document Ingestion:** Securely uploads PDFs/TXTs and sanitizes broken Unicode characters.
2. **Intelligent Chunking (`spaCy`):** Slices text using a sliding-window overlap to preserve context without exceeding LLM token limits.
3. **Semantic Extraction (LLM):** Uses an AI API to read chunks and strictly format the output into a deterministic JSON metamodel via Pydantic validation.
4. **Relational Persistence:** Maps the AI's output into a highly structured SQLite database (using fuzzy-matching for relationships to prevent string-mismatch orphans).
5. **Rule Engine:** Deterministically compiles the database records into syntactically perfect PlantUML code.

For the AI-Driven Job Matching Platform SRS, extraction preserves the canonical domain entities
`JobSeeker`, `Employer`, `JobPosting`, `Admin`, `Notification`, `IntegrationPartner`,
`Reporting`, and `AIEngine`. The ERD compiler renders one-to-many foreign keys on the
dependent entity and expands many-to-many relationships into explicit junction entities.

---

## Local Setup Instructions (Optional)
If you wish to run the FastAPI server and test the Swagger UI locally:

1. **Install Dependencies:**
   ```bash
   cd backend
   pip install -r requirements.txt
   python -m spacy download en_core_web_sm
   uvicorn main:app --reload
   ```

## Hosting

The frontend and FastAPI API are hosted on Render. The Angular frontend is
deployed as a Render Static Site; GitHub Pages is not used.

### Backend (Render)

1. Push this repository to GitHub, then create a Render Blueprint from the
   repository. Render reads [render.yaml](./render.yaml), which installs the
   dependencies in `backend/requirements.txt`, downloads the spaCy English
   model, and starts Uvicorn on Render's assigned port.
2. Set `OPENAI_API_KEY` in the Render service environment. The extraction
   feature calls OpenAI and requires a valid API key; API usage may incur
   charges.
3. Set `DATABASE_URL` to a PostgreSQL connection URL for persistent storage.
   The app still defaults to local SQLite for development, but Render's free
   web-service filesystem is ephemeral, so local SQLite data can be lost when
   the service restarts or redeploys.

### Frontend (Render Static Site)

Configure the Render Static Site with root directory `frontend`, build command
`npm ci && npm run build -- --base-href /`, and publish directory
`dist/frontend/browser`. Set its `API_BASE_URL` build-time variable to the
public HTTPS URL of the deployed Render API (for example,
`https://ai-assisted-uml-api.onrender.com`).

The backend's `CORS_ORIGINS` in `render.yaml` must match the frontend's public
origin (scheme and host, without a path or trailing slash). A push to the
tracked branch triggers Render to deploy updated services.
