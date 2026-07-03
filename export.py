#!/usr/bin/env python3
"""
WeChat Chat Exporter — export WeChat 4.x 1-on-1 chats to plain text.

Usage:
  python3 export.py <alias_or_wxid> [output_name]

Examples:
  python3 export.py some_alias "Contact Name"
  python3 export.py wxid_xxxxxxxxxxxx "Contact"
"""

import sqlite3, os, sys, hashlib
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DECRYPTED = os.path.join(SCRIPT_DIR, "vendor", "decrypted")
OUTPUT = os.path.expanduser("~/wechat_exports")


def log(msg):
    print(f"  {msg}")


def find_wxid(contact_db, search):
    """Resolve alias, name, or wxid to (wxid, display_name)."""
    db = sqlite3.connect(contact_db)
    row = db.execute(
        "SELECT username, remark, nick_name FROM contact WHERE alias=?",
        (search,)
    ).fetchone()
    if not row:
        row = db.execute(
            "SELECT username, remark, nick_name FROM contact WHERE username=?",
            (search,)
        ).fetchone()
    if not row:
        row = db.execute(
            """SELECT username, remark, nick_name FROM contact
               WHERE username LIKE ? OR remark LIKE ? OR nick_name LIKE ? OR alias LIKE ?
               LIMIT 1""",
            (f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%')
        ).fetchone()
    db.close()
    if row:
        return row[0], (row[1] or row[2] or row[0])
    return None, None


def export_chat(wxid, display_name, output_name):
    """
    Export all messages for a given wxid using deterministic sender detection.

    real_sender_id = Name2Id.rowid (per-DB foreign key).
    JOIN Msg table with Name2Id to resolve each message's actual sender wxid.
    """
    table_name = "Msg_" + hashlib.md5(wxid.encode()).hexdigest()
    log(f"wxid: {wxid}")
    log(f"table: {table_name}")

    all_msgs = []
    stats = {}

    for db_idx in [2, 1, 0]:  # chronological: oldest first
        db_path = os.path.join(DECRYPTED, "message", f"message_{db_idx}.db")
        if not os.path.exists(db_path):
            continue
        db = sqlite3.connect(db_path)

        exists = db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        ).fetchone()[0]
        if not exists:
            db.close()
            continue

        # Deterministic: JOIN with Name2Id to get actual sender wxid
        rows = db.execute(f"""
            SELECT m.create_time, m.message_content, n.user_name
            FROM {table_name} m
            JOIN Name2Id n ON m.real_sender_id = n.rowid
            ORDER BY m.create_time ASC
        """).fetchall()

        count = 0
        for ts, content, username in rows:
            if not content or not isinstance(content, str):
                continue
            sender = display_name if username == wxid else "我"
            stats[sender] = stats.get(sender, 0) + 1
            ts_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
            all_msgs.append(f"[{ts_str}] {sender}: {content}")
            count += 1

        if rows:
            first = datetime.fromtimestamp(rows[0][0]).strftime('%Y-%m-%d')
            last = datetime.fromtimestamp(rows[-1][0]).strftime('%Y-%m-%d')
            log(f"  DB{db_idx}: {count} msgs [{first} → {last}]")
        db.close()

    if not all_msgs:
        log("No messages found.")
        return None

    # Write
    os.makedirs(OUTPUT, exist_ok=True)
    safe_name = "".join(c for c in output_name if c.isalnum() or c in (' ', '_', '-'))
    path = os.path.join(OUTPUT, f"{safe_name}.txt")

    with open(path, 'w', encoding='utf-8') as f:
        f.write(f"# Chat: {output_name} ({display_name})\n")
        f.write(f"# wxid: {wxid}\n")
        for s, c in sorted(stats.items()):
            f.write(f"# {s}: {c}\n")
        f.write(f"# Total: {len(all_msgs)}\n")
        f.write(f"# Span: {all_msgs[0][1:20]} → {all_msgs[-1][1:20]}\n\n")
        for line in all_msgs:
            f.write(line + '\n')

    size_kb = os.path.getsize(path) / 1024
    stats_str = " | ".join(f"{s}:{c}" for s, c in sorted(stats.items()))
    log(f"✓ {path} ({len(all_msgs)} msgs, {size_kb:.0f} KB — {stats_str})")
    return path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    search = sys.argv[1]
    output_name = sys.argv[2] if len(sys.argv) > 2 else search

    contact_db = os.path.join(DECRYPTED, "contact", "contact.db")
    if not os.path.exists(contact_db):
        print("Error: contact.db not found.")
        print("Run 'cd vendor && python3 decrypt_db.py' first.")
        sys.exit(1)

    wxid, display_name = find_wxid(contact_db, search)
    if not wxid:
        print(f"Contact not found: {search}")
        sys.exit(1)

    print(f"Exporting: {output_name} ({display_name})")
    export_chat(wxid, display_name, output_name)


if __name__ == "__main__":
    main()
