import argparse
import json
import os
import sys
import unicodedata
from . import db, scheduler, llm, notes, interview
from datetime import date

DEFAULT_DB = None  # db.init_db will use default

def add_cmd(args):
    db.init_db(args.db)
    tags = args.tags.split(',') if args.tags else []
    subject = getattr(args, 'subject', None)
    direction = getattr(args, 'direction', None)

    # AI 出题模式：用户只给主题，大模型出题 + 批改（两层）
    if args.topic:
        if not llm.is_configured():
            print('错误：--topic 需要配置 LLM。请设置 MNEMOSYNE_LLM_API_KEY 或写入 config.json。')
            return 1
        if not direction:
            direction = _choose_direction(db, subject, args.db)
        try:
            question, answer = llm.generate_card(args.topic, direction)
        except Exception as e:
            print('[AI 出题失败] ' + str(e))
            return 1

        print('\n[第一层] AI 出题：')
        print(question)
        user_answer = input('你的回答：').strip()

        # 第二层：批改
        if user_answer:
            try:
                score, feedback = llm.evaluate_answer(question, answer, user_answer)
            except Exception as e:
                print('[AI 批改失败] ' + str(e))
                score, feedback = None, None
            if score is not None:
                verdict = '正确' if score >= 3 else '错误'
                print('\n[第二层] AI 批改：{0}（{1}/5）'.format(verdict, score))
                if feedback:
                    print('反馈：' + feedback)
        else:
            print('未作答，跳过批改。')

        print('\n参考答案：')
        print(answer)
        tags.append('topic:' + args.topic)
        db.add_card(question, answer, [], [], tags, subject, direction, args.db)
        print('\n已添加卡片（问题 + 参考答案）。')
        if direction:
            print('已归入方向：{0}'.format(direction))
        return 0

    # 手动模式：直接给问答
    if not args.q or not args.a:
        print('错误：请提供 --q 和 --a 手动添加，或用 --topic 让 AI 出题。')
        return 1
    examples = args.example or []
    files = args.file or []
    db.add_card(args.q, args.a, examples, files, tags, subject, direction, args.db)
    print('Added card.')
    return 0

KNOWN_SUBJECTS = ('英语', '嵌入式', '数学')
EXCLUDED_DIRECTIONS = ('笔试题',)


def _infer_subject(path):
    """从笔记文件路径推断学科分区名（如 Makedown/嵌入式/编程语言/C/x.md → 嵌入式）。"""
    if not path:
        return None
    parts = [p for p in os.path.abspath(path).split(os.sep) if p]
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] in KNOWN_SUBJECTS:
            return parts[i]
    parent = os.path.basename(os.path.dirname(os.path.abspath(path)))
    if parent and parent not in ('.', '', os.sep):
        return parent
    return None


def _infer_direction(path, subject=None):
    """从笔记文件路径推断方向名（学科分区下的直接子目录，如 编程语言 / MCU）。"""
    if not path or not subject:
        return None
    parts = [p for p in os.path.abspath(path).split(os.sep) if p]
    idx = -1
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == subject:
            idx = i
            break
    if idx == -1:
        return None
    for j in range(idx + 1, len(parts)):
        name = parts[j]
        if j < len(parts) - 1:
            if name in EXCLUDED_DIRECTIONS:
                return None
            return name
        break
    return None


def _choose_direction(db, subject, db_path):
    """交互式选择方向。返回方向名或 None（全部/不限定）。"""
    directions = db.list_directions(subject, db_path)
    if not directions:
        return None
    print('\n请选择方向：')
    print('  0. 全部')
    for i, d in enumerate(directions, start=1):
        print('  {0}. {1}'.format(i, d))
    sel = input('输入编号（回车=全部）：').strip() or '0'
    try:
        idx = int(sel)
        if 1 <= idx <= len(directions):
            return directions[idx - 1]
    except ValueError:
        pass
    return None


def import_cmd(args):
    db.init_db(args.db)
    tags = args.tags.split(',') if args.tags else []
    subject = getattr(args, 'subject', None) or _infer_subject(args.file)
    direction = getattr(args, 'direction', None) or _infer_direction(args.file, subject)
    count = notes.import_markdown_file(args.file, tags, subject, direction, args.db)
    print('Imported {0} card(s) from {1}'.format(count, args.file))
    if subject:
        print('已归入分区：{0}'.format(subject))
    if direction:
        print('已归入方向：{0}'.format(direction))
    return 0


