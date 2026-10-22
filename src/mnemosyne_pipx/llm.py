"""可选的 LLM 集成：用于复习时出题与判分。

配置优先级：环境变量 > 配置文件（D:\\bfx\\Mnemosyne_data\\config.json）。

配置文件支持三种写法：
1. 单模型（平铺）：
    {"api_key": "...", "api_url": "...", "model": "..."}
2. 包一层 llm：
    {"llm": {"api_key": "...", "api_url": "...", "model": "..."}}
3. 多模型故障切换（推荐）：
    {"providers": [
        {"name": "deepseek", "api_key": "...", "api_url": "...", "model": "deepseek-chat"},
        {"name": "glm", "api_key": "...", "api_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "model": "glm-4-flash"}
    ]}
    providers 按顺序尝试，主服务崩溃时自动切换到下一个可用服务。

环境变量：
    MNEMOSYNE_LLM_API_KEY
    MNEMOSYNE_LLM_API_URL
    MNEMOSYNE_LLM_MODEL

未配置任何 API key 时 is_configured() 返回 False，复习会退回本地交互模式。
"""
import os
import json
import re
import time
import urllib.request
import urllib.error
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
                    for k in ('api_key', 'api_url', 'model', 'providers'):
                        if k in data:
                            cfg[k] = data[k]
    except Exception:
        pass
    for k, env in _ENV_KEYS.items():
        v = os.environ.get(env)
        if v:
            cfg[k] = v
    return cfg


def _default_provider_name(url: str, model: str) -> str:
    """根据 api_url 推断一个可读的 provider 名，用于切换提示。"""
    u = (url or '').lower()
    if 'deepseek' in u:
        return 'deepseek'
    if 'bigmodel' in u or 'zhipu' in u:
        return 'glm'
    if 'dashscope' in u or 'aliyun' in u:
        return 'qwen'
    if 'siliconflow' in u:
        return 'siliconflow'
    return model or 'llm'


def get_providers() -> List[Dict[str, str]]:
    """规范化配置为 provider 列表（按配置顺序，供故障切换）。"""
    cfg = load_config()
    providers = cfg.get('providers')
    if isinstance(providers, list):
        result = []
        for p in providers:
            if isinstance(p, dict) and p.get('api_key'):
                api_url = p.get('api_url') or DEFAULT_API_URL
                model = p.get('model') or DEFAULT_MODEL
                name = str(p.get('name') or '') or _default_provider_name(api_url, model)
                result.append({'api_key': str(p['api_key']), 'api_url': api_url, 'model': model, 'name': name})
        if result:
            return result
    key = cfg.get('api_key')
    if key:
        api_url = cfg.get('api_url') or DEFAULT_API_URL
        model = cfg.get('model') or DEFAULT_MODEL
        return [{'api_key': str(key), 'api_url': api_url, 'model': model, 'name': _default_provider_name(api_url, model)}]
    return []


def is_configured() -> bool:
    return bool(get_providers())


_active_provider = None


def _note_provider(name: str):
    """在 provider 发生切换时提示一次（避免刷屏）。"""
    global _active_provider
    label = name or 'llm'
    if label != _active_provider:
        _active_provider = label
        print('[LLM] 当前模型服务：{0}'.format(label))


def chat(messages: List[Dict[str, str]], max_tokens: int = 256, temperature: float = 0.7) -> str:
    """调用 OpenAI 兼容的 chat completions 接口，返回助手文本。

    依次尝试多个 provider（按配置顺序），主 provider 失败自动切换到备用。
    对临时性错误（429/5xx/网络中断）每个 provider 内部再自动重试，最多 3 次。
    """
    providers = get_providers()
    if not providers:
        raise RuntimeError('LLM 未配置：请设置 MNEMOSYNE_LLM_API_KEY 或写入 config.json')
    last_error = None
    for provider in providers:
        api_key = provider['api_key']
        api_url = provider.get('api_url') or DEFAULT_API_URL
        model = provider.get('model') or DEFAULT_MODEL
        name = provider.get('name') or ''
        for attempt in range(3):
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
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                # 限流或服务暂时不可用：退避后重试
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                last_error = e
                break
            except urllib.error.URLError as e:
                # 网络中断：退避后重试
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                last_error = e
                break

            choices = data.get('choices') or []
            if choices:
                msg = choices[0].get('message') or {}
                content = msg.get('content')
                if content:
                    _note_provider(name)
                    return content
            return ''

    if last_error is not None:
        raise last_error
    return ''


def generate_question(question: str) -> str:
    """围绕知识点出一道简短的复习题。失败时退回原知识点标题。"""
    content = chat([
        {'role': 'system', 'content': '你是一名学习教练，负责根据知识点出复习题。'},
        {'role': 'user', 'content': '围绕下面这个知识点，出一道简短、具体、可以直接作答的复习题。只输出题目本身，不要任何解释或答案。\n\n知识点：' + question},
    ], max_tokens=128, temperature=0.8)
    q = (content or '').strip()
    return q or question


