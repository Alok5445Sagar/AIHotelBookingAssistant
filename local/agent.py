"""
Ollama agent brain for the local offline companion.

Aria is the digital booking assistant. Her system prompt is read verbatim at
startup from ../agent/agent-instructions.txt. Tool definitions mirror the
operation names, parameters, and required fields in agent/action-group-schema.json
(checkAvailability, bookRoom, updateInventory) plus a searchKnowledgeBase tool for
general hotel questions.

The Agent runs a tool-calling loop against ollama.chat(model='qwen2.5', ...):
structured tool_calls are dispatched to booking_core / knowledge, their results are
appended as role:'tool' messages (JSON-encoded), and the loop continues until the
assistant returns a final message with no tool call. A light-parse fallback handles
qwen2.5 emitting a tool call as JSON text in the content instead of structured
tool_calls.

No Ollama call is made at import time.
"""

import json
import re
from pathlib import Path

import ollama

from . import booking_core, knowledge

MODEL = "qwen2.5"
MAX_ITERATIONS = 6

# Aria's system prompt, read verbatim from the cloud agent instructions.
_INSTRUCTIONS_PATH = Path(__file__).parent.parent / "agent" / "agent-instructions.txt"


def _load_system_prompt():
    """Read the Aria system prompt verbatim. Called at Agent construction time."""
    return _INSTRUCTIONS_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Tool definitions — mirror agent/action-group-schema.json plus searchKnowledgeBase
# --------------------------------------------------------------------------- #
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "checkAvailability",
            "description": (
                "Returns how many Sea View and Garden View rooms are available on a "
                "given date. Call this before confirming any booking."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "The date to check, in YYYY-MM-DD format.",
                    },
                    "roomType": {
                        "type": "string",
                        "enum": ["Sea View", "Garden View"],
                        "description": "Optional room type to filter on.",
                    },
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bookRoom",
            "description": (
                "Atomically reserves one room of the given type for the check-in date "
                "and creates a booking record. Fails safely if no room is available. "
                "Only call this once you have collected the check-in date, room type, "
                "and guest name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "checkInDate": {
                        "type": "string",
                        "description": "Check-in date in YYYY-MM-DD format.",
                    },
                    "roomType": {
                        "type": "string",
                        "enum": ["Sea View", "Garden View"],
                        "description": "The room type to book.",
                    },
                    "guestName": {
                        "type": "string",
                        "description": "Full name of the guest.",
                    },
                    "guestEmail": {
                        "type": "string",
                        "description": "Guest email address (optional).",
                    },
                    "nights": {
                        "type": "integer",
                        "description": "Number of nights (optional, defaults to 1).",
                    },
                },
                "required": ["checkInDate", "roomType", "guestName"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "updateInventory",
            "description": (
                "Sets the absolute number of available rooms of a given type on a "
                "given date. Intended for hotel administrators managing daily inventory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format.",
                    },
                    "roomType": {
                        "type": "string",
                        "enum": ["Sea View", "Garden View"],
                        "description": "The room type to update.",
                    },
                    "count": {
                        "type": "integer",
                        "description": "The new available room count (must be >= 0).",
                    },
                },
                "required": ["date", "roomType", "count"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "searchKnowledgeBase",
            "description": (
                "Search the hotel knowledge base for answers to general questions about "
                "policies, check-in/check-out times, amenities, dining, parking, pets, "
                "cancellation, and Wi-Fi. Do not use for availability or booking."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The guest's general hotel question.",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# --------------------------------------------------------------------------- #
# Tool dispatch
# --------------------------------------------------------------------------- #
def _dispatch(name, args):
    """Run a single tool call against the offline core; return a JSON-able result."""
    if not isinstance(args, dict):
        args = {}
    if name == "checkAvailability":
        return booking_core.check_availability(
            args.get("date"), args.get("roomType")
        )
    if name == "bookRoom":
        return booking_core.book_room(
            args.get("checkInDate"),
            args.get("roomType"),
            args.get("guestName"),
            args.get("guestEmail"),
            args.get("nights", 1) if args.get("nights") is not None else 1,
        )
    if name == "updateInventory":
        return booking_core.update_inventory(
            args.get("date"), args.get("roomType"), args.get("count")
        )
    if name == "searchKnowledgeBase":
        return {
            "status": "ok",
            "query": args.get("query"),
            "results": knowledge.snippet(args.get("query", "")),
        }
    return {"status": "error", "message": f"Unknown tool '{name}'."}


# --------------------------------------------------------------------------- #
# Light-parse fallback for models that emit a tool call as text
# --------------------------------------------------------------------------- #
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_TOOL_NAMES = {"checkAvailability", "bookRoom", "updateInventory", "searchKnowledgeBase"}


def _extract_json_object(text):
    """Return the first balanced {...} JSON object in text, or None."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : i + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break
        start = text.find("{", start + 1)
    return None


def _parse_text_tool_call(content):
    """
    Parse a tool call emitted as JSON text in the content.

    Accepts a fenced ```json {...}``` block or a raw object with the shape
    {"name": ..., "arguments": {...}}. Returns (name, args) or None.
    """
    if not content:
        return None

    candidates = []
    fenced = _FENCE_RE.search(content)
    if fenced:
        try:
            candidates.append(json.loads(fenced.group(1)))
        except json.JSONDecodeError:
            pass
    raw = _extract_json_object(content)
    if raw is not None:
        candidates.append(raw)

    for obj in candidates:
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or obj.get("tool") or obj.get("function")
        args = obj.get("arguments")
        if args is None:
            args = obj.get("parameters")
        if isinstance(name, str) and name in _TOOL_NAMES:
            if not isinstance(args, dict):
                args = {}
            return name, args
    return None


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #
class Agent:
    """Holds conversation history and drives the qwen2.5 tool-calling loop."""

    def __init__(self):
        self.history = [{"role": "system", "content": _load_system_prompt()}]

    def send(self, user_text):
        """Send a user turn, run the tool loop, and return Aria's final reply."""
        self.history.append({"role": "user", "content": user_text})

        for _ in range(MAX_ITERATIONS):
            response = ollama.chat(
                model=MODEL, messages=self.history, tools=TOOLS
            )
            message = response["message"]

            content = message.get("content", "") or ""
            tool_calls = message.get("tool_calls") or []

            if tool_calls:
                # Record the assistant's tool-calling turn, then run each call.
                self.history.append(
                    {"role": "assistant", "content": content, "tool_calls": tool_calls}
                )
                for call in tool_calls:
                    fn = call.get("function", {})
                    name = fn.get("name")
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    result = _dispatch(name, args)
                    self.history.append(
                        {
                            "role": "tool",
                            "name": name,
                            "content": json.dumps(result),
                        }
                    )
                continue

            # No structured tool_calls — try the light-parse fallback.
            parsed = _parse_text_tool_call(content)
            if parsed is not None:
                name, args = parsed
                self.history.append({"role": "assistant", "content": content})
                result = _dispatch(name, args)
                self.history.append(
                    {
                        "role": "tool",
                        "name": name,
                        "content": json.dumps(result),
                    }
                )
                continue

            # Final answer with no tool call.
            self.history.append({"role": "assistant", "content": content})
            return content

        # Iteration cap reached — return the last content we have.
        return content