def sync_cmd(args):
    db.init_db(args.db)
    tags = args.tags.split(',') if args.tags else []
    subject = getattr(args, 'subject', None) or _infer_subject(args.file)
    direction = getattr(args, 'direction', None) or _infer_direction(args.file, subject)
    updated, added = notes.sync_markdown_file(args.file, tags, subject, direction, args.db)
    print('Synced {0}: {1} updated, {2} added'.format(args.file, updated, added))
    if subject:
        print('已归入分区：{0}'.format(subject))
    if direction:
        print('已归入方向：{0}'.format(direction))
    return 0


def list_cmd(args):
    db.init_db(args.db)
    cards = db.list_cards(args.db, getattr(args, 'subject', None), getattr(args, 'direction', None))
    for c in cards:
        print(f"{c['id']}: {c['question']}  next: {c['next_review']}  ease:{c['ease']}")

class QuitReview(Exception):
    """用户输入 #quit 时抛出，提前结束本次复习。"""


def _ask_quality():
    while True:
        raw = input('Quality (0-5): ').strip()
        if raw == '#quit':
            raise QuitReview()
        try:
            q = int(raw)
            if 0 <= q <= 5:
                return q
        except Exception:
            pass
        print('请输入 0-5 的整数')


def _print_answer_details(examples, files):
    if examples:
        try:
            exs = json.loads(examples)
            if exs:
                print('\nExamples:')
                for e in exs:
                    print(' -', e)
        except Exception:
            pass
    if files:
        try:
            fls = json.loads(files)
            if fls:
                print('\nFiles:')
                for f in fls:
                    print(' -', f)
        except Exception:
            pass


