# Local build: Aria hotel booking assistant

This guide covers the local build. It runs the hotel booking assistant "Aria" on your own machine, offline, using:

- **Ollama** (`qwen2.5`) as the model, with a tool-calling loop in place of an Amazon Bedrock Agent.
- **SQLite** (Python standard library `sqlite3`) in place of DynamoDB, for room inventory and bookings.
- **Keyword retrieval** over the hotel documents in `knowledge-base/` in place of a Bedrock Knowledge Base.

The local build needs **no AWS account, no AWS credentials, and no file in the `aws/` folder**. The only folders it shares with the AWS build are `agent/` and `knowledge-base/`. For the project overview, see the [root README](../README.md).

## Where commands run

Run every command in this guide from the **repository root**: the folder that contains `local/`, `agent/`, and `knowledge-base/`. The code is a Python package rooted at `local/` and uses package-relative imports. No command needs an absolute path.

## Prerequisites

- **Python 3.10 or newer.** The `local/` code uses no syntax newer than Python 3.8, but the current releases of `fastapi` and `uvicorn` require Python 3.10, so 3.10 is the minimum for a fresh install. The build was tested with **Python 3.14**.
- **Ollama**, installed and running. The server listens at `http://localhost:11434`.
- The **`qwen2.5` model**, pulled once:

  ```bash cwd=root
  ollama pull qwen2.5
  ```

- Check that the model is available. The output of this command must include `qwen2.5` before you start the terminal chat or the web UI:

  ```bash cwd=root
  ollama list
  ```

`sqlite3` ships with Python, so there is nothing to install for the database.

## Install dependencies

A virtual environment is optional but keeps the packages separate from your system Python.

Windows PowerShell:

```powershell cwd=root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash cwd=root
python3 -m venv .venv
source .venv/bin/activate
```

Then install the dependencies (`ollama`, `fastapi`, `uvicorn`):

```bash cwd=root
python -m pip install -r local/requirements.txt
```

## Seed or reset the database

```bash cwd=root
python local/chat.py --reset-db
```

`--reset-db` drops and recreates the `inventory` and `bookings` tables and reseeds the 12 inventory rows defined in `local/db.py` (2026-12-20 to 2026-12-31). Without the flag, `local/chat.py` seeds only when the inventory table is empty. The database file `local/hotel.db` is generated at runtime and is excluded from git.

## Run the terminal chat

```bash cwd=root
python local/chat.py
```

Type messages at the `you>` prompt. `exit`, `quit`, end-of-input, or Ctrl-C ends the session.

## Run the web UI

```bash cwd=root
python local/web.py
```

The web UI is served at `http://127.0.0.1:8000`. Stop it with Ctrl-C. As an alternative, start it with uvicorn directly:

```bash cwd=root
python -m uvicorn local.web:app --reload
```

### Look and feel

The page shows a full-screen photo of a sea-view resort pool with a dark gradient overlay and a frosted-glass chat card on top. The card has an Aria header, separate guest and assistant message bubbles with timestamps, an "Aria is thinking…" indicator while a reply is pending (the Send button and suggestion chips are disabled meanwhile), Enter-to-send, an inline error bubble if the request fails, and clickable suggestion chips. Assistant replies are rendered as plain text, so no HTML from the model is interpreted; `**bold**` is shown in bold and line breaks are kept. The layout is a centred card up to 760px wide on desktop and fills the width on phones. It uses plain HTML, CSS, and JavaScript with the system font stack, so it works offline.

### Static assets and photo credit

Background images live in `local/static/` and are served by FastAPI `StaticFiles` at `/static`. The directory is resolved relative to `local/web.py`, so the working directory does not matter.

- `hotel-bg-1920.webp` and `hotel-bg-1920.jpg`: desktop and tablet (768px wide and up).
- `hotel-bg-900.webp` and `hotel-bg-900.jpg`: portrait crop for phones.

The CSS uses `image-set()` to pick WebP with a JPEG fallback, and a media query to pick the size. To use a different photo, replace these four files and keep the names.

