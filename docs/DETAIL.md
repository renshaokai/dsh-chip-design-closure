# 设计收口

这个预设是 `package/chip-arch-expert.zip` 那份 CodeBuddy 专家插件（v1.7.0，作者「流片之前」）的 DSH 版：人格提示词取自该插件的 agent 定义，工作底稿取自它自带的 `chip-design` 技能。技能内容不变，人设正文改为第二人称并去掉人名；预设、工具组合、图标与展示元数据是 DSH 侧的。

名字取「设计收口」，对应人设自己的主张：**设计侧到底，验证侧只交接**。分界线在 VP 清单，之前的产出都归它，之后属于验证；它的价值落在后半段——写得出 RTL 的人很多，能把 RTL 收到时序和面积里的少。<br>

## 它会做什么

一位数字芯片架构与前端设计负责人，负责设计侧全流程：架构与预算 → 设计规格（正向编写，或从已有 RTL 反向回填 as-built）→ 功能点（FP）与测试点（VP，P0/P1/P2 分级）→ RTL → lint/CDC → 逻辑综合 → 时序收敛 → PPA 优化 → SoC 集成与评审对账。分界线落在 VP 清单：VP 之前的产出都归它，VP 之后属于验证，它只保证交接输入完整、可执行、边界清楚。

## 包含内容

| 组成 | 来源 |
|---|---|
| 人格提示词 | 原 `agents/chip-arch-expert.md` 正文全文（去掉 YAML frontmatter），作为预设 Persona |
| `chip-design` 技能 | 原 `skills/chip-design` 全量：`SKILL.md`，10 份 `references/`（架构预算、七章规格大纲、FP/VP、RTL 清单、综合时序、PPA、评审、SoC 集成、交付格式），`templates/spec-template.md` 与 `scripts/md2doc.py` |
| 工具 | PowerShell/Bash、文件读写与 glob/grep、后台作业、todo、技能加载、联网搜索、提问、交付物声明、Office 文档、上下文压缩 |

## 怎么使用

在会话顶部切换预设，选择「设计收口」。技能 `chip-design` 在该预设的会话里自动可见，模型按需加载；它同时存在于 bundle 的 `skills/` 目录下。

## 与原始插件的差异

- 原始 `maxTurns: 80` 在 DSH 预设里没有对应字段，未迁移；需要限制轮次请在会话侧控制。
- 原始 `avatars/expert.png`（512×512 圆形徽标，内含「芯片定制」文字）在 36 px 行内尺寸下文字不可读，因此插件图标改用自绘的芯片剪影 SVG。要换回原图，把 PNG 放进包内并在 `package.json` 声明 `"icon"`。
- 原始 `quickPrompts`、`defaultInitPrompt`、`categoryId`、`expertType` 是 CodeBuddy 侧的概念，DSH 预设没有对应字段，未迁移。
- 技能根目录在补丁里用 `baseUrl` 求值为包自身的 `skills/` 目录，因此移动包目录、从 npm 或 tarball 安装都不需要改配置。
- 人设正文从第三人称改为第二人称，并去掉了原名「顾芯 Gu Xin」；其余措辞与原始 agent 定义一致。
- 原始 ZIP 仍保留在 `package/chip-arch-expert.zip`，本 bundle 是它的 DSH 侧移植，未改动原文件。
