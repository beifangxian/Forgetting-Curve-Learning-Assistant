import argparse
import json
import os
from . import db, scheduler, llm, notes, interview
from datetime import date
import sys

DEFAULT_DB = None  # db.init_db will use default

def add_cmd(args):
    db.init_db(args.db)
    tags = args.tags.split(',') if args.tags else []

    # AI 出题模式：用户只给主题，大模型出题 + 批改（两层）
    if args.topic:
        if not llm.is_configured():
            print('错误：--topic 需要配置 LLM。请设置 MNEMOSYNE_LLM_API_KEY 或写入 config.json。')
            return 1
        try:
            question, answer = llm.generate_card(args.topic)
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
        db.add_card(question, answer, [], [], tags, args.db)
        print('\n已添加卡片（问题 + 参考答案）。')
        return 0

    # 手动模式：直接给问答
    if not args.q or not args.a:
        print('错误：请提供 --q 和 --a 手动添加，或用 --topic 让 AI 出题。')
        return 1
    examples = args.example or []
    files = args.file or []
    db.add_card(args.q, args.a, examples, files, tags, args.db)
    print('Added card.')
    return 0

def import_cmd(args):
    tags = args.tags.split(',') if args.tags else []
    count = notes.import_markdown_file(args.file, tags, args.db)
    print('Imported {0} card(s) from {1}'.format(count, args.file))


def sync_cmd(args):
    tags = args.tags.split(',') if args.tags else []
    updated, added = notes.sync_markdown_file(args.file, tags, args.db)
    print('Synced {0}: {1} updated, {2} added'.format(args.file, updated, added))
    return 0


def list_cmd(args):
    db.init_db(args.db)
    cards = db.list_cards(args.db)
    for c in cards:
        print(f"{c['id']}: {c['question']}  next: {c['next_review']}  ease:{c['ease']}")

def _ask_quality():
    while True:
        try:
            q = int(input('Quality (0-5): '))
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
    rows = db.get_due_cards(date.today(), args.db)
    if not rows:
        print('No cards due today.')
        return
    total = len(rows)
    use_llm = (not args.no_llm) and llm.is_configured()
    profile = db.get_profile(args.db)
    print('\n=== 开始复习：共 {0} 题 ==='.format(total))

    def run_choice(question, answer):
        """选择题轮次：AI 出单选题并判对错。返回 quality，失败返回 None。"""
        try:
            choice = llm.generate_choice_question(question, answer)
        except Exception as e:
            print('[AI 出选择题失败] ' + str(e))
            return None
        if not choice:
            return None
        print('\n[AI 选择题] ' + choice['question'])
        for i, opt in enumerate(choice['options']):
            print('  {0}. {1}'.format(chr(ord('A') + i), opt))
        user_choice = input('你的选择（A/B/C/D）：').strip().upper()
        if not user_choice:
            print('未作答，按未掌握处理。')
            return 0
        if user_choice == choice['correct']:
            print('回答正确！')
            return 5
        ci = ord(choice['correct']) - ord('A')
        correct_text = choice['options'][ci] if 0 <= ci < len(choice['options']) else choice['correct']
        print('回答错误，正确答案是 {0}. {1}'.format(choice['correct'], correct_text))
        return 0

    def run_fill(question, answer):
        """填空题轮次：AI 出填空题并判分。返回 quality，失败返回 None。"""
        try:
            fb = llm.generate_fill_blank_question(question, answer)
        except Exception as e:
            print('[AI 出填空题失败] ' + str(e))
            return None
        if not fb:
            return None
        print('\n[AI 填空题] ' + fb['question'])
        user_answer = input('你的答案：').strip()
        if not user_answer:
            print('未作答，按未掌握处理。')
            return 0
        try:
            score, feedback = llm.evaluate_answer(question, fb['answer'], user_answer)
        except Exception as e:
            print('[AI 判分失败] ' + str(e))
            score, feedback = None, None
        if score is not None:
            print('AI 评分：{0}/5'.format(score))
            if feedback:
                print('反馈：' + feedback)
            return score
        print('请自评：')
        return _ask_quality()

    # 用户自选题型
    qtype = args.type
    if use_llm and not qtype:
        print('\n请选择题型：')
        print('  1. 选择（单选题）')
        print('  2. 填空')
        while True:
            sel = input('输入 1/2（回车默认选择）：').strip() or '1'
            if sel in ('1', '2'):
                qtype = {'1': 'choice', '2': 'fill'}[sel]
                break
            print('请输入 1 或 2')

    for index, r in enumerate(rows, start=1):
        card_id, question, answer, examples, files, tags, created_at, updated_at, ease, interval, repetition, next_review = r
        print('\n' + '=' * 50)
        remaining = total - index
        print('[复习进度] {0}/{1}，已完成 {2}，剩余 {3}'.format(index, total, index, remaining))
        quality = None

        if use_llm:
            if qtype == 'choice':
                quality = run_choice(question, answer)
            elif qtype == 'fill':
                quality = run_fill(question, answer)

            if quality is not None:
                print('\n参考答案：')
                print(answer)
                _print_answer_details(examples, files)

        if quality is None:
            # 本地模式：显示问题 → 看答案 → 自评
            print('\nQuestion:')
            print(question)
            input('Press Enter to reveal answer...')
            print('\nAnswer:')
            print(answer)
            _print_answer_details(examples, files)
            quality = _ask_quality()

        # 答错后的费曼复述（仅 AI 模式且确实答错时）
        feyn = None
        if use_llm and quality is not None and quality < 3:
            print('\n回答错误，请用一句话复述这个知识点：')
            feyn = input('> ').strip() or None

        # Feynman explanation
        if args.feynman and not feyn:
            print('\n请用一句话简要复述（费曼式，回车跳过）：')
            feyn = input('> ').strip() or None

        # compute new schedule using user profile (personalization)
        new_ease, new_interval, new_repetition, next_rev = scheduler.sm2_update(ease or 2.5, interval or 0, repetition or 0, quality, profile)
        db.update_card_schedule(card_id, new_ease, new_interval, new_repetition, next_rev, args.db)
        db.record_review(card_id, quality, feyn, args.db)
        print('已更新：下次复习 {0}'.format(next_rev))


