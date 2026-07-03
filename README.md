# School Library Recommendation and Story-Based Learning Bot

This project is a Streamlit MVP that helps schools upload a library catalog, recommend real books to students, and generate simple story-based concept lessons from book abstracts.

## Features

- Admin upload flow for Excel-based library catalogs
- SQLite storage for cleaned and enriched catalog records
- Rule-based enrichment for length, reading level, genre, and subject tags
- Student recommendation flow based on grade, topic, type, length, and reading level
- Cleaner Streamlit UI with guided sidebar flow, recommendation cards, and lesson review sections
- Story-based lesson generation with optional OpenAI support
- Teacher review mode with lesson editing, saving, and export
- SQLite logging for recommendation sessions, selected books, lessons, and feedback
- Basic dashboard for uploads, sessions, popular books, and average rating
- Safe fallback lesson template when no API key is available
- Deployment-ready config for local runs, Streamlit Community Cloud, Render, and Railway

## Folder Structure

```text
library_recommendation_bot/
|
|-- app.py
|-- requirements.txt
|-- README.md
|-- .env.example
|-- Procfile
|-- runtime.txt
|
|-- data/
|   |-- sample_catalog.xlsx
|
|-- database/
|   |-- library.db
|
|-- src/
|   |-- ingest_catalog.py
|   |-- database.py
|   |-- recommender.py
|   |-- lesson_generator.py
|   |-- chatbot_logic.py
|   |-- utils.py
```

## Setup Steps

1. Create and activate a virtual environment if you want an isolated setup.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` if you want local environment variables.

Example `.env`:

```env
OPENAI_API_KEY=your_api_key_here
LIBRARY_DB_PATH=database/library.db
```

- `OPENAI_API_KEY` is optional. If it is missing, the app safely uses the fallback lesson generator.
- `LIBRARY_DB_PATH` is optional. If it is missing, the app safely uses `database/library.db`.

## How to Run

```bash
streamlit run app.py
```

The app uses `database/library.db` for storage and will create the database table automatically if needed.

If the database is empty, the app still starts safely and shows clear guidance to upload a catalog first.

## How to Upload Catalog

1. Open the app in Streamlit.
2. Go to `Admin: Upload Catalog`.
3. Upload an `.xlsx` catalog file.
4. Click `Import Catalog`.
5. Review the import count and preview table.

Supported columns include:

- `Accession No`
- `Call No`
- `Location`
- `Item Type`
- `ISBN`
- `Publisher`
- `Pages`
- `Place`
- `Author`
- `Title`
- `Abstract`
- `GenNote`

If any columns are missing, the app keeps running and stores blank values instead.

## How Recommendation Works

The recommendation engine uses simple rule-based scoring:

- Normalized text matching across title, abstract, item type, genre tags, and subject tags
- Multiple topic keywords from the student, including comma-separated interests
- Weighted scoring where topic relevance matters most
- Medium-weight boosts for story/knowledge preference and length match
- Low-weight boosts for abstract availability and metadata completeness

The app returns 3 to 5 recommendations, a score breakdown for each book, and a clearer explanation of exactly why each book matched.

## Evaluation And Logging

The app also stores lightweight evaluation data in SQLite:

- `recommendation_sessions`
- `selected_books`
- `generated_lessons`
- `feedback`

It logs student grade, preferences, recommended books, selected books, chosen subject, chosen concept, generated lesson text, and simple feedback responses.

## Deployment

### Streamlit Community Cloud

1. Push this project to GitHub.
2. In Streamlit Community Cloud, create a new app from the repo.
3. Set the main file path to `app.py`.
4. Add optional secrets if needed:

```toml
OPENAI_API_KEY="your_api_key_here"
LIBRARY_DB_PATH="database/library.db"
```

Notes:

- `OPENAI_API_KEY` is optional.
- SQLite works for simple demos, but Community Cloud storage is not meant for durable production persistence.

### Render

You can deploy this as a web service.

Suggested settings:

- Build command: `pip install -r requirements.txt`
- Start command: `streamlit run app.py --server.address=0.0.0.0 --server.port=$PORT`

Notes:

- A `Procfile` is included for platforms that support it.
- Set `OPENAI_API_KEY` only if you want AI lesson generation.
- Set `LIBRARY_DB_PATH` if you want the SQLite database stored in a custom mounted path.

### Railway

Suggested setup:

- Deploy from the GitHub repo
- Build command: `pip install -r requirements.txt`
- Start command: `streamlit run app.py --server.address=0.0.0.0 --server.port=$PORT`

Environment variables:

- `OPENAI_API_KEY` optional
- `LIBRARY_DB_PATH` optional

### Important deployment note

SQLite is fine for an MVP and demos, but on Render or Railway it may be ephemeral unless you attach persistent disk/storage and point `LIBRARY_DB_PATH` there.

## How Story-Based Lesson Generation Works

- The student selects a recommended book.
- The student chooses a subject and an optional concept.
- If no concept is entered, the app suggests one from the book metadata.
- Lessons are structured into story connection, concept explanation, step-by-step teaching, example, activity, practice questions, and answers.
- The app checks whether the chosen concept fits the title and abstract and warns when the link is weak.
- Grade level is used to keep the tone more age-appropriate for younger and older students.
- If `OPENAI_API_KEY` is set, the app uses OpenAI to generate the lesson.
- If no API key is available, the app uses a stronger rule-based fallback template.
- The app does not invent story details and warns when the connection between concept and abstract is weak.
- Teachers can review the generated lesson, edit the final text, save it to SQLite, and export it as a `.txt` file.

## Limitations

- Recommendations are rule-based, not machine-learned.
- Grade suitability is approximate.
- Tagging depends on keyword matching.
- The quality of story-based teaching depends on the quality of the book abstract.
- OpenAI generation requires a valid API key and internet access at runtime.
- SQLite persistence on hosted platforms depends on the storage provided by that platform.

## Future Improvements

- Better ranking and personalization over time
- Teacher accounts and lesson approval workflow
- Student history and saved reading journeys
- Borrowing and availability tracking
- Stronger curriculum mapping by grade and subject
