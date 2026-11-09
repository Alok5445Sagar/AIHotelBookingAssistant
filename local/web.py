"""
Dependency-light FastAPI single-page chat UI for the local Aria assistant.

GET  /         -> inline HTML chat page (hotel background, glass chat card).
GET  /static/* -> local background images (served from local/static/).
POST /chat     -> {session_id, message} -> {reply}; one Agent per session_id.

Run it directly:
    python local/web.py
or via uvicorn (from the workspace root):
    uvicorn local.web:app --reload

Importing this module does NOT start a server or make any Ollama call.
"""

if __package__ in (None, ""):
    # Allow `python local/web.py` by making the workspace root importable and
    # re-dispatching as the package module `local.web`.
    import os
    import sys
    import runpy

    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    runpy.run_module("local.web", run_name="__main__", alter_sys=True)
    raise SystemExit(0)

import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .agent import Agent

app = FastAPI(title="Aria — Local Hotel Booking Assistant")

# Background images live next to this file, independent of the CWD.
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# In-memory session store: {session_id: Agent}.
_sessions = {}


def _get_agent(session_id):
    agent = _sessions.get(session_id)
    if agent is None:
        agent = Agent()
        _sessions[session_id] = agent
    return agent


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str


_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0b1d3a">
  <title>Aria — Hotel Booking Assistant</title>
  <link rel="preload" as="image" type="image/webp" href="/static/hotel-bg-900.webp" media="(max-width: 767px)">
  <link rel="preload" as="image" type="image/webp" href="/static/hotel-bg-1920.webp" media="(min-width: 768px)">
  <style>
    :root {
      --text: #f5f7fb;
      --muted: #c9d3e3;
      --gold: #f2c46d;
      --gold-dark: #d9a441;
      --ink: #1a1a1a;
      --glass: rgba(10, 22, 44, 0.5);
      --glass-border: rgba(255, 255, 255, 0.18);
      --bubble-aria: rgba(255, 255, 255, 0.14);
      --focus: #ffd98a;
    }
    *, *::before, *::after { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      color: var(--text);
      background: #0b1d3a;
      overflow-x: hidden;
      -webkit-font-smoothing: antialiased;
    }

    /* Full-viewport responsive hotel background (mobile-first portrait crop). */
    .bg {
      position: fixed;
      inset: 0;
      z-index: -2;
      background-color: #0b1d3a;
      background-image: url("/static/hotel-bg-900.jpg");
      background-image: image-set(
        url("/static/hotel-bg-900.webp") type("image/webp"),
        url("/static/hotel-bg-900.jpg") type("image/jpeg"));
      background-size: cover;
      background-position: center;
      background-repeat: no-repeat;
    }
    @media (min-width: 768px) {
      .bg {
        background-image: url("/static/hotel-bg-1920.jpg");
        background-image: image-set(
          url("/static/hotel-bg-1920.webp") type("image/webp"),
          url("/static/hotel-bg-1920.jpg") type("image/jpeg"));
      }
    }
    /* Dark gradient overlay so text on top stays readable. */
    .bg::after {
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(ellipse at center, rgba(4, 12, 28, 0.1) 0%, rgba(4, 12, 28, 0.4) 100%),
        linear-gradient(180deg, rgba(4, 14, 34, 0.2) 0%, rgba(4, 14, 34, 0.5) 100%);
    }

    .page {
      min-height: 100vh;
      min-height: 100dvh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }

    .card {
      width: 100%;
      max-width: 760px;
      height: calc(100vh - 48px);
      height: calc(100dvh - 48px);
      max-height: 880px;
      display: flex;
      flex-direction: column;
      background: var(--glass);
      border: 1px solid var(--glass-border);
      border-radius: 22px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
      -webkit-backdrop-filter: blur(12px) saturate(150%);
      backdrop-filter: blur(12px) saturate(150%);
      overflow: hidden;
    }

    header {
      display: flex;
      align-items: center;
      gap: 14px;
      padding: 18px 22px;
      border-bottom: 1px solid var(--glass-border);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0));
    }
    .logo {
      flex: none;
      width: 46px;
      height: 46px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      font-weight: 700;
      font-size: 1.25rem;
      color: var(--ink);
      background: linear-gradient(135deg, var(--gold), var(--gold-dark));
      box-shadow: 0 4px 14px rgba(242, 196, 109, 0.35);
    }
    .brand { min-width: 0; }
    .eyebrow {
      margin: 0;
      font-size: 0.72rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--gold);
    }
    h1 {
      margin: 2px 0 0;
      font-size: 1.2rem;
      font-weight: 650;
      line-height: 1.25;
    }
    .status {
      margin: 2px 0 0;
      font-size: 0.8rem;
      color: var(--muted);
    }
    .status::before {
      content: "";
      display: inline-block;
      width: 8px;
      height: 8px;
      margin-right: 6px;
      border-radius: 50%;
      background: #4ade80;
      vertical-align: 1px;
    }

    #log {
      flex: 1;
      overflow-y: auto;
      overscroll-behavior: contain;
      padding: 18px 20px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      scroll-behavior: smooth;
    }
    .msg {
      max-width: 82%;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .msg.aria { align-self: flex-start; }
    .msg.guest { align-self: flex-end; align-items: flex-end; }
    .bubble {
      padding: 10px 14px;
      border-radius: 16px;
      line-height: 1.5;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-size: 0.97rem;
    }
    .aria .bubble {
      background: var(--bubble-aria);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-bottom-left-radius: 4px;
    }
    .guest .bubble {
      background: linear-gradient(135deg, var(--gold), #f6d48f);
      color: var(--ink);
      border-bottom-right-radius: 4px;
    }
    .error .bubble {
      background: rgba(190, 40, 50, 0.35);
      border: 1px solid rgba(255, 120, 120, 0.55);
    }
    .meta {
      font-size: 0.72rem;
      color: var(--muted);
      padding: 0 4px;
    }

    .typing .bubble {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-style: italic;
    }
    .dots { display: inline-flex; gap: 4px; }
    .dots span {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--muted);
      animation: blink 1.2s infinite ease-in-out;
    }
    .dots span:nth-child(2) { animation-delay: 0.2s; }
    .dots span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes blink {
      0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
      40% { opacity: 1; transform: translateY(-3px); }
    }
    @media (prefers-reduced-motion: reduce) {
      .dots span { animation: none; opacity: 0.7; }
      #log { scroll-behavior: auto; }
    }

    .composer {
      padding: 12px 16px 14px;
      border-top: 1px solid var(--glass-border);
      background: rgba(4, 12, 28, 0.25);
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 10px;
    }
    .chip {
      font: inherit;
      font-size: 0.82rem;
      padding: 6px 12px;
      border-radius: 999px;
      border: 1px solid rgba(242, 196, 109, 0.6);
      background: rgba(242, 196, 109, 0.12);
      color: var(--text);
      cursor: pointer;
      transition: background 0.15s ease;
    }
    .chip:hover:not(:disabled) { background: rgba(242, 196, 109, 0.28); }
    form { display: flex; gap: 8px; }
    #input {
      flex: 1;
      min-width: 0;
      font: inherit;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid rgba(255, 255, 255, 0.28);
      background: rgba(255, 255, 255, 0.92);
      color: var(--ink);
    }
    #input::placeholder { color: #5b6473; }
    #send {
      flex: none;
      font: inherit;
      font-weight: 650;
      padding: 0 20px;
      border: 0;
      border-radius: 12px;
      color: var(--ink);
      background: linear-gradient(135deg, var(--gold), var(--gold-dark));
      cursor: pointer;
    }
    #send:hover:not(:disabled) { filter: brightness(1.06); }
    button:disabled, #input:disabled { opacity: 0.55; cursor: not-allowed; }
    :focus-visible {
      outline: 3px solid var(--focus);
      outline-offset: 2px;
    }
    #input:focus-visible { outline-offset: 1px; }

    .credit {
      margin: 10px 0 0;
      font-size: 0.7rem;
      color: var(--muted);
      text-align: center;
    }
    .credit a { color: var(--muted); }

    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }

    @media (max-width: 600px) {
      .page { padding: 10px; }
      .card {
        height: calc(100vh - 20px);
        height: calc(100dvh - 20px);
        max-height: none;
        border-radius: 18px;
      }
      header { padding: 14px 16px; gap: 12px; }
      .logo { width: 40px; height: 40px; font-size: 1.1rem; }
      h1 { font-size: 1.05rem; }
      #log { padding: 14px 14px; }
      .msg { max-width: 90%; }
      .composer { padding: 10px 12px 12px; }
      .eyebrow { font-size: 0.66rem; letter-spacing: 0.08em; }
      /* One swipeable row of chips keeps more room for the conversation. */
      .chips {
        flex-wrap: nowrap;
        overflow-x: auto;
        scrollbar-width: none;
        padding-bottom: 2px;
      }
      .chips::-webkit-scrollbar { display: none; }
      .chip { flex: none; font-size: 0.78rem; padding: 5px 10px; }
      #send { padding: 0 16px; }
    }
  </style>
