# WeChat Chat Export — Standard Operating Procedure

## Architecture

```
WeChat process memory
  → C scanner (Mach VM API, no sudo with Developer Mode)
  → all_keys.json {db_path: {enc_key: hex}}
  → Python decrypt_db.py (AES-256-CBC page-by-page)
  → decrypted/ SQLite databases
  → export.py (MD5(wxid) → Msg table → per-DB sender_id → txt)
```

## Step-by-Step

### Prerequisites (one-time)
```bash
sudo DevToolsSecurity -enable
# Log out and back in
```

### Step 1: Re-sign WeChat
```bash
sudo cp -R /Applications/WeChat.app /Applications/WeChat_original.app
cp -R /Applications/WeChat_original.app /tmp/WeChat_tmp.app
codesign --force --deep --sign - /tmp/WeChat_tmp.app
killall WeChat
sudo rm -rf /Applications/WeChat.app
sudo cp -R /tmp/WeChat_tmp.app /Applications/WeChat.app
# Open WeChat, scan QR to login
```

### Step 2: Build & Run Key Scanner
```bash
cd vendor
cc -O2 -o find_all_keys_macos find_all_keys_macos.c -framework Foundation
./find_all_keys_macos  # no sudo needed with Developer Mode
# → all_keys.json (chmod 600, delete after export!)
```

### Step 3: Decrypt
```bash
cd vendor
python3 decrypt_db.py
# → decrypted/ directory
```

### Step 4: Find Contact
```bash
python3 -c "
import sqlite3
db = sqlite3.connect('vendor/decrypted/contact/contact.db')
rows = db.execute(\"SELECT username, remark, nick_name, alias FROM contact WHERE alias LIKE '%AliasHere%'\").fetchall()
for r in rows: print(f'wxid={r[0]} name={r[1] or r[2]} alias={r[3]}')
"
```

### Step 5: Export
```bash
python3 export.py AliasHere "Display Name"
```

### Step 6: Restore WeChat (optional)
```bash
killall WeChat
sudo rm -rf /Applications/WeChat.app
sudo cp -R /Applications/WeChat_original.app /Applications/WeChat.app
```

## Key Technical Details

### Table Naming
| Chat Type | Table Name |
|---|---|
| 1-on-1 | `Msg_` + `MD5(wxid)` |
| Group | `Msg_` + `MD5(chatroom_id)` |

### Message Format
| Chat Type | message_content format |
|---|---|
| 1-on-1 | Plain text (no prefix) |
| Group | `wxid:\ntext` |

### Database Sharding
| DB | Content |
|---|---|
| message_0.db | Recent messages |
| message_1.db | Middle period |
| message_2.db | Oldest messages |

### sender_id Mapping
- **Different per database** — must map per DB by sampling known messages
- sender_id values MAY FLIP between databases (e.g., 1=me in DB1 but 2=me in DB2)
- Verify by reading sample messages: find messages you know YOU sent and check their sender_id
- In message_0.db: sender_id=6 is typically the account owner, but always verify

## Troubleshooting

| Problem | Solution |
|---|---|
| `task_for_pid failed: 5` | Enable Developer Mode, re-sign WeChat |
| App won't open after re-sign | Use original `cp -R`, don't change entitlements |
| Table not found | Verify wxid is correct. Check if chat is group-only |
| sender_id labels wrong | Manually verify by reading sample messages |
