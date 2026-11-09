"""
Terminal REPL for the local Aria booking assistant.

Usage (from the workspace root):
    python local/chat.py             # seed only if inventory is empty, then chat
    python local/chat.py --reset-db  # force a fresh reseed, then chat

Requires the Ollama server running with the qwen2.5 model available.
"""

import sys

if __package__ in (None, ""):
    # Allow `python local/chat.py` by making the workspace root importable and
    # re-dispatching as the package module `local.chat`.
    import os
    import runpy

    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    runpy.run_module("local.chat", run_name="__main__", alter_sys=True)
    raise SystemExit(0)

from . import db
from .agent import Agent


def _inventory_is_empty():
    conn = db.connect()
    try:
        row = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()
        return (row[0] if row else 0) == 0
    finally:
        conn.close()


def _prepare_db(reset):
    if reset:
        db.init(reset=True)
        db.seed()
        print("Database reset and reseeded with the 12 canonical inventory rows.")
        return
    db.init()
    if _inventory_is_empty():
        db.seed()
        print("Database seeded with the 12 canonical inventory rows.")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    reset = "--reset-db" in argv

    _prepare_db(reset)

    print("Aria — local hotel booking assistant.")
    print("Ensure the Ollama server is running (qwen2.5). Type 'exit' or 'quit' to leave.")

    agent = Agent()
    while True:
        try:
            user_text = input("\nyou> ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if user_text.strip().lower() in {"exit", "quit"}:
            print("Goodbye.")
            break
        if not user_text.strip():
            continue

        reply = agent.send(user_text)
        print(f"\nAria> {reply}")


if __name__ == "__main__":
    main()