def review_cmd(args):
    db.init_db(args.db)
    subject = getattr(args, 'subject', None)
    direction = getattr(args, 'direction', None)
    if not direction:
        direction = _choose_direction(db, subject, args.db)
    rows = db.get_due_cards(date.today(), args.db, subject, direction)
    if not rows:
        if subject or direction:
            scope = ' / '.join([p for p in (subject, direction) if p])
            print('范围「{0}」今日无到期卡片。'.format(scope))
        else:
            print('No cards due today.')
        return
    total = len(rows)
    use_llm = (not args.no_llm) and llm.is_configured()
    ai_failures = 0
    profile = db.get_profile(args.db)
    weakness_tags = [w['tag'] for w in db.get_weaknesses(args.db)]
    if weakness_tags:
        print('\n[画像] 当前薄弱点：{0}'.format('、'.join(weakness_tags)))
    print('\n=== 开始复习：共 {0} 题 ==='.format(total))

    # 本次复习统计
    correct_count = 0
    wrong_count = 0
    wrong_items = []  # 答错题目 {'question','answer'}

    def run_choice(question, answer):
        """选择题轮次：AI 出单选题并判对错。返回 (quality, weakness_tag)，失败返回 (None, None)。"""
        try:
            hist = db.get_weakness_history(db_path=args.db)
            choice = llm.generate_choice_question(question, answer, weakness_tags, hist)
        except Exception as e:
            print('[AI 出选择题失败] ' + str(e))
            return None, None
        if not choice:
            return None, None
        print('\n[AI 选择题] ' + choice['question'])
        for i, opt in enumerate(choice['options']):
            print('  {0}. {1}'.format(chr(ord('A') + i), opt))
        raw_choice = input('你的选择（A/B/C/D）：').strip()
        if raw_choice == '#quit':
            raise QuitReview()
        user_choice = raw_choice.upper()
        if not user_choice:
            print('未作答，按未掌握处理。')
            return 0, choice.get('weakness_tag')
        if user_choice == choice['correct']:
            print('回答正确！')
            return 5, choice.get('weakness_tag')
        ci = ord(choice['correct']) - ord('A')
        correct_text = choice['options'][ci] if 0 <= ci < len(choice['options']) else choice['correct']
        print('回答错误，正确答案是 {0}. {1}'.format(choice['correct'], correct_text))
        return 0, choice.get('weakness_tag')

    def run_fill(question, answer):
        """填空题轮次：AI 出填空题并判分。返回 (quality, weakness_tag)，失败返回 (None, None)。"""
        try:
            hist = db.get_weakness_history(db_path=args.db)
            fb = llm.generate_fill_blank_question(question, answer, weakness_tags, hist)
        except Exception as e:
            print('[AI 出填空题失败] ' + str(e))
            return None, None
        if not fb:
            return None, None
        print('\n[AI 填空题] ' + fb['question'])
        user_answer = input('你的答案：').strip()
        if user_answer == '#quit':
            raise QuitReview()
        if not user_answer:
            print('未作答，按未掌握处理。')
            return 0, fb.get('weakness_tag')
        try:
            score, feedback = llm.evaluate_answer(question, fb['answer'], user_answer)
        except Exception as e:
            print('[AI 判分失败] ' + str(e))
            score, feedback = None, None
        if score is not None:
            print('AI 评分：{0}/5'.format(score))
            if feedback:
                print('反馈：' + feedback)
            return score, fb.get('weakness_tag')
        print('请自评：')
        return _ask_quality(), fb.get('weakness_tag')

    # 用户自选题型
    qtype = args.type
    if use_llm and not qtype:
        print('\n请选择题型：')
        print('  1. 选择（单选题）')
        print('  2. 填空')
        while True:
            sel = input('输入 1/2（回车默认选择）：').strip() or '1'
            if sel == '#quit':
                print('已退出今日复习。')
                return
            if sel in ('1', '2'):
                qtype = {'1': 'choice', '2': 'fill'}[sel]
                break
            print('请输入 1 或 2')

    try:
        for index, r in enumerate(rows, start=1):
            card_id, question, answer, examples, files, tags, subject, direction, created_at, updated_at, ease, interval, repetition, next_review = r
            print('\n' + '=' * 50)
            remaining = total - index
            print('[复习进度] {0}/{1}，已完成 {2}，剩余 {3}'.format(index, total, index - 1, remaining))
            quality = None
            weakness_tag = None

            if use_llm:
                if qtype == 'choice':
                    quality, weakness_tag = run_choice(question, answer)
                elif qtype == 'fill':
                    quality, weakness_tag = run_fill(question, answer)

                if quality is not None:
                    ai_failures = 0
                    print('\n参考答案：')
                    print(answer)
                    _print_answer_details(examples, files)
                else:
                    ai_failures += 1
                    if ai_failures >= 3:
                        use_llm = False
                        print('\n[提示] AI 服务连续失败，剩余题目改用本地模式（回车看答案 → 自评 0-5）。')
                    else:
                        print('[提示] 本题 AI 出题失败，改用本地模式作答。')

            if quality is None:
                # 本地模式：显示问题 → 看答案 → 自评
                print('\nQuestion:')
                print(question)
                raw = input('Press Enter to reveal answer...').strip()
                if raw == '#quit':
                    raise QuitReview()
                print('\nAnswer:')
                print(answer)
                _print_answer_details(examples, files)
                quality = _ask_quality()

            # 统计对错，并处理薄弱点连续答对计数
            if quality >= 3:
                correct_count += 1
                if weakness_tag:
                    removed = db.bump_weakness_streak(weakness_tag, True, args.db)
                    if removed:
                        weakness_tags = [t for t in weakness_tags if t != weakness_tag]
                        print('[薄弱点] 「{0}」连续答对，已从画像移除。'.format(weakness_tag))
            else:
                wrong_count += 1
                wrong_items.append({'question': question, 'answer': answer})
                if weakness_tag:
                    db.bump_weakness_streak(weakness_tag, False, args.db)

            # 记录薄弱点出题历史（AI 结合薄弱点出的题）
            if weakness_tag:
                db.record_weakness_question(weakness_tag, question, answer, qtype, quality >= 3, args.db)

            # 答错后的费曼复述（仅 AI 模式且确实答错时）
            feyn = None
            if use_llm and quality < 3:
                print('\n回答错误，请用一句话复述这个知识点：')
                raw = input('> ').strip()
                if raw == '#quit':
                    raise QuitReview()
                feyn = raw or None

            # Feynman explanation
            if args.feynman and not feyn:
                print('\n请用一句话简要复述（费曼式，回车跳过）：')
                raw = input('> ').strip()
                if raw == '#quit':
                    raise QuitReview()
                feyn = raw or None

            # compute new schedule using user profile (personalization)
            new_ease, new_interval, new_repetition, next_rev = scheduler.sm2_update(ease or 2.5, interval or 0, repetition or 0, quality, profile)
            db.update_card_schedule(card_id, new_ease, new_interval, new_repetition, next_rev, args.db)
            db.record_review(card_id, quality, feyn, args.db)
            print('已更新：下次复习 {0}'.format(next_rev))
    except QuitReview:
        print('\n已退出今日复习，已完成的题目进度已保存。')
    finally:
        # 复习结束总结：答对/答错统计 + 提炼薄弱点标签写入画像
        print('\n' + '=' * 50)
        if correct_count + wrong_count == 0:
            print('本次未作答，已退出复习。')
        else:
            print('本次复习总结')
            print('答对：{0} 题，答错：{1} 题'.format(correct_count, wrong_count))
            if wrong_items:
                tags = []
                if llm.is_configured():
                    try:
                        tags = llm.extract_weakness_tags(wrong_items)
                    except Exception as e:
                        print('[提炼薄弱点失败] ' + str(e))
                if tags:
                    db.add_weakness_tags(tags, args.db)
                    print('已更新薄弱点标签：{0}'.format('、'.join(tags)))
                    print('下次复习 AI 会围绕这些薄弱点自然结合出题强化，连续答对将自动消除。')
                else:
                    print('（未能提炼薄弱点标签。）')
            else:
                print('全部答对，无新增薄弱点。')


