"""可选的 LLM 集成：用于复习时出题与判分。

配置优先级：环境变量 > 配置文件（D:\\bfx\\Mnemosyne_data\\config.json）。

配置文件支持两种写法（平铺或包一层 llm）：
    {"api_key": "...", "api_url": "...", "model": "..."}
    {"llm": {"api_key": "...", "api_url": "...", "model": "..."}}

环境变量：
    MNEMOSYNE_LLM_API_KEY
    MNEMOSYNE_LLM_API_URL
    MNEMOSYNE_LLM_MODEL

未配置 API key 时 is_configured() 返回 False，复习会退回本地交互模式。
"""
import os
import json
import re
import urllib.request
from typing import List, Optional, Tuple, Dict, Any
from .paths import get_data_dir

DEFAULT_API_URL = 'https://api.deepseek.com/v1/chat/completions'
DEFAULT_MODEL = 'deepseek-chat'
CONFIG_PATH = os.path.join(get_data_dir(), 'config.json')

_ENV_KEYS = {
    'api_key': 'MNEMOSYNE_LLM_API_KEY',
    'api_url': 'MNEMOSYNE_LLM_API_URL',
    'model': 'MNEMOSYNE_LLM_MODEL',
}


def load_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                llm_section = data.get('llm')
                if isinstance(llm_section, dict):
                    cfg.update(llm_section)
                else:
                    for k in ('api_key', 'api_url', 'model'):
                        if k in data:
                            cfg[k] = data[k]
    except Exception:
        pass
    for k, env in _ENV_KEYS.items():
        v = os.environ.get(env)
        if v:
            cfg[k] = v
    return cfg


def is_configured() -> bool:
    return bool(load_config().get('api_key'))


def chat(messages: List[Dict[str, str]], max_tokens: int = 256, temperature: float = 0.7) -> str:
    """调用 OpenAI 兼容的 chat completions 接口，返回助手文本。"""
    cfg = load_config()
    api_key = cfg.get('api_key')
    if not api_key:
        raise RuntimeError('LLM 未配置：请设置 MNEMOSYNE_LLM_API_KEY 或写入 config.json')
    api_url = cfg.get('api_url') or DEFAULT_API_URL
    model = cfg.get('model') or DEFAULT_MODEL

    payload = {
        'model': model,
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': temperature,
        'stream': False,
    }
    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': 'Bearer ' + api_key,
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode('utf-8'))

    choices = data.get('choices') or []
    if choices:
        msg = choices[0].get('message') or {}
        content = msg.get('content')
        if content:
            return content
    return ''


def generate_question(question: str) -> str:
    """围绕知识点出一道简短的复习题。失败时退回原知识点标题。"""
    content = chat([
        {'role': 'system', 'content': '你是一名学习教练，负责根据知识点出复习题。'},
        {'role': 'user', 'content': '围绕下面这个知识点，出一道简短、具体、可以直接作答的复习题。只输出题目本身，不要任何解释或答案。\n\n知识点：' + question},
    ], max_tokens=128, temperature=0.8)
    q = (content or '').strip()
    return q or question


def generate_choice_question(question: str, answer: str) -> Optional[Dict[str, Any]]:
    """根据知识点生成一道单选题。

    返回 {'question': str, 'options': [str, ...], 'correct': str(字母 A/B/C/D)}；
    失败返回 None。
    """
    content = chat([
        {'role': 'system', 'content': '你是一名学习教练，负责出单选题。'},
        {'role': 'user', 'content': (
            '根据下面的知识点出一道单选题，给出 4 个选项（A/B/C/D），其中只有一个是正确答案。\n'
            '严格只输出 JSON，格式：{"question": "<题目>", "options": ["<选项A>", "<选项B>", "<选项C>", "<选项D>"], "correct": "<正确选项字母 A/B/C/D>"}\n\n'
            '知识点：' + question + '\n'
            '参考答案：' + answer
        )},
    ], max_tokens=256, temperature=0.8)

    if not content:
        return None
    try:
        m = re.search(r'\{.*\}', content, re.S)
        obj = json.loads(m.group(0)) if m else json.loads(content)
        q = str(obj.get('question') or '').strip()
        options = obj.get('options') or []
        if not isinstance(options, list):
            options = []
        options = [str(o).strip() for o in options if str(o).strip()]
        correct = str(obj.get('correct') or '').strip().upper()
        cm = re.search(r'[ABCD]', correct)
        if cm:
            correct = cm.group(0)
        if q and len(options) >= 2 and correct:
            return {'question': q, 'options': options, 'correct': correct}
    except Exception:
        pass
    return None


