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

DEFAULT_API_URL = 'https://api.deepseek.com/v1/chat/completions'
DEFAULT_MODEL = 'deepseek-chat'
CONFIG_PATH = os.path.join('D:\\bfx\\Mnemosyne_data', 'config.json')

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
