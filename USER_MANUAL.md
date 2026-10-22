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
mnemosyne import --file "路径.md" [--tags "标签1,标签2"] [--subject "分区"] [--direction "方向"]
```

- `--file`：必填，笔记文件路径
- `--tags`：可选，额外标签（逗号分隔）
- `--subject`：可选，学科分区；不填时从文件所在目录名推断
- `--direction`：可选，方向（学科下的二级分类）；不填时从文件所在目录推断

导入规则见上文「快速开始」。

### sync —— 同步更新笔记

修改笔记后，用 `sync` 把改动同步到卡片库：

```powershell
mnemosyne sync --file "路径.md" [--tags "标签1,标签2"] [--subject "分区"] [--direction "方向"]
```

与 `import` 的区别：

- `import`：每次导入都新增一批卡片，重复导入会重复。
- `sync`：按「来源文件 + `##` 标题」匹配，更新已有卡片（**保留学习进度**），新增多出的知识点。

匹配规则：同一来源文件（`md:文件名` 标签）下，`##` 标题完全一致即视为同一张卡。正文改动 → 更新覆盖；标题改动或新增段落 → 新增卡片；删除段落 → 旧卡保留。

### add —— 添加卡片

有两种模式：

#### 手动模式（默认）

```powershell
mnemosyne add --q "问题" --a "答案" [--example "示例"] [--file "附件"] [--tags "标签"] [--subject "分区"] [--direction "方向"]
```

- `--q` / `--a`：问题与答案
- `--example`：可多次使用，添加示例
- `--file`：可多次使用，附加文件（复制到附件目录）
- `--tags`：逗号分隔标签
- `--subject`：可选，学科分区
- `--direction`：可选，方向（学科下的二级分类，如「编程语言」「MCU」）

#### AI 出题模式（可选，需 LLM）

```powershell
mnemosyne add --topic "Python 装饰器" [--direction "方向"]
```

用户只给一个主题，其余交给 AI，分两层。若未指定 `--direction`，会先交互式选择方向（可选「全部/不限定」），让 AI 围绕该方向出题；出题结果会打上对应方向标记。

1. **第一层 · 出题**：AI 根据主题出题并生成标准答案
2. **第二层 · 批改**：你作答后，AI 判断回答是否正确并给反馈

完成后把「题目 + 参考答案」存入数据库（附 `topic:` 标签）。

> 此模式仅在显式传 `--topic` 且已配置 LLM 时触发；未配置时提示错误，不会自动调用。

### review —— 复习

```powershell
mnemosyne review [--type choice|fill] [--feynman] [--no-llm] [--subject 分区] [--direction 方向]
```

- `--subject`：可选，仅复习指定分区（如 `--subject 英语`）
- `--direction`：可选，仅复习指定方向（如 `--direction MCU`）；不传时复习开始前交互式选择方向（含「全部」），方便把大量卡片拆成小批次练习
- 开始复习时会先显示今日待复习总数，例如 `共 50 题`
- 每答完一题，会更新进度显示为 `当前进度：1/50`，并在后续逐步减少剩余题数
- 默认：如果配置了 LLM，AI 出题 → 你作答 → AI 判分并给反馈 → 显示参考答案
- `--no-llm`：强制本地模式（显示问题 → 回车看答案 → 自评 0-5）
- `--feynman`：复习结束后提示你用一句话复述（费曼式），记录到复习历史

**随时退出（#quit）**：复习过程中，在任意输入提示处输入 `#quit` 即可提前退出今日复习。已完成的题目进度会保存，未做的题保持到期状态、下次仍会调出。

**AI 故障自愈与降级**：AI 出题遇到临时性错误（限流 429、服务暂时不可用 5xx、网络中断）会自动退避重试最多 3 次；单题仍失败时提示后改用本地模式作答，连续 3 题失败则本次复习自动整体切换到本地模式，避免每题都卡住重试。

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

**复习结束总结与薄弱点强化**：每次复习结束（自然做完或 `#quit` 退出）都会输出本次总结：答对/答错题数。若有答错的题，AI 会从中提炼出**薄弱知识点标签**（简短关键词，如「I2C 时序」「volatile」）并写入画像；下次复习出题时，AI 会读取画像薄弱点，若当前知识点能自然关联就出「结合薄弱点」的综合题（例：I2C 不熟、复习 SPI 时问「I2C 与 SPI 的区别」），关联牵强则不强凑。这些结合题会记录进历史，避免重复出题、换新角度。

薄弱点**连续答对 2 次自动消除**，可用 `mnemosyne profile show` 查看当前薄弱点及连续答对进度。

### interview —— AI 模拟面试（项目考核）

让 AI 基于画像中的**项目经验**与**专业技能**出题，由易到难考察你的技术掌握程度。

```powershell
mnemosyne interview [--num 6] [--topic c|stm32|mix]
```

- `--num`：面试题数，默认 6
- `--topic`：面试范围
  - `c`：偏重 C 语言
  - `stm32`：偏重嵌入式软件
  - `mix`：项目经验与专业技能综合（默认）

