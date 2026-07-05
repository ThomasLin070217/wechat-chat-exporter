# Stage 1: Quantitative Contact Scoring
# Set these paths before running:
# DECRYPTED: path to decrypted WeChat databases
# OUTPUT: where to save scored contacts JSON
# MY_WXID: your WeChat wxid (from account folder name under xwechat_files/)

#!/usr/bin/env python3
"""Stage 1 V4: Classification + Scoring with remark/description/intro analysis."""

import sqlite3, os, json, math, hashlib, re
from datetime import datetime

DECRYPTED = "DECRYPTED_PATH"
OUTPUT = "OUTPUT_PATH"
NOW = datetime.now()
NOW_TS = int(NOW.timestamp())
MY_WXID = MY_WXID  # Replace with your wxid from the account folder name

def log(msg): print(f"  {msg}")
def percentile(vals, p):
    if not vals: return 0
    k = (len(vals) - 1) * p / 100
    f, c = math.floor(k), math.ceil(k)
    return vals[int(k)] if f == c else vals[int(f)]*(c-k) + vals[int(c)]*(k-f)

# ═══ Classification Rules ═══
FAMILY_KEYWORDS = [
    '妈', '爸', '爹', '娘', '哥', '姐', '弟', '妹', '爷', '奶', '婆', '公',
    '叔', '姨', '舅', '姑', '嫂', '侄', 'family', '亲人', '老妈', '老爸',
    '表', '堂', '伯', '婶', '丈', '媳', '婿', '孙',
]
FRIEND_KEYWORDS = [
    '同学', '朋友', 'friend', '闺蜜', '兄弟', '哥们', '室友', '舍友',
    '小学', '初中', '高中', '中学', '幼儿园',
]
WORK_KEYWORDS = [
    '公司', '科技', '集团', '有限', '投资', '资本', '基金', '创业',
    'CEO', 'CTO', 'COO', '创始人', '合伙人', '总裁', '经理', '总监',
    '董事', '客户', '商务', '销售', '市场', '运营', '产品', '研发',
    '医院', '医疗', '老师', '教授', '律师', '设计', '媒体', '金融',
    '银行', '保险', '证券', '地产', '咨询', '政府', '局长', '处长',
    '投资人', '天使', 'VC', 'PE', '奇绩创坛', '真格', '红杉', '腾讯',
    '华为', '阿里', '字节', '百度', 'ai ', 'AI', 'agent', 'startup',
    '创始人', '联合创始', 'cofounder', 'co-founder',
    '外贸', '电商', '地产', '保险', '金融', '安盛',
]
COMMUNITY_KEYWORDS = [
    'Aurora', 'InnoAI', 'ColorBlock', 'DINQ', 'Higher', 'Nexus',
    'AGENCY', '社群', '社区', '群主', '创始人', 'CoFounder',
]
SCHOOL_KEYWORDS = [
    'HKU', '香港大学', '港大', 'CUHK', '港中文', '港科大', '香港科技',
    '清华', '北大', 'THU', 'PKU', '浙大', '复旦', '交大', '斯坦福',
    'MIT', '哈佛', '牛津', '剑桥', '帝国理工', 'UCL', 'LSE',
    '华盛顿大学', '悉尼大学', '协和', '山大', '西南石油',
    '大一', '大二', '大三', '大四', '研一', '研二', '博士', '硕士',
    '中五', '中四', '中三', '中六', 'DSE', '托福', '雅思',
    'PHd', 'PhD', 'UG', 'undergrad', 'graduate',
    '遵礼', '一中', '二中', '望海园', '鲸园', '实验',
]

def classify(remark, nick, alias, description, intro_msgs):
    """Return list of applicable categories (multi-label)."""
    text = f"{remark or ''} {nick or ''} {alias or ''} {description or ''} {''.join(intro_msgs[:5])}".lower()
    display_text = f"{remark or ''} {nick or ''} {alias or ''}".lower()

    scores = {"家人": 0, "朋友": 0, "工作": 0, "社区": 0, "学校": 0}

    for kw in FAMILY_KEYWORDS:
        if kw.lower() in text: scores["家人"] += 1
    for kw in FRIEND_KEYWORDS:
        if kw.lower() in text: scores["朋友"] += 1
    for kw in WORK_KEYWORDS:
        if kw.lower() in text: scores["工作"] += 1
    for kw in COMMUNITY_KEYWORDS:
        if kw.lower() in text: scores["社区"] += 1
    for kw in SCHOOL_KEYWORDS:
        if kw.lower() in text: scores["学校"] += 1

    # Strong signals
    if any(k in display_text for k in ['妈', '爸', '妹', '姐', '哥', '弟', 'lqx']):
        scores["家人"] += 3
    if any(k in display_text for k in ['老师', '教授']):
        scores["工作"] += 2
    if alias:
        al = alias.lower()
        if any(k in al for k in ['aurora', 'inno', 'colorblock', 'dinq']):
            scores["社区"] += 3
    if description:
        dl = description.lower()
        if any(k in dl for k in ['创始人', 'ceo', 'cto', 'cofounder', '合伙人']):
            scores["工作"] += 3
        if any(k in dl for k in ['大学', '学院', '本科', '硕士', '博士', 'phd', 'hku']):
            scores["学校"] += 3

    # Return all categories with score >= threshold (1 for most, 2 for strong)
    result = [cat for cat, score in scores.items() if score >= 1]
    # Everyone with 1-on-1 chat history who isn't otherwise classified = at least "朋友"
    # but don't force it if they already have other categories
    return result if result else ["其他"]

