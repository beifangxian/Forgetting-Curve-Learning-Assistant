# 遗忘曲线学习助手

一个本地优先的个人学习记忆工具：把 Markdown 笔记拆成知识点卡片，按间隔重复（SM-2 / 艾宾浩斯遗忘曲线）调度复习，可选接入 LLM 自动出题与判分。

项目许可证：GPL-3.0-only，详见 [LICENSE](LICENSE)。

## 核心工作流

1. 写 Markdown 笔记（`#` 是主题，`##` 是知识点）
2. 首次导入：`mnemosyne import --file notes.md`
3. 修改笔记后同步：`mnemosyne sync --file notes.md`（更新卡片、保留进度）
4. 每天复习：`mnemosyne review`（AI 出题判分，或本地自评），并在开始时显示今日待复习总量与实时进度

## 数据与配置目录

默认数据目录为 Windows `%LOCALAPPDATA%\mnemosyne`，macOS/Linux `$XDG_DATA_HOME/mnemosyne`（未设置时为 `~/.local/share/mnemosyne`）。可通过 `MNEMOSYNE_DATA_DIR` 指定其他位置。

## 安装（Windows PowerShell）

```powershell
python -m pip install --user pipx
python -m pipx install --editable .
```

> 使用 `--editable` 可编辑安装，后续修改源码无需重装即可生效。

未安装时，可在项目目录用模块入口运行：

```powershell
$env:PYTHONPATH = "src"
python -m mnemosyne_pipx --help
```

## 命令速查

| 命令 | 说明 |
|------|------|
| `mnemosyne import --file x.md` | 导入 Markdown 笔记（`##` → 卡片） |
| `mnemosyne sync --file x.md` | 同步更新笔记（更新已有卡片、保留学习进度，新增多出知识点） |
| `mnemosyne add --q "..." --a "..."` | 手动添加卡片 |
| `mnemosyne add --topic "主题"` | AI 出题 + 批改（需 LLM） |
| `mnemosyne review` | 复习到期卡片（AI 出题判分，题型自选：选择/填空） |
| `mnemosyne interview` | AI 模拟面试：读项目源码出题，由易到难，结束给出评价报告并标记薄弱卡片强化复习 |
| `mnemosyne list` | 列出卡片 |
| `mnemosyne show` | 查看卡片详情 |
| `mnemosyne profile set / show` | 设置 / 查看学习画像（show 附带学习统计） |
| `mnemosyne export --out file.json` | 导出数据 |

## 可选 LLM

复习时可接入 OpenAI 兼容 API（默认 DeepSeek），让 AI 出题并判分。可设置环境变量，或在数据目录创建 `config.json`：

```json
{"api_key": "你的key", "api_url": "https://api.deepseek.com/v1/chat/completions", "model": "deepseek-chat"}
```

未配置 key 时，复习自动退回本地自评模式。启用 LLM 后，发送给 LLM 的题目、答案及项目源码会传给所配置的服务商；请勿使用敏感内容。

## 文档

- [使用手册](USER_MANUAL.md)
- [功能手册](FEATURE_MANUAL.md)
- [开发日志](DEVELOPMENT_LOG.md)
