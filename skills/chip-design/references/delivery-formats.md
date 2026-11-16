# 交付格式与单一源

spec 最终交到谁手上、以什么格式，决定图表怎么落、改完回到哪。本节只回答三件事：**哪份是源、每种格式给谁用、图怎么进 Word/PDF**。

## 零、一条铁律：Markdown 是唯一可编辑源

同一份 spec 写三遍（md 一份、Word 一份、PDF 一份）= 三份必然漂移的副本，与"附录 A 不手抄主表"是同一条纪律。**Word 与 PDF 是生成物，不手改。**

| 格式 | 给谁用 | 谁改它 | 改完回到哪 |
|---|---|---|---|
| **Markdown** | 设计/验证日常、git review、diff、ECO 追溯 | 设计者 | 它就是源 |
| **Word** | 正式评审、跨部门会签、批注 | 评审人（批注/修订模式） | 批注收回来 → 改 Markdown → 重新生成 |
| **PDF** | 归档、对外交付、签字版 | 没人改 | — |

**Word 回流规则（这条不写，单一源三周就死）：** 评审批注收回来后，一律改 Markdown 再重新生成 Word。禁止"在 Word 里直接改正文、改完的 Word 当新主"——从那一刻起 Markdown 与 Word 各改各的，两边都在漂移，且 Word 里的改动从此没有 diff、没有版本记录。

**裁剪：** 没有评审/会签需求的内部文档，只出 Markdown，不生成 Word/PDF——生成物没人读就是维护负担。

## 一、图表在三种格式里怎么落

| 格式 | 图 | 表 |
|---|---|---|
| Markdown | **DSL 源码直接嵌**：Mermaid / WaveDrom 代码块，平台原生渲染 | GFM 管道表 |
| Word / PDF | **必须预渲染成 SVG/PNG 嵌入**（Word 不认 Mermaid 代码块，会原样变文本） | 转换器出 Word 表格 |

两条纪律：

1. **图源进仓库。** 每张图的 DSL 源文件放 `fig/` 目录（`fig-3-A-02.mmd`、`fig-3-B-01.wavedrom`），正文引用编号与文件名对应。图脚标注明：`源：fig/fig-3-A-02.mmd · 由 md2doc 生成 · 勿手改`。与附录 A 同一原则：**图是生成物，源码才是可维护的。**
2. **不许在 Word 里手画图再贴回 Markdown。** 手画的图不可 diff、ECO 时改不动，等于把最常变的部分放进了最不可追溯的容器。宁可 Markdown 里先放 ASCII 框图占位，定稿前再渲染。

**选型**：框图/状态机/计算映射图用 **Mermaid**；拍级波形用 **WaveDrom**（Mermaid 的 sequenceDiagram 画消息箭头，画不了电平与反压，别用错）。

WaveDrom 波形骨架（valid-ready 反压场景）：

```json
{ "signal": [
  { "name": "clk",   "wave": "p......" },
  { "name": "valid", "wave": "0.1..0." },
  { "name": "ready", "wave": "1..0.1." },
  { "name": "data",  "wave": "x.=.=x.", "data": ["D0", "D1"] },
  {},
  { "name": "采样点", "wave": "0..1.0.", "node": ".A.B.." }
],
"head": { "text": "valid-ready 握手：ready 拉低两拍，D1 在第 5 拍采样" } }
```

## 二、转换链与脚本

**PDF 走 HTML 中转，不走 pandoc+LaTeX。** 中文 PDF 用 LaTeX 引擎必须配 CJK 字体（`xelatex -V CJKmainfont=...`），一步配错全是方框；浏览器打印路径零配置、系统字体直接嵌入，实测 Microsoft YaHei 正常嵌入。

```
spec.md ──┬──> spec.md   （源，直接交付）
          ├──> spec.docx  （python-docx 生成，表头跨页重复已设）
          └──> spec.html ──> spec.pdf  （Edge/Chrome headless --print-to-pdf）
```

脚本：`skills/chip-design/scripts/md2doc.py`

```bash
python md2doc.py spec.md              # 同时出 docx + pdf
python md2doc.py spec.md --only pdf   # 只出 PDF
python md2doc.py spec.md --only docx --font 宋体
```

依赖两样：`python-docx`（`pip install python-docx -i https://mirrors.aliyun.com/pypi/simple/`，约 1 MB）；Edge 或 Chrome（Windows/macOS 基本自带，PDF 引擎走 headless 打印，零安装）。

**转换器已处理的**：标题层级、GFM 表格（含表头底纹与跨页重复）、代码块底纹等宽、行内粗体/行内代码、引用块、有序无序列表、页脚页码、A4 页边距。

**转换器不做的（需要时手工补，别指望自动）**：

- 复杂合并单元格——Markdown 表达不了，需要时在 Word 里补并登记
- 图表交叉引用自动编号——"见图 3-A-02"要靠 Word 域或手工保持一致
- 目录自动生成——Word 里插入 TOC 域即可，不必写进源

## 三、常见错误

- **三份手写**：md、docx 各改各的，第一个 ECO 后就分叉。
- **Word 改完当新主**：评审批注直接在 Word 里改正文，改完不回 Markdown——从这版起源文件失效。
- **Markdown 里贴截图不贴源码**：图变成不可追溯的位图，下次改模块名图不跟着变。
- **Word 里手画结构图**：不可 diff，评审看不出两版差异。
- **用 Mermaid sequenceDiagram 画波形**：画的是消息序列不是电平，反压与采样拍全丢。波形必须 WaveDrom。
- **中文 PDF 走 pandoc 默认引擎**：没配 CJK 字体就是满页方框。走浏览器打印路径。
- **寄存器表 40 行跨 3 页、表头不重复**：转换器已设 `tblHeader`；若换工具生成，先查这一项——没它这表没法读。
