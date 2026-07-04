# School Library Recommendation and Story-Based Learning Bot

This project is a Streamlit app that helps schools upload a library catalog, recommend real books to students, and generate simple story-based concept lessons from book abstracts.

## Features

- Login, signup, logout, and role-based access control
- Roles for `student`, `teacher`, and `admin`
- Admin user-management page for creating staff accounts and managing roles
- Admin upload flow for Excel-based library catalogs
- PostgreSQL-ready storage for production, with SQLite fallback for local development
- Rule-based enrichment for length, reading level, genre, and subject tags
- Student recommendation flow based on grade, topic, type, length, and reading level
- Cleaner Streamlit UI with guided sidebar flow, recommendation cards, and lesson review sections
- Story-based lesson generation with optional OpenAI support
- Teacher review mode with lesson editing, saving, and export
- Database logging for recommendation sessions, selected books, lessons, and feedback
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
DATABASE_URL=
LIBRARY_DB_PATH=database/library.db
FIRST_ADMIN_NAME=
FIRST_ADMIN_EMAIL=
FIRST_ADMIN_PASSWORD=
```

- `OPENAI_API_KEY` is optional. If it is missing, the app safely uses the fallback lesson generator.
- `DATABASE_URL` is optional for local development, but it should be set in production.
- `LIBRARY_DB_PATH` is only used for local SQLite fallback when `DATABASE_URL` is not set.
- `FIRST_ADMIN_*` is optional, but it is the easiest way to create the first admin account.

## How to Run

```bash
streamlit run app.py
```

If `DATABASE_URL` is set, the app uses PostgreSQL. If it is not set, the app falls back to a local SQLite database and creates the tables automatically if needed.

If the database is empty, the app still starts safely and shows clear guidance to upload a catalog first.

## Authentication And Roles

- The first screen is now authentication, not role switching.
- `Sign Up` creates a `student` account.
- `Login` works for `student`, `teacher`, and `admin` accounts.
- The sidebar only shows pages that match the logged-in user's role.
- Route access is checked in code as well, so changing `session_state` alone is not enough to unlock another role.

### Role access

- `student`: Student Dashboard, Find Books, Story-Based Learning
- `teacher`: Teacher Dashboard, Teacher Review
- `admin`: Admin Dashboard, Admin User Management, Admin Upload Catalog

## First Admin Account Setup

Set these environment variables before starting the app:

```env
FIRST_ADMIN_NAME=School Admin
FIRST_ADMIN_EMAIL=admin@example.com
FIRST_ADMIN_PASSWORD=StrongPass1
```

On startup, the app will create or refresh that admin account securely.

After logging in as admin, open `Admin: User Management` to:

- create teacher accounts from the UI
- create another admin if needed
- promote a student to teacher
- change teacher back to student
- deactivate or reactivate accounts

Inactive users cannot log in.

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

The app also stores lightweight evaluation data in the database:

- `recommendation_sessions`
- `selected_books`
- `generated_lessons`
- `user_feedback`

It also uses these auth and user tables:

- `users`
- `student_profiles`
- `saved_books`
- `reading_history`

It logs student grade, preferences, recommended books, selected books, chosen subject, chosen concept, generated lesson text, and simple feedback responses.

## Deployment

### Streamlit Community Cloud

1. Push this project to GitHub.
2. In Streamlit Community Cloud, create a new app from the repo.
3. Set the main file path to `app.py`.
4. Add optional secrets if needed:

```toml
OPENAI_API_KEY="your_api_key_here"
DATABASE_URL="postgresql://..."
```

Notes:

- `OPENAI_API_KEY` is optional.
- Streamlit Community Cloud should use `DATABASE_URL` if you want durable production-style persistence.

### Render

You can deploy this as a web service.

Suggested settings:

- Build command: `pip install -r requirements.txt`
- Start command: `streamlit run app.py --server.address=0.0.0.0 --server.port=$PORT`

Notes:

- A `Procfile` is included for platforms that support it.
- Set `DATABASE_URL` to your Render PostgreSQL connection string.
- Set `OPENAI_API_KEY` only if you want AI lesson generation.
- `LIBRARY_DB_PATH` is not needed on Render when PostgreSQL is used.

### Railway

Suggested setup:

- Deploy from the GitHub repo
- Build command: `pip install -r requirements.txt`
- Start command: `streamlit run app.py --server.address=0.0.0.0 --server.port=$PORT`

Environment variables:

- `DATABASE_URL` for PostgreSQL
- `OPENAI_API_KEY` optional
- `LIBRARY_DB_PATH` optional for local SQLite fallback only

### Important deployment note

For Render production, use PostgreSQL through `DATABASE_URL`. SQLite remains useful for local development and quick demos when `DATABASE_URL` is not present.

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
- Teachers can review the generated lesson, edit the final text, save it to the database, and export it as a `.txt` file.

## Limitations

- Recommendations are rule-based, not machine-learned.
- Grade suitability is approximate.
- Tagging depends on keyword matching.
- The quality of story-based teaching depends on the quality of the book abstract.
- OpenAI generation requires a valid API key and internet access at runtime.
- If you stay on SQLite locally, the database file persistence depends on the local path you choose.

## Future Improvements

- Better ranking and personalization over time
- Teacher accounts and lesson approval workflow
- Student history and saved reading journeys
- Borrowing and availability tracking
- Stronger curriculum mapping by grade and subject
