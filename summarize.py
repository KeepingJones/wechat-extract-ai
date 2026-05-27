"""
summarize.py — Generate AI summaries of WeChat conversations.

Supports local Ollama models (default) and OpenAI (with --openai flag).
Summaries are saved to export/summaries/ as standalone HTML pages,
and a summary index is written to export/summaries/index.html.

Usage:
    python summarize.py --contact "Alice"
        Summarise all messages with Alice.

    python summarize.py --contact "Alice" --month 2024-01
        Summarise only January 2024 messages.

    python summarize.py --all
        Summarise every contact (skips contacts with < 20 messages).

    python summarize.py --all --openai
        Use OpenAI GPT-4o instead of Ollama (requires OPENAI_API_KEY env var).

Options:
    --model MODEL        Ollama model (default: llama3.2)
    --openai             Use OpenAI GPT-4o instead of Ollama
    --month YYYY-MM      Limit to a single month
    --min-messages N     Skip contacts with fewer than N messages (default: 20)
    --chunk-size N       Max messages per LLM call (default: 150)
    --rebuild            Re-summarise even if summary already exists
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH   = os.path.join(SCRIPT_DIR, "config.json")
SUMMARY_DIR   = None   # set in main() from config


# ── Config / DB helpers ──────────────────────────────────────────────────────

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print("config.json not found. Run setup_config.py first.", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def open_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def load_contacts(decrypted_dir):
    contact_db = os.path.join(decrypted_dir, "contact_contact.db")
    if not os.path.exists(contact_db):
        return {}
    conn = open_db(contact_db)
    try:
        cur = conn.execute("SELECT * FROM Contact LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return {}
    cols       = {d[0].lower() for d in cur.description}
    user_col   = next((c for c in ["username", "user_name"] if c in cols), None)
    name_col   = next((c for c in ["nick_name", "nickname"] if c in cols), None)
    remark_col = "remark" if "remark" in cols else None
    alias_col  = "alias"  if "alias"  in cols else None
    if not user_col:
        conn.close()
        return {}
    contacts = {}
    for row in conn.execute("SELECT * FROM Contact"):
        row      = dict(row)
        username = row.get(user_col, "") or ""
        if not username:
            continue
        name = (
            (remark_col and row.get(remark_col, "").strip()) or
            (name_col   and row.get(name_col,   "").strip()) or
            (alias_col  and row.get(alias_col,  "").strip()) or
            username
        )
        contacts[username] = name
    conn.close()
    return contacts


def md5_username(username):
    import hashlib
    return hashlib.md5(username.encode()).hexdigest().lower()


def find_message_dbs(decrypted_dir):
    return [
        os.path.join(decrypted_dir, fn)
        for fn in sorted(os.listdir(decrypted_dir))
        if fn.startswith("message_message_") and fn.endswith(".db")
    ]


# ── Message loading ──────────────────────────────────────────────────────────

def load_messages_for_contact(decrypted_dir, talker, month_filter=None):
    """
    Returns list of {ts, is_sent, content} for the given talker, plain text only.
    month_filter: "YYYY-MM" string or None.
    """
    target_table = "Msg_" + md5_username(talker)
    messages = []

    for db_path in find_message_dbs(decrypted_dir):
        conn = open_db(db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (target_table,)
        )]
        if not tables:
            conn.close()
            continue

        cur = conn.execute(f"SELECT * FROM [{target_table}] LIMIT 1")
        col_names = {d[0].lower() for d in cur.description}

        time_col    = next((c for c in ["create_time","createtime","timestamp"]         if c in col_names), None)
        type_col    = next((c for c in ["local_type","type","msgtype"]                   if c in col_names), None)
        content_col = next((c for c in ["message_content","content","strcontent","body"] if c in col_names), None)
        send_col    = next((c for c in ["issend","issender","is_sender"]                 if c in col_names), None)

        if not (time_col and content_col):
            conn.close()
            continue

        sel = ", ".join(filter(None, [time_col, type_col, content_col, send_col]))
        for row in conn.execute(f"SELECT {sel} FROM [{target_table}] ORDER BY {time_col}"):
            row     = dict(row)
            ts      = row.get(time_col) or 0
            mtype   = int(row.get(type_col, 1) or 1)
            content = row.get(content_col, "") or ""
            is_sent = bool(row.get(send_col, 0))

            if mtype != 1 or not content or len(content.strip()) < 2:
                continue
            if content.strip().startswith("<"):
                continue

            if month_filter:
                try:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    if dt.strftime("%Y-%m") != month_filter:
                        continue
                except Exception:
                    continue

            messages.append({"ts": ts, "is_sent": is_sent, "content": content[:500]})

        conn.close()

    return messages


def format_messages_for_llm(messages, contact_name, me_name="Me"):
    lines = []
    for m in messages:
        try:
            dt = datetime.fromtimestamp(m["ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        except Exception:
            dt = "unknown"
        speaker = me_name if m["is_sent"] else contact_name
        lines.append(f"[{dt}] {speaker}: {m['content']}")
    return "\n".join(lines)


# ── LLM calls ────────────────────────────────────────────────────────────────

SUMMARY_PROMPT = """You are summarising a WeChat conversation between {me} and {contact}.
Below are {n_messages} messages from {date_range}.

