# 遗忘曲线学习助手

一个本地优先的个人学习记忆工具：把 Markdown 笔记拆成知识点卡片，按间隔重复（SM-2 / 艾宾浩斯遗忘曲线）调度复习，可选接入 LLM 自动出题与判分。

项目许可证：GPL-3.0-only，详见 [LICENSE](LICENSE)。

## 核心工作流

1. 写 Markdown 笔记（`#` 是主题，`##` 是知识点）
2. 首次导入：`mnemosyne import --file notes.md`（可用 `--subject` 指定学科分区、`--direction` 指定方向）
3. 修改笔记后同步：`mnemosyne sync --file notes.md`（更新卡片、保留进度）
4. 每天复习：`mnemosyne review`（AI 出题判分，或本地自评），并在开始时显示今日待复习总量与实时进度；可先选方向把大量卡片拆成小批次；复习中随时输入 `#quit` 退出，结束时自动统计对错并提炼薄弱点写入画像

## 学科分区

卡片可归入**学科分区**（subject），内置「英语」「嵌入式」「数学」三个分区，便于按学科分别学习：

- 导入/同步时指定分区：`mnemosyne import --file notes.md --subject 嵌入式`；不填 `--subject` 时，会取笔记所在目录名作为分区（如 `Makedown/嵌入式/x.md` → 分区「嵌入式」）
- 按分区复习：`mnemosyne review --subject 英语`
- 查看分区与统计：`mnemosyne subject list`
- 新建分区：`mnemosyne subject add --name 物理 --desc "大学物理"`

## 方向（二级分类）

在学科分区之下，卡片还可按**方向**（direction）细分。例如「嵌入式」分区下的「编程语言」「MCU」两个方向，对应笔记目录 `嵌入式/编程语言/`、`嵌入式/MCU/`。

- 导入/同步自动推断方向：`mnemosyne import --file 嵌入式/MCU/x.md` → 方向「MCU」；也可用 `--direction` 显式指定
- AI 出题选方向：`mnemosyne add --topic "主题" --direction MCU`，让 AI 围绕该方向出题
- 按方向分批复习：`mnemosyne review --direction MCU`（或开始时不指定，交互式选方向）
- 查看时按方向筛选：`mnemosyne list --direction 编程语言`

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
| `mnemosyne import --file x.md [--subject 分区] [--direction 方向]` | 导入 Markdown 笔记（`##` → 卡片），可指定学科分区与方向 |
| `mnemosyne sync --file x.md [--subject 分区] [--direction 方向]` | 同步更新笔记（更新已有卡片、保留学习进度，新增多出知识点） |
| `mnemosyne add --q "..." --a "..." [--subject 分区] [--direction 方向]` | 手动添加卡片 |
| `mnemosyne add --topic "主题" [--direction 方向]` | AI 出题 + 批改（需 LLM，可选方向） |
| `mnemosyne review [--subject 分区] [--direction 方向]` | 复习到期卡片（AI 出题判分，题型自选：选择/填空；输入 `#quit` 退出并总结对错、提炼薄弱点） |
| `mnemosyne interview [--num N] [--topic c\|stm32\|mix]` | AI 模拟面试：依据画像的项目经验与专业技能出题，由易到难，结束给出评价报告并标记薄弱卡片强化复习；答对不再问、答错换问法 |
| `mnemosyne interview history [--correct ...] [--detail]` | 查看面试历史题目（含知识点、得分、对错、难度、日期） |
| `mnemosyne list [--subject 分区] [--direction 方向]` | 列出卡片 |
| `mnemosyne show [--subject 分区] [--direction 方向]` | 查看卡片详情 |
| `mnemosyne subject list` | 列出学科分区及统计 |
| `mnemosyne subject add --name 分区名` | 新建学科分区 |
| `mnemosyne profile set / show` | 设置 / 查看学习画像（show 附带学习统计） |
| `mnemosyne export --out file.json` | 导出数据 |

## 可选 LLM

复习时可接入 OpenAI 兼容 API（默认 DeepSeek），让 AI 出题并判分。可设置环境变量，或在数据目录创建 `config.json`。

单模型配置：

```json
{"api_key": "你的key", "api_url": "https://api.deepseek.com/v1/chat/completions", "model": "deepseek-chat"}
```

**多模型故障切换（推荐）**：配置多个 provider，主服务崩溃时自动切换到备用（例如 DeepSeek → 智谱 GLM）：

```json
{
  "providers": [
    {"name": "deepseek", "api_key": "...", "api_url": "https://api.deepseek.com/v1/chat/completions", "model": "deepseek-chat"},
    {"name": "glm", "api_key": "...", "api_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "model": "glm-4-flash"}
  ]
}
```

未配置 key 时，复习自动退回本地自评模式。启用 LLM 后，发送给 LLM 的题目、答案及画像中的项目经验/专业技能会传给所配置的服务商；请勿使用敏感内容。

AI 出题遇到临时性错误（限流 429、服务暂时不可用 5xx、网络中断）会自动退避重试最多 3 次；主服务连续失败会自动切换到备用服务，全部失败则降级为本地自评模式，不会卡住复习。

## 文档

- [使用手册](USER_MANUAL.md)
- [功能手册](FEATURE_MANUAL.md)
- [开发日志](DEVELOPMENT_LOG.md)
