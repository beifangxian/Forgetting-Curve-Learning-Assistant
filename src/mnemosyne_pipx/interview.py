"""Collect project source and format interview history for the LLM."""
import os
from typing import List, Dict, Any

SOURCE_EXTENSIONS = {'.c', '.h', '.cpp', '.hpp', '.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.go', '.rs', '.cs'}
IGNORED_DIRS = {'.git', '.hg', '.svn', '.venv', 'venv', 'node_modules', '__pycache__', 'build', 'dist'}
MAX_PROJECT_FILES = 30
MAX_FILE_CHARS = 6000

def collect_project_context(project_root: str = None) -> str:
    """Read a bounded set of source files under a user-selected project root."""
    project_root = project_root or os.environ.get('MNEMOSYNE_PROJECT_ROOT') or os.getcwd()
    project_root = os.path.abspath(os.path.expanduser(project_root))
    parts = []
    for current_dir, dir_names, file_names in os.walk(project_root):
        dir_names[:] = sorted(name for name in dir_names if name not in IGNORED_DIRS and not name.startswith('.'))
        for file_name in sorted(file_names):
            if os.path.splitext(file_name)[1].lower() not in SOURCE_EXTENSIONS:
                continue
            path = os.path.join(current_dir, file_name)
            try:
                if os.path.getsize(path) > 1024 * 1024:
                    continue
                with open(path, 'r', encoding='utf-8', errors='replace') as source_file:
                    text = source_file.read(MAX_FILE_CHARS + 1)
            except OSError:
                continue
            if len(text) > MAX_FILE_CHARS:
                text = text[:MAX_FILE_CHARS] + '\n...(truncated)...'
            label = os.path.relpath(path, project_root)
            parts.append('===== {0} =====\n{1}'.format(label, text))
            if len(parts) >= MAX_PROJECT_FILES:
                return '\n\n'.join(parts)
    return '\n\n'.join(parts)


def format_history(history: List[Dict[str, Any]]) -> str:
    """Format interview history for the LLM while bounding answer length."""
    lines = []
    for i, h in enumerate(history, start=1):
        lines.append('第{0}题：{1}'.format(i, h.get('question', '')))
        answer = str(h.get('user_answer', ''))
        if len(answer) > 300:
            answer = answer[:300] + '...(已截断)'
        lines.append('候选人回答：{0}'.format(answer))
        lines.append('得分：{0}/5'.format(h.get('score')))
        if h.get('feedback'):
            lines.append('点评：{0}'.format(h['feedback']))
        lines.append('')
    return '\n'.join(lines)