Conversation:
{conversation}

Write a clear, concise summary (3-6 bullet points) covering:
• Main topics discussed
• Key decisions or plans made
• Any notable events, dates, or places mentioned
• Overall tone and relationship dynamics

Use plain English. Be specific — mention names, dates, and details where relevant."""


def call_ollama(prompt, model="llama3.2"):
    try:
        import ollama as ollama_lib
    except ImportError:
        print(
            "ollama package not installed.\n  Run: pip install ollama\n"
            "  And start Ollama: https://ollama.com",
            file=sys.stderr,
        )
        sys.exit(1)
    response = ollama_lib.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response["message"]["content"]


def call_openai(prompt, model="gpt-4o"):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)
    try:
        import openai
    except ImportError:
        print("openai package not installed.\n  Run: pip install openai", file=sys.stderr)
        sys.exit(1)
    client = openai.OpenAI(api_key=api_key)
    resp   = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
    )
    return resp.choices[0].message.content


def summarise_messages(messages, contact_name, use_openai=False, model=None, chunk_size=150):
    """Summarise a list of messages, chunking if too many."""
    if not messages:
        return "No messages to summarise."

    # Date range
    try:
        first = datetime.fromtimestamp(messages[0]["ts"],  tz=timezone.utc).strftime("%Y-%m-%d")
        last  = datetime.fromtimestamp(messages[-1]["ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        date_range = f"{first} to {last}"
    except Exception:
        date_range = "unknown dates"

    llm_call = call_openai if use_openai else call_ollama
    llm_model = model or ("gpt-4o" if use_openai else "llama3.2")

    # If too many messages, summarise in chunks then combine
    if len(messages) > chunk_size:
        chunk_summaries = []
        for i in range(0, len(messages), chunk_size):
            chunk = messages[i:i + chunk_size]
            conv  = format_messages_for_llm(chunk, contact_name)
            prompt = SUMMARY_PROMPT.format(
                me="Me", contact=contact_name,
                n_messages=len(chunk),
                date_range=date_range,
                conversation=conv,
            )
            chunk_summaries.append(llm_call(prompt, llm_model))

        # Combine chunk summaries
        combined = "\n\n".join(f"Part {i+1}:\n{s}" for i, s in enumerate(chunk_summaries))
        combine_prompt = (
            f"These are partial summaries of a conversation between Me and {contact_name}.\n\n"
            f"{combined}\n\n"
            "Write a single unified summary (5-8 bullet points) covering the full conversation."
        )
        return llm_call(combine_prompt, llm_model)

    conv   = format_messages_for_llm(messages, contact_name)
    prompt = SUMMARY_PROMPT.format(
        me="Me", contact=contact_name,
        n_messages=len(messages),
        date_range=date_range,
        conversation=conv,
    )
    return llm_call(prompt, llm_model)


# ── HTML output ──────────────────────────────────────────────────────────────

SUMMARY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Summary: {contact_name}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#08090a;color:#e8eaed;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:40px 32px;max-width:760px;margin:0 auto}}
a{{color:#07c160;text-decoration:none}}
a:hover{{text-decoration:underline}}
.back{{font-size:13px;margin-bottom:28px;display:inline-block}}
h1{{font-size:22px;font-weight:700;color:#fff;margin-bottom:6px}}
.meta{{font-size:12px;color:rgba(255,255,255,0.35);margin-bottom:28px}}
.summary-card{{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:28px 32px}}
.summary-card h2{{font-size:14px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:rgba(255,255,255,0.35);margin-bottom:16px}}
.summary-text{{line-height:1.8;color:rgba(255,255,255,0.85);white-space:pre-wrap;font-size:14px}}
.stats-row{{display:flex;gap:24px;margin-top:24px;padding-top:20px;border-top:1px solid rgba(255,255,255,0.07)}}
.stat-item{{display:flex;flex-direction:column;gap:4px}}
.stat-v{{font-size:20px;font-weight:700;color:#07c160}}
.stat-l{{font-size:11px;color:rgba(255,255,255,0.35)}}
</style>
</head>
<body>
<a class="back" href="index.html">← All summaries</a>
<h1>{contact_name}</h1>
<div class="meta">{date_range} &nbsp;·&nbsp; {n_messages} messages &nbsp;·&nbsp; Generated {generated_at}</div>
<div class="summary-card">
  <h2>Summary</h2>
  <div class="summary-text">{summary_text}</div>
  <div class="stats-row">
    <div class="stat-item"><div class="stat-v">{n_messages}</div><div class="stat-l">messages</div></div>
    <div class="stat-item"><div class="stat-v">{date_range}</div><div class="stat-l">date range</div></div>
  </div>
</div>
</body>
</html>"""