def interview_cmd(args):
    db.init_db(args.db)
    if not llm.is_configured():
        print('错误：面试功能需要配置 LLM。请设置 MNEMOSYNE_LLM_API_KEY 或写入 config.json。')
        return 1
    topic = args.topic or 'mix'
    num = args.num or 6

    profile = db.get_profile(args.db)
    projects = str(profile.get('projects') or '').strip() if profile else ''
    skills = str(profile.get('skills') or '').strip() if profile else ''
    if not projects and not skills:
        print('错误：画像中暂无项目经验或专业技能。请先设置画像：')
        print('  mnemosyne profile set --name 姓名 --projects "项目经验" --skills "专业技能"')
        return 1

    scope = {'c': 'C 语言', 'stm32': '嵌入式软件', 'mix': '项目经验与专业技能'}.get(topic, topic)
    print('\n=== AI 模拟面试（{0} 题，由易到难）==='.format(num))
    print('面试范围：' + scope)
    print('出题依据：画像中的项目经验 + 专业技能')
    print('每道题请直接作答，答完由面试官点评并进入下一题。\n')

    # 跨次去重：读取历史面试问过的题，避免热门题反复出现
    past_questions = db.get_recent_interview_questions(db_path=args.db)
    # 跨次出题策略：已答对的题不再问，答错的题下次换个问法再考
    mastered = db.get_mastered_interview_questions(db_path=args.db)
    failed = db.get_failed_interview_questions(db_path=args.db)

    history = []
    asked_this_round = []
    for i in range(1, num + 1):
        history_text = interview.format_history(history)
        # 本次已问过的题也要纳入去重
        avoid = list(past_questions) + asked_this_round
        try:
            q = llm.generate_interview_question(projects, history_text, topic, i, num, avoid, skills, mastered=mastered, failed=failed)
        except Exception as e:
            print('[面试官出题失败] ' + str(e))
            break
        if not q:
            print('[面试官出题失败] 请稍后重试。')
            break
        asked_this_round.append(q['question'])

        diff_label = {'easy': '基础', 'medium': '进阶', 'hard': '深入'}.get(q.get('difficulty'), '')
        print('\n[第 {0}/{1} 题]{2}'.format(i, num, ('（' + diff_label + '）') if diff_label else ''))
        print(q['question'])
        user_answer = input('你的回答：').strip()
        if not user_answer:
            user_answer = '（未作答）'

        score, feedback = None, None
        try:
            score, feedback = llm.evaluate_interview_answer(q['question'], q.get('reference', ''), user_answer)
        except Exception as e:
            print('[点评失败] ' + str(e))
        if score is None:
            score = 0
        print('面试官点评（{0}/5）：{1}'.format(score, feedback or ''))
        # 即时展示本题参考答案，帮助当场查漏补缺
        reference = q.get('reference', '')
        if reference:
            print('参考答案：')
            print(reference)

        # 记录本题答题结果：答对的题下次不再问，答错的题下次换个问法再考
        try:
            db.record_interview_result(
                question=q['question'],
                topic=topic,
                score=score,
                user_answer=user_answer,
                reference=q.get('reference', ''),
                difficulty=q.get('difficulty', ''),
                correct=(score >= 3),
                knowledge_point=q.get('knowledge_point') or '',
                db_path=args.db,
            )
        except Exception as e:
            print('[记录面试结果失败] ' + str(e))

        history.append({
            'question': q['question'],
            'reference': q.get('reference', ''),
            'user_answer': user_answer,
            'score': score,
            'feedback': feedback or '',
            'difficulty': q.get('difficulty', ''),
            'knowledge_point': q.get('knowledge_point', ''),
        })

    if not history:
        print('本次面试未产生任何问答。')
        return 1

    # 每道题的答题结果已在答题过程中通过 record_interview_result 记录，这里不再重复记录，避免去重数据翻倍。

    print('\n正在生成面试评价报告...')
    try:
        report = llm.generate_interview_report(interview.format_history(history))
    except Exception as e:
        print('[生成报告失败] ' + str(e))
        report = None

    if report:
        print('\n' + '=' * 50)
        print('面试评价报告')
        print('=' * 50)
        print('总分：{0}/100'.format(report.get('total_score', '-')))
        print('总评：' + str(report.get('summary', '')))
        strengths = report.get('strengths') or []
        if strengths:
            print('\n【强项】')
            for s in strengths:
                print('  + ' + str(s))
        weaknesses = report.get('weaknesses') or []
        if weaknesses:
            print('\n【薄弱点】')
            for w in weaknesses:
                if isinstance(w, dict):
                    print('  - ' + str(w.get('topic', '')))
                else:
                    print('  - ' + str(w))
        print('\n【建议】' + str(report.get('suggestion', '')))

        # 把薄弱点匹配到复习卡库中已有的卡片，标记为今日到期，强化训练
        weaknesses = report.get('weaknesses') or []
        weaknesses = [w for w in weaknesses if isinstance(w, dict) and str(w.get('question') or '').strip()]
        if weaknesses:
            existing = db.list_cards(args.db)
            if existing:
                print('\n正在将薄弱点匹配到已有复习卡...')
                matched = llm.match_weaknesses_to_cards(weaknesses, existing)
                matched_ids = list(dict.fromkeys([cid for cid in matched if cid is not None]))
                if matched_ids:
                    n = db.mark_cards_due(matched_ids, args.db)
                    print('已将 {0} 张相关复习卡标记为今日到期，`mnemosyne review` 会调出这些卡片做强化训练。'.format(n))
                unmatched = sum(1 for cid in matched if cid is None)
                if unmatched:
                    print('另有 {0} 个薄弱点在复习卡库中未找到对应卡片，已跳过。'.format(unmatched))
            else:
                print('\n复习卡库为空，无法匹配薄弱点进行强化。')
    else:
        print('\n（未能生成报告，但面试过程已结束。）')

    # 面试结束总结：逐题回顾（含题目、你的回答、参考答案、得分）
    print('\n' + '=' * 50)
    print('逐题回顾总结（含参考答案）')
    print('=' * 50)
    for idx, h in enumerate(history, start=1):
        diff_label = _INTERVIEW_DIFF_LABEL.get(h.get('difficulty') or '', '')
        verdict = '答对' if (h.get('score') or 0) >= 3 else '答错'
        kp = h.get('knowledge_point') or ''
        head = '[第 {0} 题]'.format(idx)
        if diff_label:
            head += '（' + diff_label + '）'
        if kp:
            head += ' 知识点：' + kp
        head += ' 得分：{0}/5（{1}）'.format(h.get('score') if h.get('score') is not None else '-', verdict)
        print('\n' + head)
        print('题目：' + str(h.get('question') or ''))
        print('你的回答：' + str(h.get('user_answer') or '（未作答）'))
        ref = str(h.get('reference') or '').strip()
        if ref:
            print('参考答案：' + ref)
        fb = str(h.get('feedback') or '').strip()
        if fb:
            print('点评：' + fb)

    return 0