def _weakness_prompt_block(weakness_tags: Optional[List[str]], weakness_history: Optional[List[Dict[str, Any]]]) -> str:
    """构造「薄弱点强化」出题提示块；无薄弱点时返回空串。"""
    tags = [str(t).strip() for t in (weakness_tags or []) if str(t).strip()]
    if not tags:
        return ''
    lines = []
    for h in (weakness_history or [])[:10]:
        tag = str(h.get('tag') or '').strip()
        q = str(h.get('question') or '').strip()
        if q:
            lines.append('- [{0}][{1}] {2}'.format(tag, h.get('qtype') or '题', q))
    return (
        '\n【薄弱点强化】考生当前薄弱的知识点标签：' + '、'.join(tags) + '。\n'
        '出题时，如果当前知识点能与上述某个薄弱点自然关联，请出一题“结合薄弱点”的综合题（例：薄弱点是 I2C、当前复习 SPI，可问“I2C 与 SPI 的区别”）；若关联牵强就不要强行结合，正常出当前知识点的题即可。\n'
        '这些薄弱点最近已出过的题（务必避免重复、换新角度）：\n' + ('\n'.join(lines) if lines else '（暂无）') + '\n'
    )


def extract_weakness_tags(wrong_items: List[Dict[str, Any]]) -> List[str]:
    """从答错的题中提炼薄弱知识点标签列表（简短关键词）。"""
    if not wrong_items:
        return []
    lines = []
    for i, w in enumerate(wrong_items, start=1):
        lines.append('{0}. 题目：{1}'.format(i, str(w.get('question') or '').strip()))
        lines.append('   参考答案：{0}'.format(str(w.get('answer') or '').strip()))
    content = chat([
        {'role': 'system', 'content': '你是一名学习教练，负责从答错题目中提炼薄弱知识点标签。'},
        {'role': 'user', 'content': (
            '下面是一些答错的复习题。请提炼出考生薄弱的「知识点标签」（简短关键词，如 I2C 时序、volatile、DMA 中断、指针运算）。\n'
            '要求：每个标签 2-8 个字，只提炼最核心、最具体的知识点；语义重复的合并；最多 5 个。\n'
            '严格只输出 JSON，格式：{"tags": ["标签1", "标签2"]}\n\n'
            '=== 答错题目 ===\n' + '\n'.join(lines)
        )},
    ], max_tokens=128, temperature=0.3)

    if not content:
        return []
    try:
        m = re.search(r'\{.*\}', content, re.S)
        obj = json.loads(m.group(0)) if m else json.loads(content)
        tags = obj.get('tags') or []
        if isinstance(tags, list):
            return [str(t).strip() for t in tags if str(t).strip()]
    except Exception:
        pass
    return []