#### 查看面试历史题目

```powershell
mnemosyne interview history [--correct all|correct|wrong] [--limit 100] [--detail]
```

- 列出每次模拟面试的题目，含知识点、得分、对错、难度、范围、日期
- `--correct`：按对错筛选（`all` 全部 / `correct` 仅答对 / `wrong` 仅答错）
- `--limit`：最多显示条数（默认 100）
- `--detail`：额外显示你的回答与参考要点

出题依据是画像中的 `projects`（项目经验）与 `skills`（专业技能），需先设置画像：

```powershell
mnemosyne profile set --name "张三" --projects "项目经验..." --skills "专业技能..."
```

流程：

1. 面试官读取画像中的项目经验与专业技能
2. 逐题提问，难度由易到难；你作答后，面试官判分（0-5）、点评并**展示本题参考答案**
3. 面试结束输出**评价报告**：总分、总评、强项、薄弱点、学习建议
4. 随后输出**逐题回顾总结**：每道题的难度、知识点、得分、对错、题目、你的回答与参考答案
5. 自动把薄弱点**匹配到复习卡库中已有的卡片**，并标记为今日到期

之后运行 `mnemosyne review`，这些薄弱点对应的卡片会被调出，做**强化训练**。

**跨次记忆（答对不再问、答错换问法）**：每道面试题的答题结果会记录到数据库——答对（评分 ≥ 3）的题下次面试**不再出**；答错的题下次**围绕同一知识点换个角度重新考察**。答对/答错都按「知识点标签」去重，而非死扣原题文字，保证每次面试不断查漏补缺、覆盖新的知识面。

> 面试需配置 LLM。未配置时提示错误并退出。
>
> 启用 LLM 后，画像中的项目经验/专业技能和面试回答会发送给配置的服务商。请勿在画像中填写密钥等敏感信息。

### subject —— 学科分区

卡片可按**学科分区**组织（内置「英语」「嵌入式」「数学」），便于分学科学习。

```powershell
mnemosyne subject list                  # 列出所有分区及卡片数、今日到期数
mnemosyne subject add --name 物理 --desc "大学物理"   # 新建分区
```

分区会应用到导入/添加/复习/查看等命令的 `--subject` 参数上。

### direction —— 方向

在学科分区之下，卡片还可按**方向**（二级分类）组织。例如「嵌入式」分区下的「编程语言」「MCU」两个方向，对应笔记目录 `嵌入式/编程语言/`、`嵌入式/MCU/`。

- 导入/同步笔记时，方向会从文件所在目录自动推断（`嵌入式/MCU/*.md` → 方向 `MCU`）
- AI 出题（`add --topic`）时可选方向，让 AI 围绕该方向出题
- 复习（`review`）时可只复习某个方向，把当天大量到期卡片拆成小批次

可用 `--direction` 参数在 `add` / `import` / `sync` / `list` / `show` / `review` 命令中显式指定或筛选方向。

### list / show —— 查看

```powershell
mnemosyne list [--subject 分区] [--direction 方向]   # 简要列表
mnemosyne show [--subject 分区] [--direction 方向]   # 详细内容
```

### profile —— 学习画像

```powershell
mnemosyne profile set --name "张三" --difficulty hard --study-hours 0.5 --notes "碎片化学习"
mnemosyne profile set --projects "项目经验..." --skills "专业技能..."
mnemosyne profile show
```

- `--difficulty`：easy / normal / hard
- `--study-hours`：每日学习时长（小时）
- `--projects`：项目经验（多行文本，用于面试出题）
- `--skills`：专业技能（多行/分号分隔，可标注熟练度，用于面试出题）

画像会影响复习间隔：easy 更宽松，hard 更频繁，学习时长低则更保守。

`profile show` 除展示基本画像外，还会附带学习统计：卡片总数、今日到期数、累计复习次数、最近复习时间、已掌握卡片数（间隔≥21 天）。若画像中有项目经验、专业技能、薄弱点标签，也会一并列出（薄弱点含「连续答对 n/2」进度）。

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

### 方法三：多模型故障切换（推荐）

配置多个 provider，程序按顺序尝试，主服务崩溃时自动切换到备用服务（切换时会提示一次「当前模型服务」）。适合主模型（如 DeepSeek）偶发崩溃的场景，自动兜底到智谱 GLM：

```json
{
  "providers": [
    {"name": "deepseek", "api_key": "...", "api_url": "https://api.deepseek.com/v1/chat/completions", "model": "deepseek-chat"},
    {"name": "glm", "api_key": "...", "api_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "model": "glm-4-flash"}
  ]
}
```

- `providers` 按顺序依次尝试，`api_key` 为空的项会被自动跳过
- 想手动指定只用某个服务时，删除其他项或调整顺序即可
- 智谱 GLM 的 `glm-4-flash` 为免费模型，可到 open.bigmodel.cn 申请 key

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