_INTERVIEW_TOPIC_LABEL = {'c': 'C 语言', 'stm32': '嵌入式软件', 'mix': '综合'}
_INTERVIEW_DIFF_LABEL = {'easy': '基础', 'medium': '进阶', 'hard': '深入'}


def interview_history_cmd(args):
    db.init_db(args.db)
    rows = db.list_interview_history(db_path=args.db)
    if not rows:
        print('暂无模拟面试历史记录。')
        return 0

    correct_filter = getattr(args, 'correct', 'all')
    if correct_filter == 'correct':
        rows = [r for r in rows if r['correct']]
    elif correct_filter == 'wrong':
        rows = [r for r in rows if not r['correct']]

    limit = getattr(args, 'limit', None)
    if limit and limit > 0:
        rows = rows[:limit]

    if not rows:
        print('（该筛选条件下无历史记录。）')
        return 0

    total = len(rows)
    correct_count = sum(1 for r in rows if r['correct'])
    wrong_count = total - correct_count

    print('\n=== 模拟面试历史（共 {0} 题：答对 {1}，答错 {2}）===\n'.format(total, correct_count, wrong_count))

    headers = ['ID', '知识点', '得分', '结果', '难度', '范围', '日期', '题目']
    table_rows = []
    for r in rows:
        topic_label = _INTERVIEW_TOPIC_LABEL.get(r['topic'], r['topic'] or '-')
        diff_label = _INTERVIEW_DIFF_LABEL.get(r['difficulty'], r['difficulty'] or '-')
        verdict = '答对' if r['correct'] else '答错'
        score = '{0}/5'.format(r['score']) if r['score'] is not None else '-'
        date_str = (r['created_at'] or '')[:10] or '-'
        table_rows.append([
            str(r['id']),
            r['knowledge_point'] or '-',
            score,
            verdict,
            diff_label,
            topic_label,
            date_str,
            r['question'],
        ])
    print(_render_table(headers, table_rows, max_widths=[None, None, None, None, None, None, None, 44]))

    if getattr(args, 'detail', False):
        print('\n【详情】')
        for r in rows:
            verdict = '答对' if r['correct'] else '答错'
            print('\n#{0} [{1}] {2}（{3}/5）'.format(
                r['id'], verdict, r['knowledge_point'] or '-',
                r['score'] if r['score'] is not None else '-'))
            print('题目：' + r['question'])
            print('你的回答：' + (r['user_answer'] or '（未作答）'))
            if r['reference']:
                print('参考要点：' + r['reference'])
    return 0


