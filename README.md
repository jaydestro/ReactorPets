# 🐾 ReactorPets

> **⚠️ Disclaimer:** This is strictly a demonstration application. This code has not been thoroughly reviewed — it was built live during a livestream using GitHub Copilot Chat for VS Code. It is not intended for production use.

A pet adoption web app built live during the **[Azure Decoded: Vibe Coding on Azure Cosmos DB — Build an AI App](https://www.youtube.com/watch?v=3NUBILXN70A)** Reactor session.

## What It Does

- Browse adoptable pets with images, breeds, locations, and listing dates
- Register / login (demo mode auto-creates accounts on login)
- Submit adoption applications with auto-filled profile info
- Track application status in real time via SSE (Submitted → Under Review → Home Check Scheduled → Approved)
- AI chatbot powered by Ollama answers questions about available pets and the adoption process using live Cosmos DB data

## Tech Stack

- **Python / Flask** — web framework
- **Azure Cosmos DB** (NoSQL) — database (local emulator for dev)
- **Ollama** (`qwen2.5:0.5b`) — local AI chatbot
- **Uvicorn** — WSGI server

## Cosmos DB Design

| Container | Partition Key | Access Pattern |
|-----------|--------------|----------------|
| `pets` | `/id` | Point reads by pet ID |
| `users` | `/id` | Point reads for session loading |
| `applications` | `/userId` | Single-partition "my applications" queries |

Best practices applied: singleton client, point reads over queries, embedded timelines, type discriminators, emulator SSL config.

## Setup

### Prerequisites

- Python 3.10+
- [Azure Cosmos DB Emulator](https://learn.microsoft.com/azure/cosmos-db/emulator) running on `https://localhost:8081`
- [Ollama](https://ollama.com) installed

### Install & Run

```bash
# Clone
git clone https://github.com/jaydestro/ReactorPets.git
cd ReactorPets

# Virtual environment
python -m venv .venv
.venv/Scripts/activate   # Windows
# source .venv/bin/activate  # macOS/Linux

# Dependencies
pip install -r requirements.txt

# Environment variables
cp .env.sample .env
# Edit .env with your Cosmos DB endpoint/key

# Pull the AI model
ollama pull qwen2.5:0.5b

# Run
.venv/Scripts/uvicorn app:app --port 5000 --interface wsgi
```

Open **http://localhost:5000**

## Project Structure

```
ReactorPets/
├── app.py              # Flask routes, auth, SSE, chat endpoint
├── cosmos_db.py        # Cosmos DB data layer (singleton client, CRUD)
├── requirements.txt
├── .env.sample         # Environment variable template
├── .gitignore
├── static/images/      # Placeholder SVGs per species
└── templates/          # Jinja2 templates (base, index, detail, apply, etc.)
```

## Resources

- [Azure Cosmos DB Vibe Coding Cheat Sheet](https://gist.github.com/jaydestro/29982ecce186b3e996787c83aee1c844)

## License

Demo app — use however you like.
