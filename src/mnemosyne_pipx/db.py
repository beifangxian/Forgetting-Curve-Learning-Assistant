import sqlite3
from typing import Optional, List, Dict
from datetime import datetime, date
import os
import json
import shutil
from .paths import get_data_dir

DEFAULT_DB = os.path.join(get_data_dir(), 'mnemosyne.db')
DEFAULT_FILE_DIR = os.path.join(get_data_dir(), 'files')

# 预置的学科分区
DEFAULT_SUBJECTS = ['英语', '嵌入式', '数学']


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
        subject TEXT,
        direction TEXT,
        created_at TEXT,
        updated_at TEXT,
        ease REAL DEFAULT 2.5,
        interval INTEGER DEFAULT 0,
        repetition INTEGER DEFAULT 0,
        next_review TEXT
    )
    ''')
    # 兼容旧版本：将 images 列重命名为 files 列、补充 subject 列
    cols = [row[1] for row in c.execute('PRAGMA table_info(cards)').fetchall()]
    if 'images' in cols and 'files' not in cols:
        c.execute('ALTER TABLE cards RENAME COLUMN images TO files')
        cols = [row[1] for row in c.execute('PRAGMA table_info(cards)').fetchall()]
    if 'subject' not in cols:
        c.execute('ALTER TABLE cards ADD COLUMN subject TEXT')
        cols = [row[1] for row in c.execute('PRAGMA table_info(cards)').fetchall()]
    if 'direction' not in cols:
        c.execute('ALTER TABLE cards ADD COLUMN direction TEXT')
    _backfill_directions(c)
    c.execute('''
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        description TEXT,
        created_at TEXT
    )
    ''')
    # 预置默认学科分区：英语、嵌入式、数学
    for s in DEFAULT_SUBJECTS:
        c.execute('INSERT OR IGNORE INTO subjects (name, description, created_at) VALUES (?,?,?)', (s, '', datetime.utcnow().isoformat()))
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
    # 兼容旧版本：为 profiles 表补充 skills / weaknesses / projects 列
    pcols = [row[1] for row in c.execute('PRAGMA table_info(profiles)').fetchall()]
    if 'skills' not in pcols:
        c.execute('ALTER TABLE profiles ADD COLUMN skills TEXT')
    if 'weaknesses' not in pcols:
        c.execute('ALTER TABLE profiles ADD COLUMN weaknesses TEXT')
    if 'projects' not in pcols:
        c.execute('ALTER TABLE profiles ADD COLUMN projects TEXT')
    c.execute('''
    CREATE TABLE IF NOT EXISTS interview_log (
        id INTEGER PRIMARY KEY,
        question TEXT,
        topic TEXT,
        score INTEGER,
        user_answer TEXT,
        correct INTEGER,
        knowledge_point TEXT,
        reference TEXT,
        difficulty TEXT,
        created_at TEXT
    )
    ''')
    # 兼容旧库：为 interview_log 补充答题结果相关列（记录答对/答错与知识点，用于跨次面试出题策略）
    icols = [row[1] for row in c.execute('PRAGMA table_info(interview_log)').fetchall()]
    for col, ddl in (
        ('score', 'ALTER TABLE interview_log ADD COLUMN score INTEGER'),
        ('user_answer', 'ALTER TABLE interview_log ADD COLUMN user_answer TEXT'),
        ('correct', 'ALTER TABLE interview_log ADD COLUMN correct INTEGER'),
        ('knowledge_point', 'ALTER TABLE interview_log ADD COLUMN knowledge_point TEXT'),
        ('reference', 'ALTER TABLE interview_log ADD COLUMN reference TEXT'),
        ('difficulty', 'ALTER TABLE interview_log ADD COLUMN difficulty TEXT'),
    ):
        if col not in icols:
            c.execute(ddl)
    c.execute('''
    CREATE TABLE IF NOT EXISTS weakness_history (
        id INTEGER PRIMARY KEY,
        weakness_tag TEXT,
        question TEXT,
        answer TEXT,
        qtype TEXT,
        correct INTEGER,
        created_at TEXT
    )
    ''')
    conn.commit()
    conn.close()
    return path


def set_profile(name: str, difficulty: str = 'normal', study_hours_per_day: float = 1.0, notes: Optional[str] = None, skills: Optional[str] = None, projects: Optional[str] = None, db_path: Optional[str] = None):
    if db_path is None:
        db_path = DEFAULT_DB
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute('SELECT id FROM profiles ORDER BY id DESC LIMIT 1')
    row = cur.fetchone()
    if row:
        # 更新最新一行；notes/skills/projects 为 None 时保留原值，避免覆盖未传入字段
        cur.execute('''UPDATE profiles SET name=?, difficulty=?, study_hours_per_day=?,
                       notes=COALESCE(?, notes), skills=COALESCE(?, skills), projects=COALESCE(?, projects), updated_at=?
                       WHERE id=?''',
                    (name, difficulty, study_hours_per_day, notes, skills, projects, now, row[0]))
    else:
        cur.execute('INSERT INTO profiles (name,difficulty,study_hours_per_day,notes,skills,projects,updated_at) VALUES (?,?,?,?,?,?,?)',
                    (name, difficulty, study_hours_per_day, notes, skills, projects, now))
    conn.commit()
    conn.close()


def get_profile(db_path: Optional[str] = None):
    if db_path is None:
        db_path = DEFAULT_DB
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('SELECT id,name,difficulty,study_hours_per_day,notes,skills,weaknesses,projects,updated_at FROM profiles ORDER BY id DESC LIMIT 1')
    r = cur.fetchone()
    conn.close()
    if not r:
        return None
    return {'id': r[0], 'name': r[1], 'difficulty': r[2], 'study_hours_per_day': r[3], 'notes': r[4], 'skills': r[5], 'weaknesses': r[6], 'projects': r[7], 'updated_at': r[8]}


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


def add_subject(name: str, description: Optional[str] = None, db_path: Optional[str] = None):
    """新建一个学科分区（幂等：同名不会重复创建）。"""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('INSERT OR IGNORE INTO subjects (name, description, created_at) VALUES (?,?,?)',
                (name.strip(), (description or '').strip(), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def list_subjects(db_path: Optional[str] = None):
    """列出所有分区，附带各分区卡片数与今日到期数。"""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('SELECT name, description FROM subjects ORDER BY id ASC')
    rows = cur.fetchall()
    today = date.today().isoformat()
    subjects = []
    for r in rows:
        name = r[0]
        total = cur.execute('SELECT COUNT(*) FROM cards WHERE subject=?', (name,)).fetchone()[0]
        due = cur.execute('SELECT COUNT(*) FROM cards WHERE subject=? AND (next_review IS NULL OR DATE(next_review) <= DATE(?))', (name, today)).fetchone()[0]
        subjects.append({'name': name, 'description': r[1] or '', 'total_cards': total, 'due_cards': due})
    conn.close()
    return subjects


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


def _ensure_subject(cur, subject: Optional[str]):
    """若分区名非空且尚未登记，则写入 subjects 表（幂等）。"""
    if not subject or not subject.strip():
        return
    name = subject.strip()
    cur.execute('INSERT OR IGNORE INTO subjects (name, description, created_at) VALUES (?,?,?)', (name, '', datetime.utcnow().isoformat()))


def add_card(question: str, answer: str, examples: Optional[List[str]] = None, files: Optional[List[str]] = None, tags: Optional[List[str]] = None, subject: Optional[str] = None, direction: Optional[str] = None, db_path: Optional[str] = None):
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
    _ensure_subject(cur, subject)
    cur.execute('''INSERT INTO cards (question,answer,examples,files,tags,subject,direction,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)''',
                (question, answer, json.dumps(examples, ensure_ascii=False), json.dumps(stored_files, ensure_ascii=False), ','.join(tags), (subject or '').strip() or None, (direction or '').strip() or None, now, now))
    conn.commit()
    conn.close()


def update_card(card_id: int, question: str, answer: str, examples: Optional[List[str]] = None, files: Optional[List[str]] = None, tags: Optional[List[str]] = None, subject: Optional[str] = None, direction: Optional[str] = None, db_path: Optional[str] = None):
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
    _ensure_subject(cur, subject)
    cur.execute('''UPDATE cards SET question=?, answer=?, examples=?, files=?, tags=?, subject=?, direction=?, updated_at=? WHERE id=?''',
                (question, answer, json.dumps(examples, ensure_ascii=False), json.dumps(stored_files, ensure_ascii=False), ','.join(tags), (subject or '').strip() or None, (direction or '').strip() or None, now, card_id))
    conn.commit()
    conn.close()


def get_card(card_id: int, db_path: Optional[str] = None):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('SELECT id,question,answer,examples,files,tags,subject,direction,created_at,updated_at,ease,interval,repetition,next_review FROM cards WHERE id=?', (card_id,))
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
        'subject': r[6],
        'direction': r[7],
        'created_at': r[8],
        'updated_at': r[9],
        'ease': r[10],
        'interval': r[11],
        'repetition': r[12],
        'next_review': r[13]
    }


def delete_card(card_id: int, db_path: Optional[str] = None):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('DELETE FROM reviews WHERE card_id=?', (card_id,))
    cur.execute('DELETE FROM cards WHERE id=?', (card_id,))
    conn.commit()
    conn.close()


def list_cards(db_path: Optional[str] = None, subject: Optional[str] = None, direction: Optional[str] = None):
    conn = get_conn(db_path)
    cur = conn.cursor()
    cols = 'id,question,answer,examples,files,tags,subject,direction,created_at,updated_at,ease,interval,repetition,next_review'
    if subject and direction:
        cur.execute('SELECT {0} FROM cards WHERE subject=? AND direction=? ORDER BY id DESC'.format(cols), (subject, direction))
    elif subject:
        cur.execute('SELECT {0} FROM cards WHERE subject=? ORDER BY id DESC'.format(cols), (subject,))
    elif direction:
        cur.execute('SELECT {0} FROM cards WHERE direction=? ORDER BY id DESC'.format(cols), (direction,))
    else:
        cur.execute('SELECT {0} FROM cards ORDER BY id DESC'.format(cols))
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
            'subject': r[6],
            'direction': r[7],
            'created_at': r[8],
            'updated_at': r[9],
            'ease': r[10],
            'interval': r[11],
            'repetition': r[12],
            'next_review': r[13]
        })
    return cards


def get_cards_by_tag(tag: str, db_path: Optional[str] = None):
    """按标签精确匹配返回卡片列表（用于按来源文件查找卡片）。"""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('SELECT id,question,answer,examples,files,tags,subject,direction,created_at,updated_at,ease,interval,repetition,next_review FROM cards WHERE \',\' || tags || \',\' LIKE ? ORDER BY id ASC', ('%,' + tag + ',%',))
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
            'subject': r[6],
            'direction': r[7],
            'created_at': r[8],
            'updated_at': r[9],
            'ease': r[10],
            'interval': r[11],
            'repetition': r[12],
            'next_review': r[13]
        })
    return cards


def get_due_cards(as_of: Optional[date] = None, db_path: Optional[str] = None, subject: Optional[str] = None, direction: Optional[str] = None):
    if as_of is None:
        as_of = date.today()
    conn = get_conn(db_path)
    cur = conn.cursor()
    cols = 'id,question,answer,examples,files,tags,subject,direction,created_at,updated_at,ease,interval,repetition,next_review'
    if subject and direction:
        cur.execute('SELECT {0} FROM cards WHERE (next_review IS NULL OR DATE(next_review) <= DATE(?)) AND subject=? AND direction=? ORDER BY id ASC'.format(cols), (as_of.isoformat(), subject, direction))
    elif subject:
        cur.execute('SELECT {0} FROM cards WHERE (next_review IS NULL OR DATE(next_review) <= DATE(?)) AND subject=? ORDER BY id ASC'.format(cols), (as_of.isoformat(), subject))
    elif direction:
        cur.execute('SELECT {0} FROM cards WHERE (next_review IS NULL OR DATE(next_review) <= DATE(?)) AND direction=? ORDER BY id ASC'.format(cols), (as_of.isoformat(), direction))
    else:
        cur.execute('SELECT {0} FROM cards WHERE next_review IS NULL OR DATE(next_review) <= DATE(?) ORDER BY id ASC'.format(cols), (as_of.isoformat(),))
    rows = cur.fetchall()
    conn.close()
    return rows


def list_directions(subject: Optional[str] = None, db_path: Optional[str] = None) -> List[str]:
    """列出卡片库中已有的方向（去重），可按学科分区过滤。"""
    conn = get_conn(db_path)
    cur = conn.cursor()
    if subject:
        cur.execute("SELECT DISTINCT direction FROM cards WHERE subject=? AND direction IS NOT NULL AND direction != '' ORDER BY direction ASC", (subject,))
    else:
        cur.execute("SELECT DISTINCT direction FROM cards WHERE direction IS NOT NULL AND direction != '' ORDER BY direction ASC")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows if r[0]]


def _backfill_directions(cur):
    """兼容旧库：为「嵌入式」卡片按来源标签回填方向（编程语言 / MCU）。幂等。"""
    cur.execute("UPDATE cards SET direction='编程语言' WHERE subject='嵌入式' AND (direction IS NULL OR direction='') AND tags LIKE '%md:C语言%'")
    cur.execute("UPDATE cards SET direction='MCU' WHERE subject='嵌入式' AND (direction IS NULL OR direction='') AND tags LIKE '%md:STM32%'")


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


def record_interview_result(question: str, topic: str, score: int, user_answer: str, reference: str, difficulty: str, correct: bool, knowledge_point: Optional[str] = None, db_path: Optional[str] = None):
    """记录一道面试题的完整答题结果（题目、得分、是否答对、知识点等）。

    用于跨次面试的出题策略：答对的题（correct=1）下次不再问，
    答错的题（correct=0）下次换个问法重新考察。
    """
    if not question or not question.strip():
        return
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('''INSERT INTO interview_log (question, topic, score, user_answer, correct, knowledge_point, reference, difficulty, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)''',
                (question.strip(), topic, score, user_answer, 1 if correct else 0, (knowledge_point or '').strip(), reference, difficulty, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def _dedup_interview_rows(rows, limit):
    """对 interview_log 查询结果去重（知识点优先、题目兜底），返回 [{'question','knowledge_point'}]。"""
    seen = set()
    result = []
    for r in rows:
        q = (r[0] or '').strip()
        kp = (r[1] or '').strip()
        key = kp or q
        if q and key not in seen:
            seen.add(key)
            result.append({'question': q, 'knowledge_point': kp})
        if len(result) >= limit:
            break
    return result


def get_mastered_interview_questions(limit: int = 60, db_path: Optional[str] = None) -> List[Dict]:
    """读取面试中已答对的题（correct=1），用于出题时避开已掌握的知识点。"""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT question, knowledge_point FROM interview_log WHERE correct=1 AND question IS NOT NULL AND question != '' ORDER BY id DESC LIMIT ?", (limit * 2,))
    rows = cur.fetchall()
    conn.close()
    return _dedup_interview_rows(rows, limit)


def get_failed_interview_questions(limit: int = 60, db_path: Optional[str] = None) -> List[Dict]:
    """读取面试中已答错的题（correct=0），用于下次换个问法重新考察。"""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT question, knowledge_point FROM interview_log WHERE correct=0 AND question IS NOT NULL AND question != '' ORDER BY id DESC LIMIT ?", (limit * 2,))
    rows = cur.fetchall()
    conn.close()
    return _dedup_interview_rows(rows, limit)


def list_interview_history(limit: int = 10000, db_path: Optional[str] = None) -> List[Dict]:
    """读取模拟面试历史记录（题目、得分、对错、知识点、难度、时间等），按最近优先。"""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('''SELECT id, question, topic, score, user_answer, correct, knowledge_point, reference, difficulty, created_at
                   FROM interview_log
                   WHERE question IS NOT NULL AND question != ''
                   ORDER BY id DESC LIMIT ?''', (limit,))
    rows = cur.fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            'id': r[0],
            'question': r[1] or '',
            'topic': r[2] or '',
            'score': r[3],
            'user_answer': r[4] or '',
            'correct': bool(r[5]),
            'knowledge_point': r[6] or '',
            'reference': r[7] or '',
            'difficulty': r[8] or '',
            'created_at': r[9] or '',
        })
    return result


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


def get_weaknesses(db_path: Optional[str] = None) -> List[Dict]:
    """读取画像中的薄弱点列表，每项 {'tag': str, 'streak': int}。"""
    profile = get_profile(db_path)
    if not profile or not profile.get('weaknesses'):
        return []
    try:
        val = json.loads(profile['weaknesses'])
        if isinstance(val, list):
            return [w for w in val if isinstance(w, dict) and str(w.get('tag') or '').strip()]
    except Exception:
        return []
    return []


def set_weaknesses(weaknesses: List[Dict], db_path: Optional[str] = None):
    """覆盖写入画像最新一行的薄弱点（JSON 数组）。"""
    if db_path is None:
        db_path = DEFAULT_DB
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    data = json.dumps(weaknesses, ensure_ascii=False)
    cur.execute('SELECT id FROM profiles ORDER BY id DESC LIMIT 1')
    r = cur.fetchone()
    if r:
        cur.execute('UPDATE profiles SET weaknesses=?, updated_at=? WHERE id=?', (data, datetime.utcnow().isoformat(), r[0]))
    conn.commit()
    conn.close()


def add_weakness_tags(tags: List[str], db_path: Optional[str] = None):
    """把新薄弱点标签合并进画像（已存在则忽略，streak 从 0 开始）。"""
    tags = [str(t).strip() for t in tags if str(t).strip()]
    if not tags:
        return
    current = get_weaknesses(db_path)
    existing = {str(w.get('tag')): w for w in current}
    for t in tags:
        if t not in existing:
            current.append({'tag': t, 'streak': 0})
            existing[t] = {'tag': t, 'streak': 0}
    set_weaknesses(current, db_path)


def bump_weakness_streak(tag: str, correct: bool, db_path: Optional[str] = None, clear_threshold: int = 2) -> bool:
    """薄弱点连续答对计数：答对 streak+1（达阈值消除），答错归零。返回是否消除。"""
    tag = (tag or '').strip()
    if not tag:
        return False
    current = get_weaknesses(db_path)
    removed = False
    new_list = []
    for w in current:
        if str(w.get('tag') or '').strip() == tag:
            if correct:
                streak = int(w.get('streak') or 0) + 1
                if streak >= clear_threshold:
                    removed = True
                    continue
                w['streak'] = streak
            else:
                w['streak'] = 0
        new_list.append(w)
    set_weaknesses(new_list, db_path)
    return removed


def record_weakness_question(tag: str, question: str, answer: str, qtype: Optional[str], correct: bool, db_path: Optional[str] = None):
    """记录一道围绕薄弱点出的题（含题型与对错），供后续出题扫描去重。"""
    tag = (tag or '').strip()
    if not tag:
        return
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('INSERT INTO weakness_history (weakness_tag, question, answer, qtype, correct, created_at) VALUES (?,?,?,?,?,?)',
                (tag, question, answer, qtype or '', 1 if correct else 0, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def get_weakness_history(limit: int = 20, db_path: Optional[str] = None) -> List[Dict]:
    """读取最近的薄弱点出题历史（按最近优先），供 AI 出题时扫描避免重复。"""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute('SELECT weakness_tag, question, answer, qtype, correct FROM weakness_history ORDER BY id DESC LIMIT ?', (limit,))
    rows = cur.fetchall()
    conn.close()
    return [{'tag': r[0], 'question': r[1], 'answer': r[2], 'qtype': r[3], 'correct': bool(r[4])} for r in rows]