def export_cmd(args):
    db.init_db(args.db)
    out = args.out or 'mnemosyne_export.json'
    db.export_db(out, args.db)
    print('Exported to {0}'.format(out))


def show_cmd(args):
    db.init_db(args.db)
    cards = db.list_cards(args.db, getattr(args, 'subject', None), getattr(args, 'direction', None))
    if not cards:
        print('No cards found.')
        return 0
    for card in cards:
        print('---')
        print(f"ID: {card['id']}")
        print(f"Question: {card['question']}")
        print(f"Answer: {card['answer']}")
        print(f"Subject: {card.get('subject')}")
        print(f"Direction: {card.get('direction')}")
        print(f"Examples: {card.get('examples')}")
        print(f"Tags: {card.get('tags')}")
        print(f"Next review: {card.get('next_review')}")
        print(f"Ease: {card.get('ease')}")
        print(f"Interval: {card.get('interval')}")
        print(f"Repetition: {card.get('repetition')}")
    return 0


def profile_set_cmd(args):
    db.init_db(args.db)
    db.set_profile(args.name, args.difficulty, args.study_hours, args.notes, args.skills, getattr(args, 'projects', None), args.db)
    print('Profile set: name={0} difficulty={1} study_hours={2}'.format(args.name, args.difficulty, args.study_hours))


def _display_width(s):
    """计算字符串在终端中的显示宽度（中文等全角字符按 2 计）。"""
    w = 0
    for ch in s:
        w += 2 if unicodedata.east_asian_width(ch) in ('F', 'W') else 1
    return w


def _pad_cell(s, width):
    """按显示宽度右侧补空格到指定宽度。"""
    return s + ' ' * max(0, width - _display_width(s))


def _wrap(text, width):
    """按显示宽度折行（中文等全角字符按 2 计）。"""
    lines = []
    for raw_line in text.split('\n'):
        if _display_width(raw_line) <= width:
            lines.append(raw_line)
            continue
        cur = ''
        cur_w = 0
        for ch in raw_line:
            chw = 2 if unicodedata.east_asian_width(ch) in ('F', 'W') else 1
            if cur_w + chw > width:
                lines.append(cur)
                cur = ''
                cur_w = 0
            cur += ch
            cur_w += chw
        if cur:
            lines.append(cur)
    return lines


def _render_table(headers, rows, max_widths=None):
    """渲染 ASCII 表格。headers: List[str]，rows: List[List[str]]（单元格可含换行）。

    max_widths：每列最大显示宽度（超过则自动折行），None 表示不限制。
    """
    ncols = len(headers)
    if max_widths is None:
        max_widths = [None] * ncols

    # 预处理：对设置了 max_width 的列按显示宽度折行
    processed = []
    for row in rows:
        new_row = []
        for j, cell in enumerate(row):
            text = str(cell)
            mw = max_widths[j]
            if mw:
                wrapped = []
                for raw in text.split('\n'):
                    wrapped.extend(_wrap(raw, mw))
                new_row.append('\n'.join(wrapped))
            else:
                new_row.append(text)
        processed.append(new_row)

    cell_lines = [[cell.split('\n') for cell in row] for row in processed]
    widths = [_display_width(h) for h in headers]
    for r in cell_lines:
        for i, lines in enumerate(r):
            for ln in lines:
                widths[i] = max(widths[i], _display_width(ln))

    def border():
        return '+' + '+'.join('-' * (w + 2) for w in widths) + '+'

    def render_line(r, idx):
        parts = []
        for j in range(ncols):
            lines = r[j]
            text = lines[idx] if idx < len(lines) else ''
            parts.append(' ' + _pad_cell(text, widths[j]) + ' ')
        return '|' + '|'.join(parts) + '|'

    def render_row(r):
        n = max(len(lines) for lines in r)
        return '\n'.join(render_line(r, i) for i in range(n))

    out = [border(), render_line([[h] for h in headers], 0), border()]
    for r in cell_lines:
        out.append(render_row(r))
    out.append(border())
    return '\n'.join(out)


