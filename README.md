# Audit Time Management

Internal web app for recording login/logout times, mission selection, and task
progress against Excel-imported mission schedules.

**Stack:** FastAPI (backend) + vanilla HTML/CSS/JS (frontend) + SQLite.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Put the two Excel files in data/
#   data/Yves_TemplateEmployee.xls
#   data/Yves_TemplateMission.xls.xlsx

cp .env.example .env
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Open http://127.0.0.1:8000

Test accounts (password = login code, case-insensitive):

| Username | Password | Person |
|---|---|---|
| LEE | lee | Lena Elias El Feghaly |
| AKA | aka | Anthony Khorkhe Assal |
| MCE | mce | Mariana Charbel El Hajj |
| MIN | min | Marc  Issam Nawfal Jardak |
| TAD | tad | Toufic Antoine Daoud (placeholder) |
| AGN | agn | Alfred Ghantous Nehme (no missions) |

## Regenerate the database

Delete `db/audit.db` or run:

```bash
python scripts/reset_db.py
```

## API docs

While the server is running, browse http://127.0.0.1:8000/docs for the
auto-generated OpenAPI reference.

## Deployment

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 2
```

For production, put nginx (or Caddy) in front for TLS.