def generate_choice_question(question: str, answer: str, weakness_tags: Optional[List[str]] = None, weakness_history: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """根据知识点生成一道单选题，可结合薄弱点强化。

    返回 {'question': str, 'options': [str, ...], 'correct': str(字母 A/B/C/D),
          'weakness_tag': Optional[str]（若结合了某薄弱点则返回该标签）}；
    失败返回 None。
    """
    weakness_block = _weakness_prompt_block(weakness_tags, weakness_history)
    content = chat([
        {'role': 'system', 'content': '你是一名学习教练，负责出单选题。'},
        {'role': 'user', 'content': (
            '根据下面的知识点出一道单选题，给出 4 个选项（A/B/C/D），其中只有一个是正确答案。\n'
            '严格只输出 JSON，格式：{"question": "<题目>", "options": ["<选项A>", "<选项B>", "<选项C>", "<选项D>"], "correct": "<正确选项字母 A/B/C/D>", "weakness_tag": "<结合的薄弱点标签，未结合填 null>"}\n'
            + weakness_block +
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
            wt = obj.get('weakness_tag')
            weakness_tag = str(wt).strip() if (isinstance(wt, str) and wt.strip().lower() not in ('', 'null', 'none')) else None
            return {'question': q, 'options': options, 'correct': correct, 'weakness_tag': weakness_tag}
    except Exception:
        pass
    return None


def generate_fill_blank_question(question: str, answer: str, weakness_tags: Optional[List[str]] = None, weakness_history: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, str]]:
    """根据知识点生成一道填空题，可结合薄弱点强化。

    返回 {'question': str(含 ____ 挖空), 'answer': str(正确答案),
          'weakness_tag': Optional[str]}；失败返回 None。
    """
    weakness_block = _weakness_prompt_block(weakness_tags, weakness_history)
    content = chat([
        {'role': 'system', 'content': '你是一名学习教练，负责出填空题。'},
        {'role': 'user', 'content': (
            '根据下面的知识点出一道填空题，把关键信息挖空（用 ____ 表示空位），并给出正确答案。\n'
            '严格只输出 JSON，格式：{"question": "<含 ____ 的题目>", "answer": "<正确答案>", "weakness_tag": "<结合的薄弱点标签，未结合填 null>"}\n'
            + weakness_block +
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
            wt = obj.get('weakness_tag')
            weakness_tag = str(wt).strip() if (isinstance(wt, str) and wt.strip().lower() not in ('', 'null', 'none')) else None
            return {'question': q, 'answer': a, 'weakness_tag': weakness_tag}
    except Exception:
        pass
    return None


def generate_card(topic: str, direction: Optional[str] = None) -> Tuple[str, str]:
    """第一层：根据主题让 LLM 出题并生成标准答案。

    direction：可选方向（如 编程语言/MCU），用于约束出题范围。
    返回 (question, answer)；失败时退回 (topic, topic)。
    """
    direction_text = ''
    if direction:
        direction_text = '\n题目方向：' + direction + '（请务必围绕该方向相关的知识点出题）'
    content = chat([
        {'role': 'system', 'content': '你是一名学习教练，负责根据主题出题并给出标准答案。'},
        {'role': 'user', 'content': (
            '围绕下面的主题，出一道适合考察理解程度的简答题，并给出标准答案。\n'
            '严格只输出 JSON，格式：{"question": "<题目>", "answer": "<标准答案>"}\n\n'
            '主题：' + topic + direction_text
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
    'mix': '项目经验与专业技能',
}


def generate_interview_question(project_experience: str, history_text: str, topic: str, round_no: int, total: int, past_questions: Optional[List[str]] = None, professional_skills: Optional[str] = None, mastered: Optional[List[Dict[str, Any]]] = None, failed: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """面试官基于画像中的项目经验与专业技能出一道面试题，由易到难。

    project_experience：画像中的项目经验文本（项目名 + 技术栈与实现描述）。
    professional_skills：画像中的专业技能文本（技能分类 + 关键词）。
    past_questions：历史面试问过的题目（含本次已问过的），用于去重、避免热门题过度集中。
    mastered：已答对的题（含知识点），出题时避开这些已掌握知识点。
    failed：已答错的题（含知识点），出题时围绕这些知识点换个问法重新考察。
    返回 {'question': str, 'reference': str, 'difficulty': 'easy|medium|hard', 'knowledge_point': str}；
    失败返回 None。
    """
    topic_desc = _TOPIC_DESC.get(topic, '项目经验与专业技能')
    past_text = ''
    if past_questions:
        past_text = '\n'.join('- ' + q for q in past_questions)

    projects_block = ''
    if project_experience:
        projects_block = ('=== 候选人项目经验（围绕项目用到的技术栈与实现细节出题，问候选人实际做过、写进简历的技术）===\n'
                          + project_experience + '\n\n')

    skills_block = ''
    if professional_skills:
        skills_block = ('=== 候选人专业技能（围绕这些技能出题，标注熟练的可以问更深、掌握的问适中，不要问画像之外的技术）===\n'
                        + professional_skills + '\n\n')

    mastered_block = ''
    if mastered:
        m_lines = ['- ' + (str(m.get('knowledge_point') or '').strip() or str(m.get('question') or '').strip()) for m in mastered]
        mastered_block = ('=== 已掌握知识点（候选人之前面试已答对，务必避开：不要再问这些知识点，也不要问高度相关、换汤不换药的题）===\n'
                          + '\n'.join(m_lines) + '\n\n')

    failed_block = ''
    if failed:
        f_lines = ['- ' + (str(f.get('knowledge_point') or '').strip() or str(f.get('question') or '').strip()) for f in failed]
        failed_block = ('=== 曾答错知识点（候选人之前面试答错过，可以围绕这些知识点换一个问法/角度重新考察，帮助巩固；务必换角度，不要原题重问）===\n'
                        + '\n'.join(f_lines) + '\n\n')

    content = chat([
        {'role': 'system', 'content': '你是一名软件工程面试官。请根据候选人的项目经验与专业技能出题，考察技术理解和表达能力。题目难度应由浅入深、知识点尽量多样，并符合候选人的技能水平。'},
        {'role': 'user', 'content': (
            '下面是候选人的项目经验与专业技能，供你出题。\n'
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
            '9. 【紧扣项目经验与专业技能】优先围绕候选人项目经验中用到的技术、以及专业技能中列出的技术出题；问候选人实际做过、写在简历里的技术，不要问画像之外的技术。\n'
            '严格只输出 JSON，格式：{"question": "<题目>", "reference": "<技术正确要点>", "difficulty": "easy|medium|hard", "knowledge_point": "<本题考察的核心知识点标签，2-8 字，如 volatile、I2C 时序>"}\n\n'
            + projects_block
            + skills_block
            + mastered_block
            + failed_block +
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
        kp = str(obj.get('knowledge_point') or '').strip()
        if d not in ('easy', 'medium', 'hard'):
            d = 'easy'
        if q:
            return {'question': q, 'reference': r, 'difficulty': d, 'knowledge_point': kp}
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