def interview_cmd(args):
    db.init_db(args.db)
    if not llm.is_configured():
        print('错误：面试功能需要配置 LLM。请设置 MNEMOSYNE_LLM_API_KEY 或写入 config.json。')
        return 1
    topic = args.topic or 'mix'
    num = args.num or 6

    context = interview.collect_project_context(args.project_root)
    if not context.strip():
        print('错误：未读取到项目源码，无法进行项目面试。')
        return 1

    scope = {'c': 'C 语言', 'stm32': '嵌入式软件', 'mix': '项目源码与相关技术'}.get(topic, topic)
    print('\n=== AI 模拟面试（{0} 题，由易到难）==='.format(num))
    print('面试范围：' + scope)
    print('项目目录：' + os.path.abspath(args.project_root or os.environ.get('MNEMOSYNE_PROJECT_ROOT') or os.getcwd()))
    print('每道题请直接作答，答完由面试官点评并进入下一题。\n')

    # 跨次去重：读取历史面试问过的题，避免热门题反复出现
    past_questions = db.get_recent_interview_questions(db_path=args.db)

    # 读取候选人技能画像（用于面试出题围绕简历技能、按熟练度定难度）
    skills = None
    profile = db.get_profile(args.db)
    if profile and profile.get('skills'):
        skills = str(profile.get('skills')).strip()

    history = []
    asked_this_round = []
    for i in range(1, num + 1):
        history_text = interview.format_history(history)
        # 本次已问过的题也要纳入去重
        avoid = list(past_questions) + asked_this_round
        try:
            q = llm.generate_interview_question(context, history_text, topic, i, num, avoid, skills)
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

        history.append({
            'question': q['question'],
            'reference': q.get('reference', ''),
            'user_answer': user_answer,
            'score': score,
            'feedback': feedback or '',
        })

    if not history:
        print('本次面试未产生任何问答。')
        return 1

    # 记录本次问过的题，供下次面试去重
    db.record_interview_questions(asked_this_round, topic, args.db)

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

    return 0


def export_cmd(args):
    db.init_db(args.db)
    out = args.out or 'mnemosyne_export.json'
    db.export_db(out, args.db)
    print('Exported to {0}'.format(out))


def show_cmd(args):
    db.init_db(args.db)
    cards = db.list_cards(args.db)
    if not cards:
        print('No cards found.')
        return 0
    for card in cards:
        print('---')
        print(f"ID: {card['id']}")
        print(f"Question: {card['question']}")
        print(f"Answer: {card['answer']}")
        print(f"Examples: {card.get('examples')}")
        print(f"Tags: {card.get('tags')}")
        print(f"Next review: {card.get('next_review')}")
        print(f"Ease: {card.get('ease')}")
        print(f"Interval: {card.get('interval')}")
        print(f"Repetition: {card.get('repetition')}")
    return 0