def generate_fill_blank_question(question: str, answer: str) -> Optional[Dict[str, str]]:
    """根据知识点生成一道填空题。

    返回 {'question': str(含 ____ 挖空), 'answer': str(正确答案)}；失败返回 None。
    """
    content = chat([
        {'role': 'system', 'content': '你是一名学习教练，负责出填空题。'},
        {'role': 'user', 'content': (
            '根据下面的知识点出一道填空题，把关键信息挖空（用 ____ 表示空位），并给出正确答案。\n'
            '严格只输出 JSON，格式：{"question": "<含 ____ 的题目>", "answer": "<正确答案>"}\n\n'
            '知识点：' + question + '\n'
            '参考答案：' + answer
        )},
    ], max_tokens=256, temperature=0.8)

    if not content:
        return None
    try:
        m = re.search(r'\{.*\}', content, re.S)
        obj = json.loads(m.group(0)) if m else json.loads(content)
        q = str(obj.get('question') or '').strip()
        a = str(obj.get('answer') or '').strip()
        if q and a:
            return {'question': q, 'answer': a}
    except Exception:
        pass
    return None


def generate_card(topic: str) -> Tuple[str, str]:
    """第一层：根据主题让 LLM 出题并生成标准答案。

    返回 (question, answer)；失败时退回 (topic, topic)。
    """
    content = chat([
        {'role': 'system', 'content': '你是一名学习教练，负责根据主题出题并给出标准答案。'},
        {'role': 'user', 'content': (
            '围绕下面的主题，出一道适合考察理解程度的简答题，并给出标准答案。\n'
            '严格只输出 JSON，格式：{"question": "<题目>", "answer": "<标准答案>"}\n\n'
            '主题：' + topic
        )},
    ], max_tokens=256, temperature=0.7)

    if not content:
        return topic, topic
    try:
        m = re.search(r'\{.*\}', content, re.S)
        obj = json.loads(m.group(0)) if m else json.loads(content)
        question = str(obj.get('question') or '').strip()
        answer = str(obj.get('answer') or '').strip()
        if question and answer:
            return question, answer
    except Exception:
        pass
    return topic, topic


def evaluate_answer(question: str, reference: str, user_answer: str) -> Tuple[Optional[int], Optional[str]]:
    """让 LLM 根据标准答案给学生的回答打分（0-5）。

    返回 (score, feedback)；解析失败返回 (None, None)。
    """
    content = chat([
        {'role': 'system', 'content': '你是一名学习教练，负责评判学生的回答。'},
        {'role': 'user', 'content': (
            '知识点：' + question + '\n'
            '标准答案：' + reference + '\n'
            '学生回答：' + user_answer + '\n\n'
            '请根据学生回答与标准答案的符合程度，打一个 0 到 5 的整数分，并给一句简短反馈。\n'
            '严格只输出 JSON，格式：{"score": <0-5整数>, "feedback": "<一句话>"}'
        )},
    ], max_tokens=128, temperature=0.2)

    if not content:
        return None, None
    try:
        m = re.search(r'\{.*\}', content, re.S)
        obj = json.loads(m.group(0)) if m else json.loads(content)
        score = max(0, min(5, int(obj.get('score'))))
        feedback = str(obj.get('feedback') or '')
        return score, feedback
    except Exception:
        m = re.search(r'[0-5]', content)
        if m:
            return int(m.group(0)), content.strip()
        return None, None


