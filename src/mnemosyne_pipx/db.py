import sqlite3
from typing import Optional, List
from datetime import datetime, date
import os
import json
import shutil
from .paths import get_data_dir

DEFAULT_DB = os.path.join(get_data_dir(), 'mnemosyne.db')
DEFAULT_FILE_DIR = os.path.join(get_data_dir(), 'files')


def _from_json(s: Optional[str]) -> List:
    """Parse a JSON list stored in a TEXT column, tolerating empty/None/invalid."""
    if not s:
        return []
    try:
        val = json.loads(s)
        return val if isinstance(val, list) else []
    except Exception:
        return []


def init_db(path: Optional[str] = None):
    if path is None:
        path = DEFAULT_DB
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 兼容旧版本：将 images 目录重命名为 files 目录
    old_dir = os.path.join(get_data_dir(), 'images')
    if os.path.isdir(old_dir) and not os.path.isdir(DEFAULT_FILE_DIR):
        try:
            os.rename(old_dir, DEFAULT_FILE_DIR)
        except Exception:
            pass
    os.makedirs(DEFAULT_FILE_DIR, exist_ok=True)
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        examples TEXT,
        files TEXT,
        tags TEXT,
        created_at TEXT,
        updated_at TEXT,
        ease REAL DEFAULT 2.5,
        interval INTEGER DEFAULT 0,
        repetition INTEGER DEFAULT 0,
        next_review TEXT
    )
    ''')
    # 兼容旧版本：将 images 列重命名为 files 列
    cols = [row[1] for row in c.execute('PRAGMA table_info(cards)').fetchall()]
    if 'images' in cols and 'files' not in cols:
        c.execute('ALTER TABLE cards RENAME COLUMN images TO files')
    c.execute('''
    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY,
        card_id INTEGER,
        reviewed_at TEXT,
        quality INTEGER,
        feynman TEXT
    )
    ''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS profiles (
        id INTEGER PRIMARY KEY,
        name TEXT,
        difficulty TEXT DEFAULT 'normal',
        study_hours_per_day REAL DEFAULT 1.0,
        notes TEXT,
        skills TEXT,
        updated_at TEXT
    )
    ''')
    # 兼容旧版本：为 profiles 表补充 skills 列
    pcols = [row[1] for row in c.execute('PRAGMA table_info(profiles)').fetchall()]
    if 'skills' not in pcols:
        c.execute('ALTER TABLE profiles ADD COLUMN skills TEXT')
    c.execute('''
    CREATE TABLE IF NOT EXISTS interview_log (
        id INTEGER PRIMARY KEY,
        question TEXT,
        topic TEXT,
        created_at TEXT
    )
    ''')
    conn.commit()
    conn.close()
    return path


def set_profile(name: str, difficulty: str = 'normal', study_hours_per_day: float = 1.0, notes: Optional[str] = None, skills: Optional[str] = None, db_path: Optional[str] = None):
    if db_path is None:
        db_path = DEFAULT_DB
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute('INSERT INTO profiles (name,difficulty,study_hours_per_day,notes,skills,updated_at) VALUES (?,?,?,?,?,?)', (name, difficulty, study_hours_per_day, notes, skills, now))
    conn.commit()
    conn.close()


def get_profile(db_path: Optional[str] = None):
    if db_path is None:
        db_path = DEFAULT_DB
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('SELECT id,name,difficulty,study_hours_per_day,notes,skills,updated_at FROM profiles ORDER BY id DESC LIMIT 1')
    r = cur.fetchone()
    conn.close()
    if not r:
        return None
    return {'id': r[0], 'name': r[1], 'difficulty': r[2], 'study_hours_per_day': r[3], 'notes': r[4], 'skills': r[5], 'updated_at': r[6]}


def get_stats(db_path: Optional[str] = None):
    """汇总学习统计，用于画像展示。"""
    conn = get_conn(db_path)
    cur = conn.cursor()
    total = cur.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
    due = cur.execute('SELECT COUNT(*) FROM cards WHERE next_review IS NULL OR DATE(next_review) <= DATE(?)', (date.today().isoformat(),)).fetchone()[0]
    review_count = cur.execute('SELECT COUNT(*) FROM reviews').fetchone()[0]
    last_review = cur.execute('SELECT MAX(reviewed_at) FROM reviews').fetchone()[0]
    mastered = cur.execute('SELECT COUNT(*) FROM cards WHERE interval >= 21').fetchone()[0]
    conn.close()
    return {
        'total_cards': total,
        'due_cards': due,
        'review_count': review_count,
        'last_review': last_review,
        'mastered_cards': mastered,
    }


def get_conn(path: Optional[str] = None):
    if path is None:
        path = DEFAULT_DB
    return sqlite3.connect(path)


def _copy_file_to_store(file_path: str):
    if not file_path or not os.path.isfile(file_path):
        return None
    os.makedirs(DEFAULT_FILE_DIR, exist_ok=True)
    base = os.path.basename(file_path)
    dst = os.path.join(DEFAULT_FILE_DIR, base)
    if os.path.exists(dst):
        name, ext = os.path.splitext(base)
        i = 1
        while os.path.exists(os.path.join(DEFAULT_FILE_DIR, f'{name}_{i}{ext}')):
            i += 1
        dst = os.path.join(DEFAULT_FILE_DIR, f'{name}_{i}{ext}')
    shutil.copy2(file_path, dst)
    return os.path.basename(dst)


def _store_files(files: Optional[List[str]]):
    if not files:
        return []
    stored = []
    for f in files:
        try:
            stored_name = _copy_file_to_store(f)
            if stored_name:
                stored.append(stored_name)
        except Exception:
            continue
    return stored


def add_card(question: str, answer: str, examples: Optional[List[str]] = None, files: Optional[List[str]] = None, tags: Optional[List[str]] = None, db_path: Optional[str] = None):
    if examples is None:
        examples = []
    if files is None:
        files = []
    if tags is None:
        tags = []
    now = datetime.utcnow().isoformat()
    conn = get_conn(db_path)
    cur = conn.cursor()
    stored_files = _store_files(files)
    cur.execute('''INSERT INTO cards (question,answer,examples,files,tags,created_at,updated_at) VALUES (?,?,?,?,?,?,?)''',
                (question, answer, json.dumps(examples, ensure_ascii=False), json.dumps(stored_files, ensure_ascii=False), ','.join(tags), now, now))
    conn.commit()
    conn.close()


def update_card(card_id: int, question: str, answer: str, examples: Optional[List[str]] = None, files: Optional[List[str]] = None, tags: Optional[List[str]] = None, db_path: Optional[str] = None):
    if examples is None:
        examples = []
    if files is None:
        files = []
    if tags is None:
        tags = []
    now = datetime.utcnow().isoformat()
    conn = get_conn(db_path)
    cur = conn.cursor()
    stored_files = _store_files(files)
    cur.execute('''UPDATE cards SET question=?, answer=?, examples=?, files=?, tags=?, updated_at=? WHERE id=?''',
                (question, answer, json.dumps(examples, ensure_ascii=False), json.dumps(stored_files, ensure_ascii=False), ','.join(tags), now, card_id))
    conn.commit()
    conn.close()


def get_card(card_id: int, db_path: Optional[str] = None):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('SELECT id,question,answer,examples,files,tags,created_at,updated_at,ease,interval,repetition,next_review FROM cards WHERE id=?', (card_id,))
    r = cur.fetchone()
    conn.close()
    if not r:
        return None
    return {
        'id': r[0],
        'question': r[1],
        'answer': r[2],
        'examples': _from_json(r[3]),
        'files': _from_json(r[4]),
        'tags': (r[5] or '').split(',') if r[5] else [],
        'created_at': r[6],
        'updated_at': r[7],
        'ease': r[8],
        'interval': r[9],
        'repetition': r[10],
        'next_review': r[11]
    }


def delete_card(card_id: int, db_path: Optional[str] = None):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('DELETE FROM reviews WHERE card_id=?', (card_id,))
    cur.execute('DELETE FROM cards WHERE id=?', (card_id,))
    conn.commit()
    conn.close()


def list_cards(db_path: Optional[str] = None):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('SELECT id,question,answer,examples,files,tags,created_at,updated_at,ease,interval,repetition,next_review FROM cards ORDER BY id DESC')
    rows = cur.fetchall()
    conn.close()
    cards = []
    for r in rows:
        cards.append({
            'id': r[0],
            'question': r[1],
            'answer': r[2],
            'examples': _from_json(r[3]),
            'files': _from_json(r[4]),
            'tags': (r[5] or '').split(',') if r[5] else [],
            'created_at': r[6],
            'updated_at': r[7],
            'ease': r[8],
            'interval': r[9],
            'repetition': r[10],
            'next_review': r[11]
        })
    return cards


def get_cards_by_tag(tag: str, db_path: Optional[str] = None):
    """按标签精确匹配返回卡片列表（用于按来源文件查找卡片）。"""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('SELECT id,question,answer,examples,files,tags,created_at,updated_at,ease,interval,repetition,next_review FROM cards WHERE \',\' || tags || \',\' LIKE ? ORDER BY id ASC', ('%,' + tag + ',%',))
    rows = cur.fetchall()
    conn.close()
    cards = []
    for r in rows:
        cards.append({
            'id': r[0],
            'question': r[1],
            'answer': r[2],
            'examples': _from_json(r[3]),
            'files': _from_json(r[4]),
            'tags': (r[5] or '').split(',') if r[5] else [],
            'created_at': r[6],
            'updated_at': r[7],
            'ease': r[8],
            'interval': r[9],
            'repetition': r[10],
            'next_review': r[11]
        })
    return cards


def get_due_cards(as_of: Optional[date] = None, db_path: Optional[str] = None):
    if as_of is None:
        as_of = date.today()
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('SELECT id,question,answer,examples,files,tags,created_at,updated_at,ease,interval,repetition,next_review FROM cards WHERE next_review IS NULL OR DATE(next_review) <= DATE(?) ORDER BY id ASC', (as_of.isoformat(),))
    rows = cur.fetchall()
    conn.close()
    return rows


def update_card_schedule(card_id: int, ease: float, interval: int, repetition: int, next_review: Optional[str], db_path: Optional[str] = None):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('UPDATE cards SET ease=?,interval=?,repetition=?,next_review=?,updated_at=? WHERE id=?', (ease, interval, repetition, next_review, datetime.utcnow().isoformat(), card_id))
    conn.commit()
    conn.close()


def mark_cards_due(card_ids: List[int], db_path: Optional[str] = None) -> int:
    """把指定卡片标记为今日到期，用于面试薄弱点强化训练。

    将 next_review 设为今天、interval 与 repetition 归零，
    使其出现在下一次 `review` 的到期队列里。返回成功标记的卡片数。
    """
    if not card_ids:
        return 0
    conn = get_conn(db_path)
    cur = conn.cursor()
    today = date.today().isoformat()
    now = datetime.utcnow().isoformat()
    count = 0
    for cid in card_ids:
        cur.execute('UPDATE cards SET next_review=?, interval=0, repetition=0, updated_at=? WHERE id=?', (today, now, cid))
        count += cur.rowcount
    conn.commit()
    conn.close()
    return count


def record_interview_questions(questions: List[str], topic: str, db_path: Optional[str] = None):
    """记录一次面试问过的题目，用于跨次面试去重。"""
    if not questions:
        return
    conn = get_conn(db_path)
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    for q in questions:
        if q and q.strip():
            cur.execute('INSERT INTO interview_log (question, topic, created_at) VALUES (?,?,?)', (q.strip(), topic, now))
    conn.commit()
    conn.close()


def get_recent_interview_questions(limit: int = 60, db_path: Optional[str] = None) -> List[str]:
    """读取最近面试问过的题目（去重、按最近优先），用于出题时避免重复。"""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('SELECT question FROM interview_log ORDER BY id DESC LIMIT ?', (limit * 2,))
    rows = cur.fetchall()
    conn.close()
    seen = []
    for r in rows:
        q = (r[0] or '').strip()
        if q and q not in seen:
            seen.append(q)
        if len(seen) >= limit:
            break
    return seen


def record_review(card_id: int, quality: int, feynman: Optional[str] = None, db_path: Optional[str] = None):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('INSERT INTO reviews (card_id,reviewed_at,quality,feynman) VALUES (?,?,?,?)', (card_id, datetime.utcnow().isoformat(), quality, feynman))
    conn.commit()
    conn.close()


def export_db(out_path: str, db_path: Optional[str] = None):
    cards = list_cards(db_path)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)