def profile_set_cmd(args):
    db.init_db(args.db)
    db.set_profile(args.name, args.difficulty, args.study_hours, args.notes, args.skills, args.db)
    print('Profile set: name={0} difficulty={1} study_hours={2}'.format(args.name, args.difficulty, args.study_hours))


def profile_show_cmd(args):
    db.init_db(args.db)
    p = db.get_profile(args.db)
    if not p:
        print('No profile set')
        return
    print('Profile:')
    print('  id: {0}'.format(p.get('id')))
    print('  name: {0}'.format(p.get('name')))
    print('  difficulty: {0}'.format(p.get('difficulty')))
    print('  study_hours_per_day: {0}'.format(p.get('study_hours_per_day')))
    print('  notes: {0}'.format(p.get('notes')))
    if p.get('skills'):
        print('  skills:')
        for line in str(p.get('skills')).splitlines():
            if line.strip():
                print('    ' + line.strip())
    print('  updated_at: {0}'.format(p.get('updated_at')))
    s = db.get_stats(args.db)
    print('\n学习统计：')
    print('  卡片总数: {0}'.format(s['total_cards']))
    print('  今日到期: {0}'.format(s['due_cards']))
    print('  累计复习: {0} 次'.format(s['review_count']))
    print('  最近复习: {0}'.format(s['last_review'] or '暂无'))
    print('  已掌握(间隔≥21天): {0}'.format(s['mastered_cards']))


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
    p_add.add_argument('--db')
    p_add.set_defaults(func=add_cmd)

    p_import = sp.add_parser('import')
    p_import.add_argument('--file', required=True, help='path to a markdown (.md) note file')
    p_import.add_argument('--tags')
    p_import.add_argument('--db')
    p_import.set_defaults(func=import_cmd)

    p_sync = sp.add_parser('sync')
    p_sync.add_argument('--file', required=True, help='path to a markdown (.md) note file')
    p_sync.add_argument('--tags')
    p_sync.add_argument('--db')
    p_sync.set_defaults(func=sync_cmd)

    p_list = sp.add_parser('list')
    p_list.add_argument('--db')
    p_list.set_defaults(func=list_cmd)

    p_review = sp.add_parser('review')
    p_review.add_argument('--db')
    p_review.add_argument('--feynman', action='store_true', help='prompt for Feynman explanation')
    p_review.add_argument('--no-llm', action='store_true', help='disable LLM and use local interactive review')
    p_review.add_argument('--type', choices=['choice', 'fill'], help='question type: choice / fill (default: interactive selection)')
    p_review.set_defaults(func=review_cmd)

    p_interview = sp.add_parser('interview')
    p_interview.add_argument('--num', type=int, default=6, help='面试题数（默认 6）')
    p_interview.add_argument('--topic', choices=['c', 'stm32', 'mix'], default='mix', help='面试范围（默认 mix）')
    p_interview.add_argument('--project-root', help='源码目录；也可设置 MNEMOSYNE_PROJECT_ROOT')
    p_interview.add_argument('--db')
    p_interview.set_defaults(func=interview_cmd)

    p_export = sp.add_parser('export')
    p_export.add_argument('--db')
    p_export.add_argument('--out')
    p_export.set_defaults(func=export_cmd)

    p_show = sp.add_parser('show')
    p_show.add_argument('--db')
    p_show.set_defaults(func=show_cmd)

    # profile subcommands
    p_profile = sp.add_parser('profile')
    p_profile_sub = p_profile.add_subparsers(dest='profile_cmd')
    p_profile_set = p_profile_sub.add_parser('set')
    p_profile_set.add_argument('--name', required=True)
    p_profile_set.add_argument('--difficulty', choices=['easy','normal','hard'], default='normal')
    p_profile_set.add_argument('--study-hours', type=float, default=1.0)
    p_profile_set.add_argument('--notes')
    p_profile_set.add_argument('--skills', help='技能画像，多行/分号分隔，可标注熟练度（用于面试出题）')
    p_profile_set.add_argument('--db')
    p_profile_set.set_defaults(func=profile_set_cmd)

    p_profile_show = p_profile_sub.add_parser('show')
    p_profile_show.add_argument('--db')
    p_profile_show.set_defaults(func=profile_show_cmd)

    return p


def main(argv=None):
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
