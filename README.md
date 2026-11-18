# Spec -> Code

Turn software requirements documents into reviewable, source-linked software models.

**Try the live application:** [an-ai-assisted-requirements-extraction.onrender.com](https://an-ai-assisted-requirements-extraction.onrender.com/)

Spec -> Code is a full-stack application that helps bridge the gap between a written specification and an implementation-ready design. Upload a PDF or TXT requirements document, review the AI-extracted domain model against its original source passages, then generate diagrams and starter code from the approved model.

## Why it is useful

Requirements are often written in natural language, while implementation depends on precise entities, fields, behaviors, and relationships. This project makes that translation visible and reviewable:

- **Move from prose to structure:** Extract candidate classes, attributes, methods, and relationships from one or more specification documents.
- **Keep the model grounded in its source:** Open the passage behind an extracted item and check it in context before accepting the design.
- **Keep people in the loop:** Edit, add, or remove model elements before generating artifacts; AI output is a starting point for review, not a substitute for it.
- **Generate consistent deliverables:** Build UML class and 3NF ER diagrams, export editable draw.io diagrams, and download C# classes.
- **Separate interpretation from generation:** AI assists with interpreting requirements; deterministic generators create artifacts from the reviewed structured model.

## Demo guide

The fastest way to explore the project is with a small requirements document, such as a to-do list app specification:

1. Open the [live application](https://an-ai-assisted-requirements-extraction.onrender.com/).
2. Select one or more `.pdf` or `.txt` requirements files and choose **Upload & Extract Model**. The app creates a project from the uploaded file names and starts processing automatically.
3. On the **Requirements review** screen, explore the extracted classes, attributes, methods, and relationships. Select an item to see its supporting passage in the source document; edit the model where needed.
4. Confirm the reviewed model and generate its diagrams.
5. Explore the UML class diagram and 3NF ERD. Download them as SVG or PNG images, or as editable draw.io files. Download the generated C# classes as a ZIP containing one file per class.

For best results, use a text-based PDF or a clear TXT document with concrete domain concepts and relationships. Review extracted results carefully before generating artifacts.

## How it works

```text
PDF / TXT specifications
          |
          v
Text extraction and contextual chunking (spaCy)
          |
          v
LLM-assisted structured model extraction (OpenAI, Pydantic validation)
          |
          v
Relational persistence and human review
          |
          v
Deterministic UML / ERD / code / API-contract generation
```

Uploaded document text is extracted and divided into overlapping chunks to preserve context. The extraction service uses OpenAI to identify candidate domain concepts and return structured data, which is validated and stored in a relational model. The Angular interface links model elements to source evidence and supports review and editing. After review, backend generators produce UML and ERD diagrams, C# classes, and an OpenAPI YAML contract.

## Technology

| Area | Technologies |
| --- | --- |
| Frontend | Angular 21, TypeScript, RxJS, Tailwind CSS, daisyUI |
| API | Python, FastAPI, Pydantic |
| Requirements processing | spaCy, PyPDF2, OpenAI API (`gpt-4o-mini`) |
| Persistence | SQLAlchemy, SQLite for local development, PostgreSQL support |
| Generated artifacts | UML class diagrams, 3NF ERDs, SVG, PNG, draw.io XML, C# classes, OpenAPI YAML |
| Hosting | Render |

## Run locally

### Backend

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment, then install and start the API:

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
uvicorn main:app --reload
```

The API is available at `http://localhost:8000`; interactive API documentation is at `http://localhost:8000/docs`. Local development uses SQLite by default. Set `OPENAI_API_KEY` in the environment to enable extraction; the OpenAI API may incur usage charges. Set `DATABASE_URL` to use PostgreSQL instead.

### Frontend

In another terminal:

```bash
cd frontend
npm ci
npm start
```

Open the Angular development server URL shown in the terminal. The development frontend is configured to call the API at `http://localhost:8000`.


