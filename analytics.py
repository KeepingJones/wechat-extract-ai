"""
analytics.py — Compute and visualise WeChat chat statistics.

Usage:
    python analytics.py                # generate export/analytics.html
    python analytics.py --json         # also write export/analytics.json
    python analytics.py --top 20       # show top N contacts (default 15)
"""

import argparse
import collections
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

try:
    from jinja2 import Environment, FileSystemLoader
    HAS_JINJA = True
except ImportError:
    HAS_JINJA = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

# ── Stop words ───────────────────────────────────────────────────────────────

STOP_WORDS = set("""
i me my myself we our ours ourselves you your yours yourself yourselves
he him his himself she her hers herself it its itself they them their
theirs themselves what which who whom this that these those am is are
was were be been being have has had having do does did doing a an the
and but if or because as until while of at by for with about against
between into through during before after above below to from up down in
out on off over under again further then once here there when where why
how all both each few more most other some such no nor not only own
same so than too very s t can will just don should now d ll m o re ve y
ain aren couldn didn doesn hadn hasn haven isn ma mightn mustn needn
shan shouldn wasn weren won wouldn ok okay yeah yes no lol haha oh
get got like know one think im dont its thats
""".split())


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
    """Returns {username -> display_name}."""
    contact_db = os.path.join(decrypted_dir, "contact_contact.db")
    if not os.path.exists(contact_db):
        return {}
    conn = open_db(contact_db)
    try:
        cur = conn.execute("SELECT * FROM Contact LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return {}
    cols = {d[0].lower() for d in cur.description}

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
    dbs = []
    for fn in sorted(os.listdir(decrypted_dir)):
        if fn.startswith("message_message_") and fn.endswith(".db"):
            dbs.append(os.path.join(decrypted_dir, fn))
    return dbs


# ── Core computation ─────────────────────────────────────────────────────────

def compute_analytics(decrypted_dir, contacts, top_n=15):
    msg_dbs = find_message_dbs(decrypted_dir)
    if not msg_dbs:
        print("No message databases found in", decrypted_dir, file=sys.stderr)
        sys.exit(1)

    per_contact  = collections.defaultdict(lambda: {
        "name": "", "total": 0, "sent": 0, "received": 0,
        "images": 0, "voice": 0, "video": 0, "stickers": 0, "files": 0,
        "first_ts": None, "last_ts": None,
    })
    daily        = collections.defaultdict(int)
    hourly       = collections.defaultdict(int)
    weekday      = collections.defaultdict(int)   # 0=Mon … 6=Sun
    word_freq    = collections.defaultdict(int)
    total_msgs   = 0
    sent_total   = 0
    recv_total   = 0

    for db_path in msg_dbs:
        conn = open_db(db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
        )]

        for table in tables:
            cur = conn.execute(f"SELECT * FROM [{table}] LIMIT 1")
            if cur.fetchone() is None:
                continue
            col_names = {d[0].lower() for d in cur.description}

            time_col    = next((c for c in ["create_time","createtime","timestamp"]          if c in col_names), None)
            type_col    = next((c for c in ["local_type","type","msgtype"]                    if c in col_names), None)
            content_col = next((c for c in ["message_content","content","strcontent","body"]  if c in col_names), None)
            send_col    = next((c for c in ["issend","issender","is_sender"]                  if c in col_names), None)
            talker_col  = next((c for c in ["talker","strtalker","sender"]                    if c in col_names), None)

            if not time_col:
                continue

            select_parts = [c for c in [time_col, type_col, content_col, send_col, talker_col] if c]
            sel = ", ".join(select_parts)

            for row in conn.execute(f"SELECT {sel} FROM [{table}]"):
                row = dict(row)
                ts      = row.get(time_col)
                mtype   = int(row.get(type_col, 1) or 1)
                content = row.get(content_col, "") or ""
                is_sent = bool(row.get(send_col, 0))
                talker  = row.get(talker_col, "") or ""

                if not ts or not talker:
                    continue

                total_msgs += 1
                if is_sent:
                    sent_total += 1
                else:
                    recv_total += 1

                contact_name = contacts.get(talker, talker)
                pc = per_contact[talker]
                if not pc["name"]:
                    pc["name"] = contact_name
                pc["total"] += 1
                if is_sent:
                    pc["sent"] += 1
                else:
                    pc["received"] += 1

                if mtype == 3:   pc["images"]   += 1
                elif mtype == 34: pc["voice"]   += 1
                elif mtype == 43: pc["video"]   += 1
                elif mtype == 47: pc["stickers"] += 1
                elif mtype == 49: pc["files"]   += 1

                try:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    date_str = dt.strftime("%Y-%m-%d")
                    daily[date_str]    += 1
                    hourly[dt.hour]    += 1
                    weekday[dt.weekday()] += 1

                    if pc["first_ts"] is None or ts < pc["first_ts"]:
                        pc["first_ts"] = ts
                    if pc["last_ts"]  is None or ts > pc["last_ts"]:
                        pc["last_ts"]  = ts
                except (OSError, ValueError, OverflowError):
                    pass

                # Word frequency — plain text only, skip CJK-heavy content
                if mtype == 1 and content:
                    cjk_ratio = sum(1 for c in content if "一" <= c <= "鿿") / max(len(content), 1)
                    if cjk_ratio < 0.3:
                        for w in re.findall(r"\b[a-zA-Z]{3,}\b", content.lower()):
                            if w not in STOP_WORDS:
                                word_freq[w] += 1

        conn.close()

    # Top contacts sorted by message count
    top_contacts = sorted(per_contact.items(), key=lambda x: x[1]["total"], reverse=True)[:top_n]

    top_contacts_out = []
    for username, pc in top_contacts:
        entry = dict(pc)
        entry["username"] = username
        for field in ("first_ts", "last_ts"):
            v = entry[field]
            if v:
                try:
                    entry[field] = datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d")
                except Exception:
                    entry[field] = None
        top_contacts_out.append(entry)

    # Daily series — last 365 days
    today = datetime.now(tz=timezone.utc)
    daily_series = []
    for i in range(364, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        daily_series.append({"date": d, "count": daily.get(d, 0)})

    # Hourly series
    hourly_series = [{"hour": h, "count": hourly.get(h, 0)} for h in range(24)]

    # Weekday series
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_series = [{"day": day_names[i], "count": weekday.get(i, 0)} for i in range(7)]

    # Media totals across all contacts
    media_totals = {"images": 0, "voice": 0, "video": 0, "stickers": 0, "files": 0}
    for _, pc in per_contact.items():
        for k in media_totals:
            media_totals[k] += pc[k]

    # Top words
    top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:80]

    # Most active single day
    if daily:
        peak_day, peak_count = max(daily.items(), key=lambda x: x[1])
    else:
        peak_day, peak_count = "N/A", 0

    # Date range
    all_dates = [d["date"] for d in daily_series if d["count"] > 0]
    first_date = all_dates[0]  if all_dates else "N/A"
    last_date  = all_dates[-1] if all_dates else "N/A"

    return {
        "total_messages":  total_msgs,
        "sent_messages":   sent_total,
        "received_messages": recv_total,
        "total_contacts":  len(per_contact),
        "active_contacts": sum(1 for pc in per_contact.values() if pc["total"] > 0),
        "top_contacts":    top_contacts_out,
        "daily_series":    daily_series,
        "hourly_series":   hourly_series,
        "weekday_series":  weekday_series,
        "word_freq":       [{"word": w, "count": c} for w, c in top_words],
        "media_totals":    media_totals,
        "peak_day":        peak_day,
        "peak_count":      peak_count,
        "first_date":      first_date,
        "last_date":       last_date,
        "generated_at":    datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ── Rendering ────────────────────────────────────────────────────────────────

def render_html(data, output_dir, templates_dir):
    if not HAS_JINJA:
        print("jinja2 not installed — cannot render HTML.", file=sys.stderr)
        sys.exit(1)
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("analytics.html")
    html = template.render(data=data, data_json=json.dumps(data, ensure_ascii=False))
    out_path = os.path.join(output_dir, "analytics.html")
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Generate WeChat chat analytics dashboard")
    parser.add_argument("--json",    action="store_true", help="Also write analytics.json")
    parser.add_argument("--top",     type=int, default=15, help="Number of top contacts to show")
    args = parser.parse_args()

    config       = load_config()
    wechat_dir   = config.get("wechat_db_dir", "")
    output_dir   = config.get("output_dir", os.path.join(SCRIPT_DIR, "export"))
    decrypted_dir = os.path.join(SCRIPT_DIR, "decrypted")

    if not os.path.exists(decrypted_dir):
        print("decrypted/ folder not found. Run decryptor.py first.", file=sys.stderr)
        sys.exit(1)

    print("Loading contacts...")
    contacts = load_contacts(decrypted_dir)
    print(f"  {len(contacts)} contacts loaded")

    print("Computing analytics (this may take a moment)...")
    data = compute_analytics(decrypted_dir, contacts, top_n=args.top)

    print(f"  {data['total_messages']:,} messages across {data['active_contacts']} contacts")
    print(f"  Date range: {data['first_date']} → {data['last_date']}")
    print(f"  Peak day: {data['peak_day']} ({data['peak_count']:,} messages)")

    templates_dir = os.path.join(SCRIPT_DIR, "templates")
    out_path = render_html(data, output_dir, templates_dir)
    print(f"\nAnalytics dashboard written to: {out_path}")

    if args.json:
        json_path = os.path.join(output_dir, "analytics.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"JSON data written to: {json_path}")


if __name__ == "__main__":
    main()