</head>
<body>
  <div class="bg" aria-hidden="true"></div>
  <main class="page">
    <section class="card" aria-label="Chat with Aria">
      <header>
        <div class="logo" aria-hidden="true">A</div>
        <div class="brand">
          <p class="eyebrow">Premium Hotel · Sea View &amp; Garden View</p>
          <h1>Aria — your booking assistant</h1>
          <p class="status">Online · running locally on qwen2.5</p>
        </div>
      </header>

      <div id="log" role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation"></div>

      <div class="composer">
        <div class="chips" role="group" aria-label="Suggested questions">
          <button type="button" class="chip">What time is check-out?</button>
          <button type="button" class="chip">Rooms available on 2026-12-22?</button>
          <button type="button" class="chip">Book a Sea View room</button>
          <button type="button" class="chip">Hotel amenities</button>
        </div>
        <form id="form" autocomplete="off">
          <label for="input" class="sr-only">Message Aria</label>
          <input type="text" id="input" name="message" placeholder="Ask about availability, bookings, or hotel policies…" autocomplete="off" enterkeyhint="send">
          <button type="submit" id="send" aria-label="Send message">Send</button>
        </form>
        <p class="credit">Background photo by
          <a href="https://www.pexels.com/photo/lounge-chairs-around-infinity-pool-261181/" target="_blank" rel="noopener noreferrer">Pixabay on Pexels</a>
        </p>
      </div>
    </section>
  </main>

  <script>
    const sessionId = "web-" + Math.random().toString(36).slice(2);
    const log = document.getElementById("log");
    const form = document.getElementById("form");
    const input = document.getElementById("input");
    const send = document.getElementById("send");
    const chips = Array.from(document.querySelectorAll(".chip"));
    let busy = false;

    function timeNow() {
      return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }

    // Safe rendering: text nodes only; **bold** becomes <strong> via textContent.
    function fillText(el, text) {
      const parts = String(text).split(/\*\*([^*\n]+)\*\*/);
      parts.forEach((part, i) => {
        if (!part) return;
        if (i % 2 === 1) {
          const strong = document.createElement("strong");
          strong.textContent = part;
          el.appendChild(strong);
        } else {
          el.appendChild(document.createTextNode(part));
        }
      });
    }

    function scrollToEnd() {
      log.scrollTop = log.scrollHeight;
    }

    function add(kind, text, extraClass) {
      const wrap = document.createElement("div");
      wrap.className = "msg " + kind + (extraClass ? " " + extraClass : "");
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      if (kind === "aria") {
        fillText(bubble, text);
      } else {
        bubble.textContent = text;
      }
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = (kind === "guest" ? "You" : "Aria") + " · " + timeNow();
      wrap.appendChild(bubble);
      wrap.appendChild(meta);
      log.appendChild(wrap);
      scrollToEnd();
      return wrap;
    }

    function showTyping() {
      const wrap = document.createElement("div");
      wrap.className = "msg aria typing";
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      const dots = document.createElement("span");
      dots.className = "dots";
      dots.setAttribute("aria-hidden", "true");
      for (let i = 0; i < 3; i++) dots.appendChild(document.createElement("span"));
      const label = document.createElement("span");
      label.textContent = "Aria is thinking…";
      bubble.appendChild(dots);
      bubble.appendChild(label);
      wrap.appendChild(bubble);
      log.appendChild(wrap);
      scrollToEnd();
      return wrap;
    }

    function setBusy(state) {
      busy = state;
      send.disabled = state;
      chips.forEach((c) => { c.disabled = state; });
      form.setAttribute("aria-busy", state ? "true" : "false");
    }

    async function sendMessage(message) {
      if (busy) return;
      message = message.trim();
      if (!message) return;
      add("guest", message);
      input.value = "";
      setBusy(true);
      const typing = showTyping();
      try {
        const res = await fetch("/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, message })
        });
        if (!res.ok) throw new Error("server responded " + res.status);
        const data = await res.json();
        typing.remove();
        add("aria", data.reply);
      } catch (err) {
        typing.remove();
        add("aria", "Sorry, I couldn't reach the assistant (" + err.message + "). Please check that the server and Ollama are running, then try again.", "error");
      } finally {
        setBusy(false);
        input.focus();
      }
    }

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      sendMessage(input.value);
    });

    chips.forEach((chip) => {
      chip.addEventListener("click", () => sendMessage(chip.textContent));
    });

    add("aria", "Hello, I'm Aria. I can check room availability, book a **Sea View** or **Garden View** room, and answer questions about the hotel. How can I help?");
    input.focus();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return _PAGE


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    agent = _get_agent(req.session_id)
    reply = agent.send(req.message)
    return ChatResponse(reply=reply)


def main():
    """Seed the DB if empty, then launch uvicorn on a local port."""
    import uvicorn

    db.init()
    conn = db.connect()
    try:
        empty = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0
    finally:
        conn.close()
    if empty:
        db.seed()

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
