# 遗忘曲线复习 使用手册

## 概述

遗忘曲线复习是一个本地优先的学习记忆工具。核心思路：**把 Markdown 笔记拆成知识点卡片，按间隔重复节奏复习，可选 AI 出题判分。**

- 数据全部保存在本地 SQLite，不上传云端
- 无 GUI，纯命令行（CLI）
- LLM 可选，不配置也能完全离线使用

## 快速开始

### 1. 写一篇 Markdown 笔记

```markdown
# Python 基础

## 什么是变量
变量是用来存数据的容器，用 `=` 赋值即可创建。

## 什么是列表
列表是有序可变序列，用方括号 `[]` 表示。
```

约定：
- `#` 一级标题 = 主题（自动成为标签）
- `##` 二级标题 = 知识点（成为卡片的「问题」）
- 标题之间的正文 = 答案

### 2. 导入

```powershell
python -m mnemosyne_pipx import --file "D:\笔记\Python基础.md"
```

每个 `##` 段落变成一张卡片。

### 3. 复习

```powershell
python -m mnemosyne_pipx review
```

## 运行方式

### 方式 A：模块入口（推荐）

在项目目录下：

```powershell
$env:PYTHONPATH = "src"
python -m mnemosyne_pipx --help
```

### 方式 B：pipx 安装后的命令

```powershell
python -m pip install --user pipx
python -m pipx install --editable .
mnemosyne --help
```

> 建议用 `--editable` 可编辑安装，后续改源码无需重装即可生效。

## 命令详解

### import —— 导入 Markdown 笔记

```powershell
mnemosyne import --file "路径.md" [--tags "标签1,标签2"]
```

- `--file`：必填，笔记文件路径
- `--tags`：可选，额外标签（逗号分隔）

导入规则见上文「快速开始」。

### sync —— 同步更新笔记

修改笔记后，用 `sync` 把改动同步到卡片库：

```powershell
mnemosyne sync --file "路径.md" [--tags "标签1,标签2"]
```

与 `import` 的区别：

- `import`：每次导入都新增一批卡片，重复导入会重复。
- `sync`：按「来源文件 + `##` 标题」匹配，更新已有卡片（**保留学习进度**），新增多出的知识点。

匹配规则：同一来源文件（`md:文件名` 标签）下，`##` 标题完全一致即视为同一张卡。正文改动 → 更新覆盖；标题改动或新增段落 → 新增卡片；删除段落 → 旧卡保留。

### add —— 添加卡片

有两种模式：

#### 手动模式（默认）

```powershell
mnemosyne add --q "问题" --a "答案" [--example "示例"] [--file "附件"] [--tags "标签"]
```

- `--q` / `--a`：问题与答案
- `--example`：可多次使用，添加示例
- `--file`：可多次使用，附加文件（复制到附件目录）
- `--tags`：逗号分隔标签

#### AI 出题模式（可选，需 LLM）

```powershell
mnemosyne add --topic "Python 装饰器"
```

用户只给一个主题，其余交给 AI，分两层：

1. **第一层 · 出题**：AI 根据主题出题并生成标准答案
2. **第二层 · 批改**：你作答后，AI 判断回答是否正确并给反馈

完成后把「题目 + 参考答案」存入数据库（附 `topic:` 标签）。

> 此模式仅在显式传 `--topic` 且已配置 LLM 时触发；未配置时提示错误，不会自动调用。

### review —— 复习

```powershell
mnemosyne review [--type choice|fill] [--feynman] [--no-llm]
```

- 开始复习时会先显示今日待复习总数，例如 `共 50 题`
- 每答完一题，会更新进度显示为 `当前进度：1/50`，并在后续逐步减少剩余题数
- 默认：如果配置了 LLM，AI 出题 → 你作答 → AI 判分并给反馈 → 显示参考答案
- `--no-llm`：强制本地模式（显示问题 → 回车看答案 → 自评 0-5）
- `--feynman`：复习结束后提示你用一句话复述（费曼式），记录到复习历史

**题型自选（AI 模式）**：复习时可以自己选择题型：

| 题型 | `--type` 值 | 说明 |
|------|-------------|------|
| 选择 | `choice` | AI 出单选题（4 个选项），你选 A/B/C/D，直接判对错 |
| 填空 | `fill` | AI 出填空题（挖空），你填入答案，AI 判分 |

