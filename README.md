# WeChat Chat Exporter

Export WeChat 4.x chat records to plain text files on macOS (Apple Silicon).

**Local-first. Zero network. Batch export. AI-ready output.**

## How It Works

```
WeChat process memory → extract SQLCipher keys → decrypt local DBs → export .txt
```

1. **Extract** — C memory scanner reads WeChat's SQLCipher encryption keys from process memory
2. **Decrypt** — Python decrypts the local SQLite databases
3. **Export** — Messages exported as readable `.txt` with sender labels

## Quick Start

### Prerequisites
- macOS with Apple Silicon (M1/M2/M3/M4)
- WeChat 4.x installed
- Python 3.10+

### 1. Enable Developer Mode (one-time)
```bash
sudo DevToolsSecurity -enable
# Log out and back in
```

### 2. Re-sign WeChat (one-time per key extraction)
```bash
# Backup
sudo cp -R /Applications/WeChat.app /Applications/WeChat_original.app

# Re-sign
cp -R /Applications/WeChat_original.app /tmp/WeChat_tmp.app
codesign --force --deep --sign - /tmp/WeChat_tmp.app

# Install
killall WeChat
sudo rm -rf /Applications/WeChat.app
sudo cp -R /tmp/WeChat_tmp.app /Applications/WeChat.app

# Open WeChat, scan QR to login
```

### 3. Clone & Setup
```bash
git clone https://github.com/YOUR_USERNAME/wechat-export.git
cd wechat-export

# Clone the key extraction engine
git clone https://github.com/ylytdeng/wechat-decrypt.git vendor
cd vendor
pip install -r requirements.txt

# Build C memory scanner
cc -O2 -o find_all_keys_macos find_all_keys_macos.c -framework Foundation

# Extract keys
./find_all_keys_macos
# → all_keys.json

# Decrypt databases
python3 decrypt_db.py
# → decrypted/
cd ..
```

### 4. Export Chats
```bash
# By WeChat alias
python3 export.py some_alias "Contact Name"

# By wxid
python3 export.py wxid_xxxxxxxxxxxx "Contact Name"

# By name search
python3 export.py "张三"
```

### 5. Restore Original WeChat (optional)
```bash
killall WeChat
sudo rm -rf /Applications/WeChat.app
sudo cp -R /Applications/WeChat_original.app /Applications/WeChat.app
```

## Output Format

```text
# Chat: Alice (DisplayName)
# wxid: wxid_xxxxxxxxxxxx
# 我: 31220
# Alice: 32755
# Total: 63975
# Span: 2024-08-16 → 2026-07-01

[2024-08-16 15:54:57] Alice: I've accepted your friend request. Now let's chat!
[2024-08-16 15:56:15] 我: 张三
[2024-08-16 15:56:44] Alice: 李四
...
```

## Technical Details

| Concept | Rule |
|---|---|
| 1-on-1 table name | `Msg_` + `MD5(wxid)` |
| Group chat table name | `Msg_` + `MD5(chatroom_id)` |
| Database shards | message_0 (recent), message_1 (middle), message_2 (oldest) |
| sender_id | Varies per DB — auto-detected from samples |

## Security

- **Zero network** — Everything runs locally
- **Read-only** — Never modifies WeChat data
- **Key safety** — Delete `all_keys.json` after export
- **SIP stays on** — Only Developer Mode needed (not full SIP disable)

## Credits

- Key extraction engine: [ylytdeng/wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt)
- WeChat SQLCipher decryption approach reverse-engineered by the community

## License

MIT