def _parse_sections(text):
    """把 '##标题\n内容' 解析成 [(标题, 内容)]，忽略空行。"""
    result = []
    cur_title = None
    cur_lines = []

    def flush():
        if cur_title is not None:
            result.append((cur_title, '\n'.join(cur_lines).strip()))

    for line in str(text or '').splitlines():
        if line.startswith('##'):
            flush()
            cur_title = line[2:].strip()
            cur_lines = []
        elif line.strip():
            cur_lines.append(line.strip())
    flush()
    return result


def profile_show_cmd(args):
    db.init_db(args.db)
    p = db.get_profile(args.db)
    if not p:
        print('No profile set')
        return

    print('\n【基本画像】')
    base_rows = [
        ['ID', str(p.get('id'))],
        ['姓名', str(p.get('name') or '')],
        ['难度', str(p.get('difficulty') or '')],
        ['每日学习时长(小时)', str(p.get('study_hours_per_day'))],
        ['备注', str(p.get('notes') or '')],
        ['更新时间', str(p.get('updated_at') or '')],
    ]
    print(_render_table(['字段', '值'], base_rows))

    if p.get('skills'):
        print('\n【专业技能】')
        rows = [[title, content] for title, content in _parse_sections(p.get('skills'))]
        print(_render_table(['分类', '技能'], rows))

    if p.get('projects'):
        print('\n【项目经验】')
        proj_rows = []
        for title, content in _parse_sections(p.get('projects')):
            if '|' in title:
                name, rest = title.split('|', 1)
                proj_rows.append([name.strip(), rest.strip(), content])
            else:
                proj_rows.append([title, '', content])
        print(_render_table(['项目', '说明', '描述'], proj_rows, max_widths=[None, None, 44]))

    weaknesses = db.get_weaknesses(args.db)
    if weaknesses:
        print('\n【薄弱点】（连续答对 2 次自动消除）')
        rows = [[str(w.get('tag')), '{0}/2'.format(w.get('streak') or 0)] for w in weaknesses]
        print(_render_table(['薄弱点', '连续答对'], rows))

    s = db.get_stats(args.db)
    print('\n【学习统计】')
    stat_rows = [
        ['卡片总数', str(s['total_cards'])],
        ['今日到期', str(s['due_cards'])],
        ['累计复习', '{0} 次'.format(s['review_count'])],
        ['最近复习', str(s['last_review'] or '暂无')],
        ['已掌握(间隔≥21天)', str(s['mastered_cards'])],
    ]
    print(_render_table(['指标', '值'], stat_rows))


def subject_list_cmd(args):
    db.init_db(args.db)
    subjects = db.list_subjects(args.db)
    if not subjects:
        print('暂无分区。')
        return 0
    print('学科分区：')
    for s in subjects:
        print('  {0}  卡片 {1}  今日到期 {2}'.format(s['name'], s['total_cards'], s['due_cards']))
        if s.get('description'):
            print('      ' + s['description'])
    return 0


