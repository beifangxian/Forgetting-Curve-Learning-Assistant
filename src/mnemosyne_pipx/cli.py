import argparse
import json
from . import db, scheduler, llm, notes
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
    use_llm = (not args.no_llm) and llm.is_configured()
    profile = db.get_profile(args.db)

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

    for r in rows:
        card_id, question, answer, examples, files, tags, created_at, updated_at, ease, interval, repetition, next_review = r
        print('\n' + '=' * 50)
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
    db.set_profile(args.name, args.difficulty, args.study_hours, args.notes, args.db)
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