_TOPIC_DESC = {
    'c': 'C 语言与数据结构',
    'stm32': '嵌入式软件与微控制器',
    'mix': '项目源码涉及的综合技术',
}


def generate_interview_question(project_context: str, history_text: str, topic: str, round_no: int, total: int, past_questions: Optional[List[str]] = None, candidate_profile: Optional[str] = None, hardware_context: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """面试官基于项目源码出一道面试题，由易到难。

    past_questions：历史面试问过的题目（含本次已问过的），用于去重、避免热门题过度集中。
    candidate_profile：候选人技能画像（含熟练度），用于围绕简历技能出题并定难度。
    hardware_context：项目硬件/芯片/设备清单，用于围绕具体型号与操作逻辑出题。
    返回 {'question': str, 'reference': str, 'difficulty': 'easy|medium|hard'}；
    失败返回 None。
    """
    topic_desc = _TOPIC_DESC.get(topic, '项目相关知识')
    past_text = ''
    if past_questions:
        past_text = '\n'.join('- ' + q for q in past_questions)

    profile_block = ''
    if candidate_profile:
        profile_block = ('=== 候选人简历技能画像（围绕这些技能出题，熟练的可以问更深、掌握的问适中，不要问画像之外的技术）===\n'
                         + candidate_profile + '\n\n')

    hardware_block = ''
    if hardware_context:
        hardware_block = hardware_context + '\n\n'

    content = chat([
        {'role': 'system', 'content': '你是一名软件工程面试官。请根据提供的项目源码与候选人的技能画像出题，考察技术理解和表达能力。题目难度应由浅入深、知识点尽量多样，并符合候选人的技能水平。'},
        {'role': 'user', 'content': (
            '下面是候选人项目的源码，仅用于了解项目涉及的技术与实现，供你出题。\n'
            '请围绕「' + topic_desc + '」出一道通用技术面试题。\n'
            '要求：\n'
            '1. 题目必须是通用的技术面试题，考察原理、设计思路、方案选择、常见坑等；不要问“你代码里第几行写了什么”，不要引用具体函数名、变量名、宏名。\n'
            '2. 像真实面试官一样提问：真实面试官看不到代码，问的是“这个技术点你是怎么理解/处理的”。\n'
            '3. 候选人是一名应届生（校招），难度必须匹配应届生水平，三档定义如下：\n'
            '   easy（基础）＝单一知识点、有唯一明确答案的概念/原理/计算题，可直接作答。例：波特率计算、奇偶校验原理、I2C 基本时序、ADC 是多少位分辨率、volatile 的作用。\n'
            '   medium（进阶）＝围绕一两个明确概念的适度综合题。\n'
            '   hard（深入）＝设计权衡、边界条件、并发问题、工程经验。\n'
            '4. 难度必须严格按进度分配：前 1/3 的题只能是 easy，中间 1/3 是 medium，后 1/3 是 hard。当前是第 ' + str(round_no) + ' 题（共 ' + str(total) + ' 题），请据此确定难度。\n'
            '5. 严禁把开放式多因素设计题（如“有哪些因素会影响…你会怎么设计/处理”）标为 easy，这类题属于 medium 或 hard；easy 题必须有唯一、明确的答案。\n'
            '6. 只出一道题，不要一次问多个，不要提示答案。\n'
            '7. 同时给出该题的“技术正确要点”（通用正确知识，仅用于判分参考，不展示给候选人）。\n'
            '8. 【去重与多样性——非常重要】下面会列出“历史问过的题”。请务必换一个新的知识点出题，不要重复、不要换汤不换药地重问同一个知识点（例如已经问过 volatile，就不要再出 const/static/volatile 相关题；已问过波特率就不要再出串口时序类计算）。要尽量覆盖还没问过的技术面，保证知识点分散、问得杂一点、面广一点。\n'
            '9. 【紧扣技能画像】优先围绕候选人简历上列出的技能出题；标注“熟练”的技能可以问得更深入，标注“掌握”的问适中；不要问画像之外的技术。\n'
            '严格只输出 JSON，格式：{"question": "<题目>", "reference": "<技术正确要点>", "difficulty": "easy|medium|hard"}\n\n'
            + profile_block
            + hardware_block +
            '=== 候选人项目背景（仅作选题参考）===\n' + project_context + '\n\n'
            '=== 历史问过的题（务必避开，换新知识点）===\n' + (past_text or '（暂无）') + '\n\n'
            '=== 本次已问过的问题与候选人表现 ===\n' + (history_text or '（暂无，这是第一题）')
        )},
    ], max_tokens=512, temperature=0.9)

    if not content:
        return None
    try:
        m = re.search(r'\{.*\}', content, re.S)
        obj = json.loads(m.group(0)) if m else json.loads(content)
        q = str(obj.get('question') or '').strip()
        r = str(obj.get('reference') or '').strip()
        d = str(obj.get('difficulty') or 'easy').strip().lower()
        if d not in ('easy', 'medium', 'hard'):
            d = 'easy'
        if q:
            return {'question': q, 'reference': r, 'difficulty': d}
    except Exception:
        pass
    return None


def evaluate_interview_answer(question: str, reference: str, user_answer: str) -> Tuple[Optional[int], Optional[str]]:
    """面试官给候选人的回答打分（0-5）并点评，指出关键盲点。

    返回 (score, feedback)；解析失败返回 (None, None)。
    """
    content = chat([
        {'role': 'system', 'content': '你是一名资深嵌入式软件面试官，正在给候选人的回答打分。评分标准：可行性、逻辑联通性、知识点正确性。'},
        {'role': 'user', 'content': (
            '面试题：' + question + '\n'
            '该题技术正确要点（仅作参考，不要逐字对照）：' + reference + '\n'
            '候选人回答：' + user_answer + '\n\n'
            '请按以下三条标准给候选人的回答打一个 0 到 5 的整数分，并给一句简短点评（指出对或错、关键盲点）：\n'
            '1. 可行性：他的方案/思路是否真的可行、能否落地；\n'
            '2. 逻辑联通性：表述是否连贯、自洽，因果关系是否清楚；\n'
            '3. 知识点正确性：涉及的技术概念、原理、数值是否正确。\n'
            '注意：不要拿“标准答案”逐字对照，重点是理解是否正确、思路是否合理。\n'
            '严格只输出 JSON，格式：{"score": <0-5整数>, "feedback": "<一句话点评>"}'
        )},
    ], max_tokens=128, temperature=0.2)

    if not content:
        return None, None
    try:
        m = re.search(r'\{.*\}', content, re.S)
        obj = json.loads(m.group(0)) if m else json.loads(content)
        score = max(0, min(5, int(obj.get('score'))))
        feedback = str(obj.get('feedback') or '')
        return score, feedback
    except Exception:
        m = re.search(r'[0-5]', content)
        if m:
            return int(m.group(0)), content.strip()
        return None, None


def generate_interview_report(history_text: str) -> Optional[Dict[str, Any]]:
    """面试结束后生成评价报告。

    返回 {'total_score': int, 'summary': str, 'strengths': [str],
          'weaknesses': [{'topic': str, 'question': str, 'answer': str}],
          'suggestion': str}；失败返回 None。
    """
    content = chat([
        {'role': 'system', 'content': '你是一名资深嵌入式软件面试官，负责在面试结束后输出评价报告。'},
        {'role': 'user', 'content': (
            '下面是一场嵌入式软件面试的完整记录（题目、候选人回答、得分、点评）。\n'
            '请输出一份面试评价报告，严格只输出 JSON，不要任何多余文字。JSON 字段：\n'
            '1. total_score：总分（0-100 整数，按各题得分加权估算）；\n'
            '2. summary：一句话总评；\n'
            '3. strengths：候选人表现出色的方面（字符串数组，1-3 条）；\n'
            '4. weaknesses：候选人的薄弱点（数组，1-5 条），每项为 {"topic": "<知识点名>", "question": "<可复习的问句>", "answer": "<正确要点>"}，用于之后生成复习卡；\n'
            '5. suggestion：下一步学习建议（一句话）。\n\n'
            '=== 面试记录 ===\n' + history_text
        )},
    ], max_tokens=1024, temperature=0.4)

    if not content:
        return None
    try:
        m = re.search(r'\{.*\}', content, re.S)
        obj = json.loads(m.group(0)) if m else json.loads(content)
        total_score = int(obj.get('total_score') or 0)
        total_score = max(0, min(100, total_score))
        strengths = obj.get('strengths') or []
        if not isinstance(strengths, list):
            strengths = []
        weaknesses = obj.get('weaknesses') or []
        if not isinstance(weaknesses, list):
            weaknesses = []
        return {
            'total_score': total_score,
            'summary': str(obj.get('summary') or ''),
            'strengths': [str(s) for s in strengths],
            'weaknesses': weaknesses,
            'suggestion': str(obj.get('suggestion') or ''),
        }
    except Exception:
        pass
    return None


def match_weaknesses_to_cards(weaknesses: List[Dict[str, Any]], cards: List[Dict[str, Any]]) -> List[Optional[int]]:
    """把面试薄弱点匹配到复习卡片库中最相关的已有卡片。

    返回与 weaknesses 一一对应的列表，每项为匹配到的卡片 id（int）或 None（未匹配到）。
    """
    if not weaknesses or not cards:
        return [None] * len(weaknesses)

    card_lines = []
    for c in cards:
        q = str(c.get('question') or '').strip()
        tags = c.get('tags') or []
        tag_str = ','.join(tags) if isinstance(tags, list) else str(tags)
        card_lines.append('{0}. {1} | {2}'.format(c.get('id'), q, tag_str))
    card_text = '\n'.join(card_lines)

    weak_lines = []
    for i, w in enumerate(weaknesses):
        topic = str(w.get('topic') or '').strip()
        q = str(w.get('question') or '').strip()
        weak_lines.append('{0}. 知识点={1} 问句={2}'.format(i, topic, q))
    weak_text = '\n'.join(weak_lines)

    content = chat([
        {'role': 'system', 'content': '你负责把面试薄弱点匹配到复习卡片库中最相关的卡片。'},
        {'role': 'user', 'content': (
            '下面有一批面试中暴露的薄弱点，以及复习卡片库（每张卡有 id 和标题、标签）。\n'
            '请为每个薄弱点找出一张最相关的卡片 id（按主题/关键词匹配即可，若确实无相关卡片则返回 null）。\n'
            '严格只输出 JSON，格式：{"matches": [{"index": 0, "card_id": 3}, {"index": 1, "card_id": null}, ...]}\n\n'
            '=== 薄弱点 ===\n' + weak_text + '\n\n'
            '=== 卡片库 ===\n' + card_text
        )},
    ], max_tokens=512, temperature=0.2)

    result: List[Optional[int]] = [None] * len(weaknesses)
    if not content:
        return result
    try:
        m = re.search(r'\{.*\}', content, re.S)
        obj = json.loads(m.group(0)) if m else json.loads(content)
        matches = obj.get('matches') or []
        if isinstance(matches, list):
            for mm in matches:
                if not isinstance(mm, dict):
                    continue
                try:
                    idx = int(mm.get('index'))
                except Exception:
                    continue
                cid = mm.get('card_id')
                if cid is None:
                    continue
                try:
                    cid = int(cid)
                except Exception:
                    continue
                if 0 <= idx < len(result):
                    result[idx] = cid
    except Exception:
        pass
    return result