def main():
    os.makedirs(OUTPUT, exist_ok=True)

    # ═══ Load contact DB ═══
    cdb = sqlite3.connect(os.path.join(DECRYPTED, "contact/contact.db"))
    contacts = cdb.execute("""
        SELECT username, remark, nick_name, alias, local_type, description
        FROM contact WHERE username != '' AND delete_flag = 0
    """).fetchall()

    # Load labels (names only for now)
    labels = {r[0]: r[1] for r in cdb.execute("SELECT label_id_, label_name_ FROM contact_label").fetchall()}
    cdb.close()

    # ═══ Build table classifier ═══
    mdb = sqlite3.connect(os.path.join(DECRYPTED, "message/message_0.db"))
    hash_to_id = {}
    for row in mdb.execute("SELECT user_name FROM Name2Id WHERE user_name != ''").fetchall():
        h = hashlib.md5(row[0].encode()).hexdigest()
        hash_to_id[h] = row[0]

    on_one_tables = {}
    group_tables = {}
    for mt in [t[0] for t in mdb.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'").fetchall()]:
        h = mt[4:]
        if h not in hash_to_id: continue
        wid = hash_to_id[h]
        count = mdb.execute(f"SELECT COUNT(*) FROM {mt}").fetchone()[0]
        (group_tables if '@chatroom' in wid else on_one_tables).setdefault(wid, []).append((0, mt, count))
    log(f"{len(on_one_tables)} 1-on-1, {len(group_tables)} groups")

    # ═══ Per-contact stats (1-on-1 only) ═══
    contact_stats = {}
    for wxid, tlist in on_one_tables.items():
        stats = {"count": 0, "first_ts": None, "last_ts": None, "from_me": 0, "from_them": 0,
                 "msgs_7d": 0, "msgs_30d": 0, "msgs_90d": 0, "msgs_365d": 0, "intro": []}
        for db_idx, mt, _ in tlist:
            try:
                db = sqlite3.connect(os.path.join(DECRYPTED, f"message/message_{db_idx}.db"))
                row = db.execute(f"""
                    SELECT COUNT(*), MIN(m.create_time), MAX(m.create_time),
                           SUM(CASE WHEN m.create_time >= ? THEN 1 ELSE 0 END),
                           SUM(CASE WHEN m.create_time >= ? THEN 1 ELSE 0 END),
                           SUM(CASE WHEN m.create_time >= ? THEN 1 ELSE 0 END),
                           SUM(CASE WHEN m.create_time >= ? THEN 1 ELSE 0 END)
                    FROM {mt} m WHERE m.message_content IS NOT NULL
                """, (NOW_TS-7*86400, NOW_TS-30*86400, NOW_TS-90*86400, NOW_TS-365*86400)).fetchone()
                c, ft, lt, w7, w30, w90, w365 = row
                stats["count"] += (c or 0)
                stats["msgs_7d"] += (w7 or 0)
                stats["msgs_30d"] += (w30 or 0)
                stats["msgs_90d"] += (w90 or 0)
                stats["msgs_365d"] += (w365 or 0)
                if ft and (stats["first_ts"] is None or ft < stats["first_ts"]): stats["first_ts"] = ft
                if lt and (stats["last_ts"] is None or lt > stats["last_ts"]): stats["last_ts"] = lt
                mc = db.execute(f"""
                    SELECT COUNT(*) FROM {mt} m JOIN Name2Id n ON m.real_sender_id=n.rowid
                    WHERE n.user_name=? AND m.message_content IS NOT NULL
                """, (MY_WXID,)).fetchone()[0]
                stats["from_me"] += (mc or 0)
                stats["from_them"] += max(0, (c or 0) - (mc or 0))
                if not stats["intro"]:
                    for it_ts, it_content, it_user in db.execute(f"""
                        SELECT m.create_time, m.message_content, n.user_name FROM {mt} m
                        JOIN Name2Id n ON m.real_sender_id=n.rowid
                        WHERE m.message_content IS NOT NULL ORDER BY m.create_time ASC LIMIT 10
                    """).fetchall():
                        if isinstance(it_content, str):
                            w = "我" if it_user == MY_WXID else "对方"
                            stats["intro"].append(f"[{datetime.fromtimestamp(it_ts):%Y-%m-%d %H:%M}] {w}: {it_content[:120]}")
                db.close()
            except: pass
        contact_stats[wxid] = stats

    # ═══ Group contributions ═══
    group_contrib = {}
    for chatroom_id, tlist in group_tables.items():
        for db_idx, mt, _ in tlist:
            try:
                db = sqlite3.connect(os.path.join(DECRYPTED, f"message/message_{db_idx}.db"))
                for username, count in db.execute(f"""
                    SELECT n.user_name, COUNT(*) FROM {mt} m
                    JOIN Name2Id n ON m.real_sender_id=n.rowid
                    WHERE m.message_content IS NOT NULL GROUP BY n.user_name
                """).fetchall():
                    if username == MY_WXID or '@chatroom' in username: continue
                    gc = group_contrib.setdefault(username, {"groups": 0, "msgs": 0})
                    gc["groups"] += 1
                    gc["msgs"] += count
                db.close()
            except: pass
    mdb.close()
    log(f"Group contributions: {len(group_contrib)} contacts")

    # ═══ Scoring ═══
    on_one_counts = sorted([s["count"] for s in contact_stats.values() if s["count"] > 0])
    p50, p80, p95 = percentile(on_one_counts, 50), percentile(on_one_counts, 80), percentile(on_one_counts, 95) if on_one_counts else (5, 30, 200)
    log(f"Percentiles: p50={p50:.0f} p80={p80:.0f} p95={p95:.0f}")

    results = []
    for contact in contacts:
        wxid, remark, nick, alias, local_type, description = contact
        s = contact_stats.get(wxid, {})
        gc = group_contrib.get(wxid, {"groups": 0, "msgs": 0})
        count = s.get("count", 0)
        from_me, from_them = s.get("from_me", 0), s.get("from_them", 0)
        ft, lt = s.get("first_ts"), s.get("last_ts")
        w7, w30, w90, w365 = s.get("msgs_7d", 0), s.get("msgs_30d", 0), s.get("msgs_90d", 0), s.get("msgs_365d", 0)
        intro = s.get("intro", [])
        groups, group_msgs = gc["groups"], gc["msgs"]
        display = remark or nick or alias or wxid

        # ═══ CLASSIFICATION (multi-label) ═══
        categories = classify(remark, nick, alias, description or '', intro)

        # ═══ IDENTITY (15) ═══
        id_score = 0
        if remark: id_score += 4
        if alias: id_score += 2
        if nick: id_score += 1
        if count > 0: id_score += 3
        if local_type == 1: id_score += 2
        if description: id_score += 1  # has rich description
        id_score = min(id_score, 15)

        # ═══ RELATIONSHIP (25) ═══
        rel_score = 0
        if count > 0:
            rel_score += 5
            if count >= p50: rel_score += 2
            if count >= p80: rel_score += 2
            if count >= p95: rel_score += 2
            if from_me > 0 and from_them > 0:
                ratio = min(from_me, from_them) / max(from_me, from_them, 1)
                if ratio > 0.3: rel_score += 1
                if ratio > 0.6: rel_score += 2
            if ft and lt:
                days = (lt - ft) / 86400
                if days > 30: rel_score += 1
                if days > 180: rel_score += 1
                if days > 365: rel_score += 1
        if remark: rel_score += 4
        if alias: rel_score += 2
        if description: rel_score += 2  # extra detail = stronger relationship
        rel_score = min(rel_score, 25)

        # ═══ RECENCY (20) ═══
        recency = 0
        if w7 >= 3: recency = 20
        elif w30 >= 5: recency = 17
        elif w90 >= 8: recency = 14
        elif w365 >= 10: recency = 10
        elif lt:
            days_ago = (NOW - datetime.fromtimestamp(lt)).days
            if days_ago <= 90: recency = 7
            elif days_ago <= 365: recency = 3
            else: recency = 1

        # ═══ NETWORK (10) ═══
        net_score = 0
        if groups >= 10: net_score += 4
        elif groups >= 5: net_score += 3
        elif groups >= 2: net_score += 2
        elif groups >= 1: net_score += 1
        if group_msgs >= 500: net_score += 3
        elif group_msgs >= 100: net_score += 2
        elif group_msgs >= 10: net_score += 1
        if count > 0 and groups > 0: net_score += 1
        net_score = min(net_score, 10)

        total = id_score + rel_score + recency + net_score
        total_100 = min(round(total * 100 / 70), 100)

        if total >= 50: tier = "A"
        elif total >= 35: tier = "B"
        elif total >= 25: tier = "C"
        elif total >= 15: tier = "D"
        else: tier = "E"

        reconnect = 0
        if rel_score >= 12 and recency <= 10 and lt:
            days_ago = (NOW - datetime.fromtimestamp(lt)).days
            reconnect = min(rel_score + days_ago // 30, 60)

        last_days = (NOW - datetime.fromtimestamp(lt)).days if lt else None

        results.append({
            "wxid": wxid, "display": display, "remark": remark, "nick": nick, "alias": alias,
            "description": description or "",
            "categories": categories,
            "msgs_1on1": count, "from_me": from_me, "from_them": from_them,
            "msgs_7d": w7, "msgs_30d": w30, "msgs_90d": w90, "msgs_365d": w365,
            "first_ts": ft, "last_ts": lt, "last_days": last_days,
            "span_days": int((lt-ft)/86400) if (ft and lt) else 0,
            "group_count": groups, "group_msgs": group_msgs,
            "id_score": id_score, "rel_score": rel_score, "recency": recency, "net_score": net_score,
            "total_raw": total, "total_100": total_100, "tier": tier, "reconnect": reconnect,
            "intro": intro,
        })

    results.sort(key=lambda x: (-x["total_raw"], -x["msgs_1on1"], -x["group_msgs"]))

    # ═══ Output ═══
    json_path = os.path.join(OUTPUT, "contacts_scored.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Per-category breakdown (multi-label: contacts can appear in multiple categories)
    cat_index = {}
    for r in results:
        for cat in r["categories"]:
            cat_index.setdefault(cat, []).append(r)

    print(f"\n{'='*60}")
    print(f"Stage 1 V4 — Multi-Label Classified & Scored")
    print(f"{'='*60}")
    print(f"\nCategory coverage:")
    for cat in ["家人", "朋友", "工作", "社区", "学校", "其他"]:
        cat_results = cat_index.get(cat, [])
        tier_a = sum(1 for r in cat_results if r["tier"] == "A")
        print(f"  {cat}: {len(cat_results)} contacts (Tier A: {tier_a})")

    # Multi-identity contacts
    multi = [r for r in results if len(r["categories"]) > 1]
    print(f"\n  多重身份: {len(multi)} contacts belong to 2+ categories")

    # Print top per category
    for cat in ["家人", "朋友", "工作", "社区", "学校"]:
        cat_results = sorted(cat_index.get(cat, []), key=lambda x: -x["total_raw"])[:5]
        print(f"\n═══ Top {cat} ═══")
        for i, r in enumerate(cat_results):
            other_cats = [c for c in r["categories"] if c != cat]
            multi_tag = f" +{','.join(other_cats)}" if other_cats else ""
            desc_hint = r["description"][:50] if r["description"] else ""
            print(f"  {i+1}. {r['display'][:22]:<22} {r['total_raw']:>2}pts | "
                  f"1on1:{r['msgs_1on1']:>5}msgs | groups:{r['group_count']:>2} | "
                  f"7d:{r['msgs_7d']:>3}{multi_tag}")

    # Full ranking text output
    txt_path = os.path.join(OUTPUT, "contacts_ranked.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f"# Personal CRM — Stage 1 V4 (Classified)\n")
        f.write(f"# {NOW.strftime('%Y-%m-%d')}\n\n")
        for cat in ["家人", "朋友", "工作", "社区", "学校"]:
            cat_results = sorted(cat_index.get(cat, []), key=lambda x: -x["total_raw"])
            f.write(f"\n{'='*60}\n")
            f.write(f"  {cat} ({len(cat_results)} contacts)\n")
            f.write(f"{'='*60}\n")
            for i, r in enumerate(cat_results[:20]):
                cats = ','.join(r['categories'])
                f.write(f"\n{i+1}. {r['display']} — {r['total_raw']}pts Tier:{r['tier']} [{cats}]\n")
                f.write(f"   1on1:{r['msgs_1on1']}msgs | 7d:{r['msgs_7d']} 30d:{r['msgs_30d']} | groups:{r['group_count']}\n")
                if r["description"]:
                    f.write(f"   Description: {r['description'][:150]}\n")
                if r["intro"]:
                    f.write(f"   Intro: {r['intro'][0][:120]}\n")

    print(f"\nJSON: {json_path}")
    print(f"TXT:  {txt_path}")

if __name__ == "__main__":
    main()