def subject_add_cmd(args):
    db.init_db(args.db)
    db.add_subject(args.name, args.desc, args.db)
    print('已添加分区：{0}'.format(args.name))
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog='mnemosyne')
    sp = p.add_subparsers(dest='cmd')

    p_add = sp.add_parser('add')
    p_add.add_argument('--q', help='question (manual mode)')
    p_add.add_argument('--a', help='answer (manual mode)')
    p_add.add_argument('--topic', help='topic: let AI generate a question and grade your answer (requires LLM)')
    p_add.add_argument('--example', action='append')
    p_add.add_argument('--file', action='append', help='path to a file to attach (can be used multiple times)')
    p_add.add_argument('--tags')
    p_add.add_argument('--subject', help='学科分区（如 英语/嵌入式/数学）')
    p_add.add_argument('--direction', help='方向（学科下的二级分类，如 编程语言/MCU）')
    p_add.add_argument('--db')
    p_add.set_defaults(func=add_cmd)

    p_import = sp.add_parser('import')
    p_import.add_argument('--file', required=True, help='path to a markdown (.md) note file')
    p_import.add_argument('--tags')
    p_import.add_argument('--subject', help='学科分区；不填时从文件所在目录名推断')
    p_import.add_argument('--direction', help='方向；不填时从文件所在目录推断')
    p_import.add_argument('--db')
    p_import.set_defaults(func=import_cmd)

    p_sync = sp.add_parser('sync')
    p_sync.add_argument('--file', required=True, help='path to a markdown (.md) note file')
    p_sync.add_argument('--tags')
    p_sync.add_argument('--subject', help='学科分区；不填时从文件所在目录名推断')
    p_sync.add_argument('--direction', help='方向；不填时从文件所在目录推断')
    p_sync.add_argument('--db')
    p_sync.set_defaults(func=sync_cmd)

    p_list = sp.add_parser('list')
    p_list.add_argument('--subject', help='按分区筛选')
    p_list.add_argument('--direction', help='按方向筛选')
    p_list.add_argument('--db')
    p_list.set_defaults(func=list_cmd)

    p_review = sp.add_parser('review')
    p_review.add_argument('--db')
    p_review.add_argument('--subject', help='仅复习指定分区')
    p_review.add_argument('--direction', help='仅复习指定方向')
    p_review.add_argument('--feynman', action='store_true', help='prompt for Feynman explanation')
    p_review.add_argument('--no-llm', action='store_true', help='disable LLM and use local interactive review')
    p_review.add_argument('--type', choices=['choice', 'fill'], help='question type: choice / fill (default: interactive selection)')
    p_review.set_defaults(func=review_cmd)

    p_interview = sp.add_parser('interview')
    p_interview.add_argument('--num', type=int, default=6, help='面试题数（默认 6）')
    p_interview.add_argument('--topic', choices=['c', 'stm32', 'mix'], default='mix', help='面试范围（默认 mix）')
    p_interview.add_argument('--db')
    p_interview.set_defaults(func=interview_cmd)

    p_interview_sub = p_interview.add_subparsers(dest='interview_cmd')
    p_ihist = p_interview_sub.add_parser('history', help='查看模拟面试历史题目')
    p_ihist.add_argument('--db')
    p_ihist.add_argument('--correct', choices=['all', 'correct', 'wrong'], default='all', help='按对错筛选（all/correct/wrong）')
    p_ihist.add_argument('--limit', type=int, default=100, help='最多显示条数（默认 100）')
    p_ihist.add_argument('--detail', action='store_true', help='同时显示你的回答与参考要点')
    p_ihist.set_defaults(func=interview_history_cmd)

    p_export = sp.add_parser('export')
    p_export.add_argument('--db')
    p_export.add_argument('--out')
    p_export.set_defaults(func=export_cmd)

    p_show = sp.add_parser('show')
    p_show.add_argument('--subject', help='按分区筛选')
    p_show.add_argument('--direction', help='按方向筛选')
    p_show.add_argument('--db')
    p_show.set_defaults(func=show_cmd)

    # subject subcommands（学科分区：英语 / 嵌入式 / 数学 ...）
    p_subject = sp.add_parser('subject', help='学科分区管理')
    p_subject_sub = p_subject.add_subparsers(dest='subject_cmd')
    p_subject_list = p_subject_sub.add_parser('list', help='列出所有分区及统计')
    p_subject_list.add_argument('--db')
    p_subject_list.set_defaults(func=subject_list_cmd)
    p_subject_add = p_subject_sub.add_parser('add', help='新建分区')
    p_subject_add.add_argument('--name', required=True, help='分区名')
    p_subject_add.add_argument('--desc', help='分区描述')
    p_subject_add.add_argument('--db')
    p_subject_add.set_defaults(func=subject_add_cmd)

    # profile subcommands
    p_profile = sp.add_parser('profile')
    p_profile_sub = p_profile.add_subparsers(dest='profile_cmd')
    p_profile_set = p_profile_sub.add_parser('set')
    p_profile_set.add_argument('--name', required=True)
    p_profile_set.add_argument('--difficulty', choices=['easy','normal','hard'], default='normal')
    p_profile_set.add_argument('--study-hours', type=float, default=1.0)
    p_profile_set.add_argument('--notes')
    p_profile_set.add_argument('--skills', help='专业技能（多行/分号分隔，可标注熟练度，用于面试出题）')
    p_profile_set.add_argument('--projects', help='项目经验（多行文本，用于面试出题）')
    p_profile_set.add_argument('--db')
    p_profile_set.set_defaults(func=profile_set_cmd)

    p_profile_show = p_profile_sub.add_parser('show')
    p_profile_show.add_argument('--db')
    p_profile_show.set_defaults(func=profile_show_cmd)

    return p


def main(argv=None):
    # 兼容 Windows GBK 控制台：遇到无法编码的字符（如 emoji）用 ? 替代，避免打印崩溃
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')
        except Exception:
            pass
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, 'func'):
        parser.print_help()
        return 1
    return args.func(args)

if __name__ == '__main__':
    main()
