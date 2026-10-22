"""Markdown 笔记解析与导入。

笔记约定：
- `#` 一级标题 = 笔记主题（作为标签写入卡片）
- `##` 二级标题 = 知识点（作为卡片的问题）
- 二级标题之间的正文 = 答案

导入后每个 `##` 段落会成为一张复习卡片。
"""
import os
from typing import List, Optional, Dict


def parse_markdown(text: str) -> List[Dict[str, str]]:
    """将 markdown 文本按 `##` 二级标题拆分为知识点。

    返回列表，每项为 {'question': str, 'answer': str, 'topic': str}。
    topic 来自最近的 `#` 一级标题，可能为 None。
    """
    items: List[Dict[str, str]] = []
    topic: Optional[str] = None
    current_q: Optional[str] = None
    current_a: List[str] = []

    def flush():
        nonlocal current_q, current_a
        if current_q is not None:
            answer = '\n'.join(current_a).strip()
            if answer:
                items.append({'question': current_q, 'answer': answer, 'topic': topic})
        current_q = None
        current_a = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('## '):
            flush()
            current_q = stripped[3:].strip()
        elif stripped.startswith('# '):
            flush()
            topic = stripped[2:].strip()
        else:
            if current_q is not None:
                current_a.append(line)

    flush()
    return items


def import_markdown_file(path: str, tags: Optional[List[str]] = None, subject: Optional[str] = None, direction: Optional[str] = None, db_path: Optional[str] = None) -> int:
    """读取 md 文件并导入数据库，返回导入的卡片数。

    subject：学科分区（如「英语」「嵌入式」「数学」），为 None 时不归入任何分区。
    direction：方向（学科下的二级分类，如「编程语言」「MCU」），为 None 时不标记。
    """
    from . import db

    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()

    items = parse_markdown(text)
    db.init_db(db_path)

    source_tag = 'md:' + os.path.splitext(os.path.basename(path))[0]
    count = 0
    for it in items:
        card_tags = [t for t in (tags or [])]
        if it.get('topic'):
            card_tags.append(it['topic'])
        card_tags.append(source_tag)
        db.add_card(it['question'], it['answer'], [], [], card_tags, subject, direction, db_path)
        count += 1
    return count


def sync_markdown_file(path: str, tags: Optional[List[str]] = None, subject: Optional[str] = None, direction: Optional[str] = None, db_path: Optional[str] = None):
    """同步 md 文件：更新已有知识点卡（保留学习进度），新增多出的知识点。

    匹配规则：来源标签 md:<文件名> 且 `##` 标题文字完全一致。
    返回 (updated, added) 两个计数。
    """
    from . import db

    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()

    items = parse_markdown(text)
    db.init_db(db_path)

    source_tag = 'md:' + os.path.splitext(os.path.basename(path))[0]

    existing = db.get_cards_by_tag(source_tag, db_path)
    by_question = {}
    for c in existing:
        by_question.setdefault(c['question'], c)

    updated = 0
    added = 0
    for it in items:
        card_tags = [t for t in (tags or [])]
        if it.get('topic'):
            card_tags.append(it['topic'])
        card_tags.append(source_tag)
        q = it['question']
        if q in by_question:
            db.update_card(by_question[q]['id'], q, it['answer'], [], [], card_tags, subject, direction, db_path)
            updated += 1
        else:
            db.add_card(q, it['answer'], [], [], card_tags, subject, direction, db_path)
            added += 1
    return updated, added
