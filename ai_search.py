"""
ai_search.py — Semantic search and AI Q&A over your WeChat chat history.

Commands:
    python ai_search.py build
        Embed all plain-text messages and save to embeddings.db.
        First run downloads the sentence-transformers model (~90 MB, one time).

    python ai_search.py search "when did we plan the Japan trip"
        Return the top matching messages ranked by semantic similarity.

    python ai_search.py ask "what gifts did Alice mention she wanted"
        Retrieve the most relevant messages and feed them to a local Ollama LLM
        to generate a synthesised answer.

Options:
    --contact CONTACT    Filter to a single contact (name substring match)
    --top N              Number of results to show (default: 10)
    --model MODEL        Ollama model to use for 'ask' (default: llama3.2)
    --rebuild            Force full rebuild even if embeddings.db already exists
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

try:
    import zstandard as zstd
    _zstd_dctx = zstd.ZstdDecompressor()
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def decompress_content(raw):
    if not isinstance(raw, bytes) or not raw:
        return raw or ""
    if HAS_ZSTD and raw[:4] == ZSTD_MAGIC:
        try:
            return _zstd_dctx.decompress(raw, max_output_size=65536).decode("utf-8", errors="replace")
        except Exception:
            pass
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def build_md5_lookup(contacts):
    return {hashlib.md5(u.encode()).hexdigest().lower(): u for u in contacts}

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH  = os.path.join(SCRIPT_DIR, "config.json")
EMBED_DB     = os.path.join(SCRIPT_DIR, "embeddings.db")
BATCH_SIZE   = 256   # messages per embedding batch
EMBED_MODEL  = "all-MiniLM-L6-v2"   # fast, 384-dim, ~90 MB download


# ── Lazy imports (heavy libs only loaded when needed) ────────────────────────

def _require(package, pip_name=None):
    import importlib
    try:
        return importlib.import_module(package)
    except ImportError:
        name = pip_name or package
        print(f"Missing package: {name}\n  Run: pip install {name}", file=sys.stderr)
        sys.exit(1)


def _get_embedder():
    st = _require("sentence_transformers", "sentence-transformers")
    print(f"Loading embedding model '{EMBED_MODEL}' (downloads on first use)...")
    return st.SentenceTransformer(EMBED_MODEL)


def _get_numpy():
    return _require("numpy")


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
        row = dict(row)
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


def find_message_dbs(decrypted_dir):
    return [
        os.path.join(decrypted_dir, fn)
        for fn in sorted(os.listdir(decrypted_dir))
        if fn.startswith("message_message_") and fn.endswith(".db")
    ]


# ── Vector serialisation ─────────────────────────────────────────────────────

def vec_to_blob(vec):
    np = _get_numpy()
    arr = np.array(vec, dtype="float32")
    return arr.tobytes()


def blob_to_vec(blob):
    np = _get_numpy()
    return np.frombuffer(blob, dtype="float32")


def cosine_similarity(a, b):
    np = _get_numpy()
    a = np.array(a, dtype="float32")
    b = np.array(b, dtype="float32")
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


# ── Embedding database ───────────────────────────────────────────────────────

def init_embed_db():
    conn = sqlite3.connect(EMBED_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            talker      TEXT,
            contact_name TEXT,
            msg_time    INTEGER,
            msg_type    INTEGER,
            content     TEXT,
            embedding   BLOB
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_talker ON messages(talker)")
    conn.commit()
    return conn


def count_embedded(embed_conn):
    return embed_conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


# ── Build index ──────────────────────────────────────────────────────────────

def cmd_build(args):
    decrypted_dir = os.path.join(SCRIPT_DIR, "decrypted")
    if not os.path.exists(decrypted_dir):
        print("decrypted/ not found. Run decryptor.py first.", file=sys.stderr)
        sys.exit(1)

    if os.path.exists(EMBED_DB) and not args.rebuild:
        embed_conn = sqlite3.connect(EMBED_DB)
        n = embed_conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        embed_conn.close()
        print(f"embeddings.db already exists with {n:,} entries.")
        print("Use --rebuild to force a full rebuild.")
        return

    if os.path.exists(EMBED_DB):
        os.remove(EMBED_DB)
        print("Removed existing embeddings.db")

    print("Loading contacts...")
    contacts  = load_contacts(decrypted_dir)
    md5_lookup = build_md5_lookup(contacts)

    embedder   = _get_embedder()
    embed_conn = init_embed_db()
    msg_dbs    = find_message_dbs(decrypted_dir)

    total_indexed = 0
    batch_texts   = []
    batch_meta    = []

    def flush_batch():
        nonlocal total_indexed
        if not batch_texts:
            return
        vecs = embedder.encode(batch_texts, batch_size=64, show_progress_bar=False)
        rows = []
        for meta, vec in zip(batch_meta, vecs):
            rows.append((
                meta["talker"], meta["contact_name"], meta["msg_time"],
                meta["msg_type"], meta["content"], vec_to_blob(vec)
            ))
        embed_conn.executemany(
            "INSERT INTO messages (talker, contact_name, msg_time, msg_type, content, embedding) "
            "VALUES (?,?,?,?,?,?)", rows
        )
        embed_conn.commit()
        total_indexed += len(rows)
        batch_texts.clear()
        batch_meta.clear()

    print(f"Indexing messages from {len(msg_dbs)} database(s)...")

    for db_path in msg_dbs:
        conn = open_db(db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
        )]

        for table in tables:
            # Resolve talker from MD5 table name
            table_hash   = table[4:]
            talker       = md5_lookup.get(table_hash, table_hash)
            contact_name = contacts.get(talker, talker)

            cur = conn.execute(f"SELECT * FROM [{table}] LIMIT 1")
            if cur.fetchone() is None:
                continue
            col_names = {d[0].lower() for d in cur.description}

            time_col    = next((c for c in ["create_time","createtime","timestamp"]         if c in col_names), None)
            type_col    = next((c for c in ["local_type","type","msgtype"]                   if c in col_names), None)
            content_col = next((c for c in ["message_content","content","strcontent","body"] if c in col_names), None)

            if not (time_col and content_col):
                continue

            sel = ", ".join(filter(None, [time_col, type_col, content_col]))
            for row in conn.execute(f"SELECT {sel} FROM [{table}]"):
                row   = dict(row)
                ts    = row.get(time_col)
                mtype = int(row.get(type_col, 1) or 1)
                raw   = row.get(content_col, b"") or b""

                content = decompress_content(raw) if isinstance(raw, bytes) else (raw or "")

                # Only index plain-text messages with real content
                if mtype != 1 or not content or len(content.strip()) < 3:
                    continue
                if content.strip().startswith("<") or content.startswith("http"):
                    continue

                batch_texts.append(content[:512])
                batch_meta.append({
                    "talker":       talker,
                    "contact_name": contact_name,
                    "msg_time":     ts or 0,
                    "msg_type":     mtype,
                    "content":      content[:1000],
                })

                if len(batch_texts) >= BATCH_SIZE:
                    flush_batch()
                    print(f"  {total_indexed:,} messages indexed...", end="\r")

        conn.close()

    flush_batch()
    embed_conn.close()
    print(f"\nDone -- {total_indexed:,} messages indexed to embeddings.db")


# ── Search ───────────────────────────────────────────────────────────────────

def load_all_embeddings(embed_conn, contact_filter=None):
    np = _get_numpy()
    query = "SELECT id, talker, contact_name, msg_time, content, embedding FROM messages"
    params = []
    if contact_filter:
        query += " WHERE LOWER(contact_name) LIKE ? OR LOWER(talker) LIKE ?"
        pat = f"%{contact_filter.lower()}%"
        params = [pat, pat]
    rows = embed_conn.execute(query, params).fetchall()
    ids, names, times, texts, vecs = [], [], [], [], []
    for r in rows:
        ids.append(r[0])
        names.append(f"{r[2]} ({r[1]})")
        times.append(r[3])
        texts.append(r[4])
        vecs.append(blob_to_vec(r[5]))
    if not vecs:
        return [], [], [], [], None
    mat = np.stack(vecs)
    return ids, names, times, texts, mat


def semantic_search(query_text, embed_conn, embedder, top_k=10, contact_filter=None):
    np = _get_numpy()
    ids, names, times, texts, mat = load_all_embeddings(embed_conn, contact_filter)
    if mat is None:
        return []

    q_vec = embedder.encode([query_text])[0]
    q_norm = q_vec / (np.linalg.norm(q_vec) + 1e-9)
    norms  = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
    sims   = (mat / norms) @ q_norm

    top_idx = np.argsort(sims)[::-1][:top_k]
    results = []
    for i in top_idx:
        results.append({
            "score":   float(sims[i]),
            "name":    names[i],
            "time":    times[i],
            "content": texts[i],
        })
    return results


def format_result(r, i):
    try:
        dt = datetime.fromtimestamp(r["time"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        dt = "unknown"
    score_bar = "█" * int(r["score"] * 20)
    return (
        f"\n  [{i+1}] {r['name']}  ·  {dt}  ·  similarity {r['score']:.3f}  {score_bar}\n"
        f"      {r['content'][:200]}"
    )


def cmd_search(args):
    if not os.path.exists(EMBED_DB):
        print("embeddings.db not found. Run: python ai_search.py build", file=sys.stderr)
        sys.exit(1)

    embedder   = _get_embedder()
    embed_conn = sqlite3.connect(EMBED_DB)

    print(f"\nSearching for: \"{args.query}\"\n")
    results = semantic_search(
        args.query, embed_conn, embedder,
        top_k=args.top,
        contact_filter=args.contact,
    )
    embed_conn.close()

    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results):
        print(format_result(r, i))
    print()


# ── Ask (RAG) ────────────────────────────────────────────────────────────────

def cmd_ask(args):
    if not os.path.exists(EMBED_DB):
        print("embeddings.db not found. Run: python ai_search.py build", file=sys.stderr)
        sys.exit(1)

    try:
        import ollama as ollama_lib
    except ImportError:
        print(
            "ollama package not installed.\n"
            "  Run: pip install ollama\n"
            "  And make sure Ollama is running: https://ollama.com",
            file=sys.stderr,
        )
        sys.exit(1)

    embedder   = _get_embedder()
    embed_conn = sqlite3.connect(EMBED_DB)

    print(f"\nFinding relevant messages for: \"{args.query}\"...")
    results = semantic_search(
        args.query, embed_conn, embedder,
        top_k=12,
        contact_filter=args.contact,
    )
    embed_conn.close()

    if not results:
        print("No relevant messages found in the index.")
        return

    # Build context block for the LLM
    context_lines = []
    for r in results:
        try:
            dt = datetime.fromtimestamp(r["time"], tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            dt = "unknown date"
        context_lines.append(f"[{dt}] {r['name']}: {r['content'][:300]}")
    context = "\n".join(context_lines)

    prompt = (
        "You are a helpful assistant answering questions about someone's WeChat chat history.\n\n"
        "Here are the most relevant messages from their chat history:\n\n"
        f"{context}\n\n"
        f"Based only on the messages above, answer this question:\n{args.query}\n\n"
        "Be concise and cite which contact said what when relevant."
    )

    model = args.model or "llama3.2"
    print(f"Asking {model}...\n")
    print("─" * 60)

    try:
        stream = ollama_lib.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        for chunk in stream:
            text = chunk.get("message", {}).get("content", "")
            print(text, end="", flush=True)
        print("\n" + "─" * 60)
    except Exception as e:
        print(f"\nOllama error: {e}", file=sys.stderr)
        print("\nFalling back to showing the top relevant messages:\n")
        for i, r in enumerate(results[:5]):
            print(format_result(r, i))


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Semantic search and AI Q&A over WeChat chat history",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    # build
    p_build = sub.add_parser("build", help="Build the embedding index")
    p_build.add_argument("--rebuild", action="store_true", help="Force full rebuild")

    # search
    p_search = sub.add_parser("search", help="Semantic search")
    p_search.add_argument("query",    help="Search query")
    p_search.add_argument("--contact", default=None, help="Filter to a contact")
    p_search.add_argument("--top",    type=int, default=10, help="Number of results")

    # ask
    p_ask = sub.add_parser("ask", help="AI Q&A using Ollama")
    p_ask.add_argument("query",     help="Question to answer")
    p_ask.add_argument("--contact", default=None, help="Filter to a contact")
    p_ask.add_argument("--model",   default="llama3.2", help="Ollama model (default: llama3.2)")
    p_ask.add_argument("--top",     type=int, default=10)

    args = parser.parse_args()

    if args.command == "build":
        cmd_build(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "ask":
        cmd_ask(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