- 不传 `--type` 时，会在复习开始前交互式询问（1=选择 2=填空，回车默认选择）
- 选定的题型会应用到本次所有到期卡片

**答错后（AI 模式）**：答错（评分 < 3）后会提示你一句话复述该知识点（费曼式），存入复习历史。

> 仅在 AI 模式且答错时出现；本地模式无此提示。

评分 0-5 会驱动 SM-2 调度，更新下次复习时间。

### interview —— AI 模拟面试（项目考核）

让 AI 基于你选择的项目源码出题，由易到难考察项目掌握程度。

```powershell
mnemosyne interview [--num 6] [--topic c|stm32|mix] [--project-root 路径]
```

- `--num`：面试题数，默认 6
- `--topic`：面试范围
  - `c`：偏重 C 语言
  - `stm32`：偏重嵌入式软件
  - `mix`：项目源码涉及的综合技术（默认）
- `--project-root`：项目源码目录；默认当前工作目录，也可设置 `MNEMOSYNE_PROJECT_ROOT`

流程：

1. 面试官读取所选项目目录中的源码
2. 逐题提问，难度由易到难；你作答后，面试官判分（0-5）并点评
3. 面试结束输出**评价报告**：总分、总评、强项、薄弱点、学习建议
4. 自动把薄弱点**匹配到复习卡库中已有的卡片**，并标记为今日到期

之后运行 `mnemosyne review`，这些薄弱点对应的卡片会被调出，做**强化训练**。

> 面试需配置 LLM。未配置时提示错误并退出。
>
> 启用 LLM 后，所读取的源码和面试回答会发送给配置的服务商。请勿选择包含密钥或其他敏感信息的目录。

### list / show —— 查看

```powershell
mnemosyne list   # 简要列表
mnemosyne show   # 详细内容
```

### profile —— 学习画像

```powershell
mnemosyne profile set --name "张三" --difficulty hard --study-hours 0.5 --notes "碎片化学习"
mnemosyne profile show
```

- `--difficulty`：easy / normal / hard
- `--study-hours`：每日学习时长（小时）

画像会影响复习间隔：easy 更宽松，hard 更频繁，学习时长低则更保守。

`profile show` 除展示基本画像外，还会附带学习统计：卡片总数、今日到期数、累计复习次数、最近复习时间、已掌握卡片数（间隔≥21 天）。

### export —— 导出

```powershell
mnemosyne export --out "D:\backup.json"
```

## LLM 配置（可选）

让 AI 在复习时出题并判分：

### 方法一：环境变量

```powershell
$env:MNEMOSYNE_LLM_API_KEY = "你的key"
$env:MNEMOSYNE_LLM_API_URL = "https://api.deepseek.com/v1/chat/completions"
$env:MNEMOSYNE_LLM_MODEL = "deepseek-chat"
```

### 方法二：配置文件

在数据目录中创建 `config.json`。Windows 默认目录为 `%LOCALAPPDATA%\mnemosyne`；macOS/Linux 默认目录为 `$XDG_DATA_HOME/mnemosyne`（未设置时为 `~/.local/share/mnemosyne`）。也可通过 `MNEMOSYNE_DATA_DIR` 指定数据目录：

```json
{"api_key": "你的key", "api_url": "https://api.deepseek.com/v1/chat/completions", "model": "deepseek-chat"}
```

也支持包一层：`{"llm": {"api_key": "..."}}`

> 安全提醒：密钥只保存在本机，不要提交到 GitHub 或共享给别人。

## 默认路径

| 项 | 路径 |
|----|------|
| 数据库 | `<数据目录>/mnemosyne.db` |
| 附件目录 | `<数据目录>/files` |

Windows 默认数据目录：`%LOCALAPPDATA%\mnemosyne`。macOS/Linux 默认数据目录：`$XDG_DATA_HOME/mnemosyne`；未设置 `XDG_DATA_HOME` 时使用 `~/.local/share/mnemosyne`。

## 故障排查

- **找不到模块**：确认在项目目录执行，并设置 `$env:PYTHONPATH = "src"`
- **数据库不更新**：检查是否用了不同的 DB 路径
- **Python 版本**：需 3.8+