SUMMARY_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Summaries — WeChat Exporter</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#08090a;color:#e8eaed;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:40px 32px;max-width:900px;margin:0 auto}}
a{{color:#07c160;text-decoration:none}}
.back{{font-size:13px;margin-bottom:28px;display:inline-block}}
h1{{font-size:22px;font-weight:700;color:#fff;margin-bottom:24px}}
.card-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}}
.card{{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:20px 22px;transition:border-color .2s}}
.card:hover{{border-color:rgba(7,193,96,0.35)}}
.card-name{{font-size:15px;font-weight:600;color:#fff;margin-bottom:6px}}
.card-meta{{font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:10px}}
.card-preview{{font-size:12px;color:rgba(255,255,255,0.55);line-height:1.6;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}
</style>
</head>
<body>
<a class="back" href="../index.html">← Dashboard</a>
<h1>AI Summaries</h1>
<div class="card-grid">
{cards}
</div>
</body>
</html>"""


def write_summary_html(summary_dir, contact_name, n_messages, date_range, summary_text):
    safe_name = re.sub(r'[^\w\-]', '_', contact_name)[:60]
    filename  = f"{safe_name}.html"
    path      = os.path.join(summary_dir, filename)

    html = SUMMARY_HTML.format(
        contact_name=contact_name,
        n_messages=n_messages,
        date_range=date_range,
        summary_text=summary_text,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return filename, safe_name


def rebuild_summary_index(summary_dir):
    """Scan existing summary HTMLs and regenerate index.html."""
    cards = []
    for fn in sorted(os.listdir(summary_dir)):
        if fn == "index.html" or not fn.endswith(".html"):
            continue
        contact_name = fn[:-5].replace("_", " ")
        cards.append(
            f'<a class="card" href="{fn}">'
            f'<div class="card-name">{contact_name}</div>'
            f'<div class="card-meta">Click to view summary</div>'
            f'</a>'
        )
    index_html = SUMMARY_INDEX_HTML.format(cards="\n".join(cards))
    index_path = os.path.join(summary_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)


# ── Commands ─────────────────────────────────────────────────────────────────

def do_summarise(contact_name, messages, args, summary_dir, date_range):
    n = len(messages)
    print(f"  Summarising {n} messages from {date_range}...")
    text = summarise_messages(
        messages, contact_name,
        use_openai=args.openai,
        model=args.model,
        chunk_size=args.chunk_size,
    )
    fn, _ = write_summary_html(summary_dir, contact_name, n, date_range, text)
    print(f"  Saved → {fn}")
    return text


def get_date_range(messages):
    if not messages:
        return "no messages"
    try:
        first = datetime.fromtimestamp(messages[0]["ts"],  tz=timezone.utc).strftime("%Y-%m-%d")
        last  = datetime.fromtimestamp(messages[-1]["ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        return f"{first} to {last}"
    except Exception:
        return "unknown"


def main():
    parser = argparse.ArgumentParser(
        description="Generate AI summaries of WeChat conversations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--contact",    default=None, help="Contact name to summarise")
    parser.add_argument("--all",        action="store_true", help="Summarise all contacts")
    parser.add_argument("--month",      default=None, help="Month filter: YYYY-MM")
    parser.add_argument("--model",      default=None, help="LLM model name")
    parser.add_argument("--openai",     action="store_true", help="Use OpenAI instead of Ollama")
    parser.add_argument("--min-messages", type=int, default=20, dest="min_messages",
                        help="Skip contacts with fewer messages (default: 20)")
    parser.add_argument("--chunk-size", type=int, default=150, dest="chunk_size",
                        help="Max messages per LLM call (default: 150)")
    parser.add_argument("--rebuild",    action="store_true", help="Re-summarise even if file exists")
    args = parser.parse_args()

    if not args.contact and not args.all:
        parser.error("Specify --contact NAME or --all")

    config        = load_config()
    output_dir    = config.get("output_dir", os.path.join(SCRIPT_DIR, "export"))
    decrypted_dir = os.path.join(SCRIPT_DIR, "decrypted")
    summary_dir   = os.path.join(output_dir, "summaries")

    if not os.path.exists(decrypted_dir):
        print("decrypted/ folder not found. Run decryptor.py first.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(summary_dir, exist_ok=True)

    llm_label = f"OpenAI {args.model or 'gpt-4o'}" if args.openai else f"Ollama {args.model or 'llama3.2'}"
    print(f"Using LLM: {llm_label}")

    print("Loading contacts...")
    contacts = load_contacts(decrypted_dir)

    if args.contact:
        # Find matching contacts
        search = args.contact.lower()
        matched = [(u, n) for u, n in contacts.items()
                   if search in n.lower() or search in u.lower()]
        if not matched:
            print(f"No contact matching '{args.contact}' found.", file=sys.stderr)
            sys.exit(1)
        for username, contact_name in matched:
            print(f"\nContact: {contact_name} ({username})")
            messages   = load_messages_for_contact(decrypted_dir, username, month_filter=args.month)
            date_range = get_date_range(messages)
            if len(messages) < args.min_messages:
                print(f"  Only {len(messages)} messages — skipping (use --min-messages to lower threshold)")
                continue
            do_summarise(contact_name, messages, args, summary_dir, date_range)

    elif args.all:
        print(f"Summarising all contacts with ≥ {args.min_messages} messages...")
        done = 0
        for username, contact_name in sorted(contacts.items(), key=lambda x: x[1]):
            safe_name = re.sub(r'[^\w\-]', '_', contact_name)[:60]
            out_file  = os.path.join(summary_dir, f"{safe_name}.html")
            if os.path.exists(out_file) and not args.rebuild:
                print(f"  Skipping {contact_name} (already summarised)")
                continue

            messages = load_messages_for_contact(decrypted_dir, username, month_filter=args.month)
            if len(messages) < args.min_messages:
                continue

            print(f"\n[{done+1}] {contact_name}")
            date_range = get_date_range(messages)
            do_summarise(contact_name, messages, args, summary_dir, date_range)
            done += 1

        print(f"\nSummarised {done} contacts.")

    rebuild_summary_index(summary_dir)
    print(f"\nSummary index → {os.path.join(summary_dir, 'index.html')}")
    print(f"Open in browser: {summary_dir}\\index.html")


if __name__ == "__main__":
    main()