Photo credit: "Lounge Chairs Around Infinity Pool" by Pixabay on Pexels (<https://www.pexels.com/photo/lounge-chairs-around-infinity-pool-261181/>), used under the [Pexels license](https://www.pexels.com/license/) (free to use, attribution not required).

## Shared files the local build reads

The local build reads these files from the repository root. In the code they are addressed as `../agent/` and `../knowledge-base/`, relative to the `local/` folder:

| File | Used for |
|---|---|
| `agent/agent-instructions.txt` | Aria's system prompt, read verbatim when the agent starts. |
| `agent/action-group-schema.json` | Source of the tool definitions (`checkAvailability`, `bookRoom`, `updateInventory`). The Python tool definitions mirror it. |
| `knowledge-base/faq.md` | Hotel FAQ, searched by the `searchKnowledgeBase` tool. |
| `knowledge-base/hotel-policies.md` | Hotel policies, searched by the same tool. |
| `knowledge-base/amenities-and-dining.md` | Amenities and dining, searched by the same tool. |

## Run the offline unit tests

```bash cwd=root
python -m unittest discover -s local/tests -v
```

The tests need no Ollama server and no network access. They include a threaded proof that concurrent bookings cannot overbook a room.

## Test scenarios

These seven scenarios use a freshly seeded database. Drive them in the terminal chat (`python local/chat.py`) or the web UI, with Ollama running (`ollama list` shows `qwen2.5`). Counts are Sea View / Garden View.

**Re-seed before each full run.** Scenario 6 books the last Sea View room for 2026-12-29, and scenarios 3 and 6 reduce counts. The following command restores all 12 seed rows. Run it, then restart the chat or web UI process:

```bash cwd=root
python local/chat.py --reset-db
```

To check counts and booking records directly, stop the chat first and run this from the repository root. It prints every inventory row and every booking record:

```bash cwd=root
python -c "import sqlite3; c = sqlite3.connect('local/hotel.db'); print(c.execute('SELECT * FROM inventory ORDER BY date').fetchall()); print(c.execute('SELECT * FROM bookings').fetchall())"
```

| # | Prompt | Tool operation called | Booking ID / booking record | Counts before to after |
|---|---|---|---|---|
| 1 | "What time is check-out?" | No booking tool. The answer comes from the knowledge-base files: 11:00 AM. | No ID, no record | No inventory change |
| 2 | "How many rooms are available on 2026-12-22?" | `checkAvailability` | No ID, no record | 2026-12-22: 10 / 8 to 10 / 8 |
| 3 | "Book a Sea View room for 2026-12-22 for Jane Doe, jane@example.com" | `bookRoom` | ID returned, one new record | 2026-12-22: Sea View 10 to 9, Garden View 8 to 8 |
| 4 | "Book a Sea View room for 2026-12-25 for John Smith" | `bookRoom` (refused) | No ID, no record | 2026-12-25: Sea View 0 to 0, Garden View 2 to 2 |
| 5 | "I'd like to book a room for 2026-12-27" | None before the assistant asks for a missing detail | No ID, no record | 2026-12-27: 10 / 4 to 10 / 4 |
| 6 | "Book a Sea View room for 2026-12-29 for Priya Patel" | `bookRoom` | First request: ID returned, exactly one record. Second identical request: refused, no ID, no second record | 2026-12-29: Sea View 1 to 0 after the first request and 0 after the second. Garden View 0 to 0 |
| 7 | "Book a Sea View room for 2026-12-31 for Sam Lee", then "Book a Garden View room for 2026-12-31 for Sam Lee" | `bookRoom` (both refused) | No ID, no record | 2026-12-31: 0 / 0 to 0 / 0 |

What to check for each scenario:

1. Aria answers 11:00 AM from the knowledge-base files. No booking tool is called, and no count changes.
2. Aria reports 10 Sea View and 8 Garden View rooms.
3. Aria returns a booking ID with status `confirmed`. The `bookings` table gains one record, and the 2026-12-22 Sea View count drops from 10 to 9. Aria may ask a brief confirmation question first. If it does, reply "go ahead and confirm it now". After this scenario the count is 9, so re-seed before comparing against scenario 2.
4. Aria politely refuses and says no Sea View rooms are available. The `bookings` table gains no record. The Sea View count stays 0 and the Garden View count stays 2.
5. Aria asks for at least one missing detail, such as the room type or the guest name, before booking. Nothing is booked, and the 2026-12-27 counts stay 10 Sea View and 4 Garden View.
6. The first request returns a booking ID and creates exactly one record, and the Sea View count goes from 1 to 0 (Garden View stays 0). **This scenario books the last Sea View room for 2026-12-29.** A second identical request is refused, returns no booking ID, creates no second record, and leaves the Sea View count at 0. Re-seed before you repeat it.
7. Both requests are refused. No booking record is created, and both counts stay 0.

`bookRoom` is atomic and overbooking-safe: a room is taken only when one is truly available.

## Troubleshooting

| Symptom | Cause | Resolution |
|---|---|---|
| The chat or web UI fails with a connection error to `localhost:11434` (connection refused). | The Ollama server is not running. | Start Ollama (launch the desktop app, or run `ollama serve` in a separate terminal), then run `ollama list` to confirm it responds. |
| An error such as `model 'qwen2.5' not found`, or `ollama list` does not show `qwen2.5`. | The model was never pulled. | Run `ollama pull qwen2.5`, then `ollama list` and check that `qwen2.5` appears. |
| The web UI fails to start with an error such as "address already in use" on port 8000. | Another process is using port 8000. | Stop the other process, or serve on another port from the repository root: `python -m uvicorn local.web:app --port 8001`, then open `http://127.0.0.1:8001`. |
| `ModuleNotFoundError: No module named 'local'`, or a missing `agent-instructions.txt` or `knowledge-base` file error. | The command was run from a folder other than the repository root. | Change to the folder that contains `local/`, `agent/`, and `knowledge-base/`, then run the command again. |

## Architecture notes

- `local/db.py`: SQLite schema, connection factory, and the 12-row seed.
- `local/booking_core.py`: the three business operations ported from `aws/src/booking_handler/app.py`, with the same return shapes and an atomic, overbooking-safe `bookRoom`. A single SQLite `UPDATE` decrements the room count only where the count is at least 1, inside an immediate transaction. The booking record is inserted in the same transaction, and the transaction rolls back when no row is updated.
- `local/knowledge.py`: keyword retrieval over the markdown files in `knowledge-base/`.
- `local/agent.py`: the Ollama tool-calling loop. Aria's system prompt is read from `agent/agent-instructions.txt` when the agent is constructed. The tools are `checkAvailability`, `bookRoom`, `updateInventory`, plus `searchKnowledgeBase`. No Ollama call is made at import time. A light-parse fallback handles models that emit a tool call as JSON text instead of structured `tool_calls`.
- `local/chat.py`: terminal chat.
- `local/web.py`: FastAPI single-page chat UI. `local/static/` holds its background images.
