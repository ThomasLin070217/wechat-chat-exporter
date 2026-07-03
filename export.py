#!/usr/bin/env python3
"""
WeChat Chat Exporter — export WeChat 4.x 1-on-1 chats to plain text.

Usage:
  python3 export.py <alias_or_wxid> [output_name]

Examples:
  python3 export.py some_alias "Contact Name"
  python3 export.py wxid_xxxxxxxxxxxx "Contact"
  python3 export.py wxid_xxxxxxxxxxxx "Contact Name"

Requirements:
  - Decrypted WeChat databases at ./vendor/decrypted/
  - Run decrypt_db.py from ylytdeng/wechat-decrypt first
"""

import sqlite3
import os
import sys
import hashlib
from datetime import datetime

# Paths — adjust these if your setup differs
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DECRYPTED = os.path.join(SCRIPT_DIR, "vendor", "decrypted")
OUTPUT = os.path.expanduser("~/wechat_exports")


def log(msg):
    print(f"  {msg}")


def find_wxid(contact_db, search):
    """Resolve alias, name, or wxid to (wxid, display_name)."""
    db = sqlite3.connect(contact_db)

    # Try exact alias match first
    row = db.execute(
        "SELECT username, remark, nick_name FROM contact WHERE alias=?",
        (search,)
    ).fetchone()

    # Try exact wxid match
    if not row:
        row = db.execute(
            "SELECT username, remark, nick_name FROM contact WHERE username=?",
            (search,)
        ).fetchone()

    # Fuzzy match by name/remark/nickname/alias
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


def get_table_name(wxid):
    """Msg table name in WeChat 4.x: Msg_ + MD5(wxid)."""
    return "Msg_" + hashlib.md5(wxid.encode()).hexdigest()


def detect_senders(table_name, wxid):
    """
    Auto-detect sender_id → label mapping.

    IMPORTANT: sender_id is NOT consistent across databases.
    We must sample known messages from each DB to verify mapping.
    """
    sender_map = {}

    for db_idx in [2, 1, 0]:
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

        counts = db.execute(f"""
            SELECT real_sender_id, COUNT(*)
            FROM {table_name}
            WHERE message_content IS NOT NULL
            GROUP BY real_sender_id
            ORDER BY COUNT(*) DESC
        """).fetchall()

        if len(counts) < 2:
            db.close()
            continue

        # Sample messages from each sender to identify who's who
        sids = [c[0] for c in counts if c[0] > 0]
        db_map = {}

        for sid in sids[:3]:  # top 3 senders
            samples = db.execute(f"""
                SELECT message_content FROM {table_name}
                WHERE real_sender_id=? AND message_content IS NOT NULL
                ORDER BY create_time ASC LIMIT 5
            """, (sid,)).fetchall()

            texts = [s[0][:60] for s in samples if s[0] and isinstance(s[0], str)]
            # Show samples for manual verification
            log(f"    DB{db_idx} sender_id={sid}: {texts[:3]}")

        db.close()

    # Use message_0.db for initial auto-detection
    # The user should verify and override if needed
    db = sqlite3.connect(os.path.join(DECRYPTED, "message", "message_0.db"))
    exists = db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()[0]

    if exists:
        counts = db.execute(f"""
            SELECT real_sender_id, COUNT(*) FROM {table_name}
            WHERE message_content IS NOT NULL
            GROUP BY real_sender_id ORDER BY COUNT(*) DESC
        """).fetchall()

        sids = sorted([c[0] for c in counts if c[0] > 0])
        if len(sids) >= 2:
            # Assume: larger count = me (account owner usually talks more in 1-on-1)
            me = counts[0][0] if counts[0][1] > counts[1][1] else counts[1][0]
            other = counts[1][0] if me == counts[0][0] else counts[0][0]
            sender_map[0] = {me: "我", other: "对方"}
            if len(sids) >= 3:
                sender_map[0][sids[2]] = "系统"

    db.close()
    return sender_map


def export_chat(wxid, display_name, output_name):
    """Export all messages for a given wxid to a .txt file."""
    table_name = get_table_name(wxid)
    log(f"wxid: {wxid}")
    log(f"table: {table_name}")

    # Auto-detect sender mapping
    sender_map = detect_senders(table_name)
    if not sender_map:
        log("Could not detect senders. The chat may be empty.")
        return None

    for db_idx, mapping in sender_map.items():
        for sid, label in sorted(mapping.items()):
            log(f"  sender_id={sid} → {label}")

    # Collect messages from all DB shards
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

        rows = db.execute(f"""
            SELECT create_time, message_content, real_sender_id
            FROM {table_name}
            ORDER BY create_time ASC
        """).fetchall()

        id_map = sender_map.get(db_idx, sender_map.get(0, {}))
        count = 0

        for ts, content, sender_id in rows:
            if not content or not isinstance(content, str):
                continue

            sender = id_map.get(sender_id, f"?({sender_id})")
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

    # Write output
    os.makedirs(OUTPUT, exist_ok=True)
    safe_name = "".join(
        c for c in output_name if c.isalnum() or c in (' ', '_', '-', '(', ')')
    )
    path = os.path.join(OUTPUT, f"{safe_name}.txt")

    with open(path, 'w', encoding='utf-8') as f:
        f.write(f"# Chat: {output_name} ({display_name})\n")
        f.write(f"# wxid: {wxid}\n")
        for sender, count in sorted(stats.items()):
            f.write(f"# {sender}: {count}\n")
        f.write(f"# Total: {len(all_msgs)}\n")
        f.write(f"# Span: {all_msgs[0][1:20]} → {all_msgs[-1][1:20]}\n")
        f.write("\n")
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
        print("Try: WeChat alias, wxid, remark name, or nickname")
        sys.exit(1)

    print(f"Exporting: {output_name} ({display_name})")
    export_chat(wxid, display_name, output_name)


if __name__ == "__main__":
    main()
