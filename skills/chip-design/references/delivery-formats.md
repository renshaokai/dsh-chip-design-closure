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
| Markdown | **DSL 源码直接嵌**：Mermaid / WaveDrom / drawio 代码块，平台原生渲染 | GFM 管道表 |
| Word / PDF | **必须预渲染成 SVG/PNG 嵌入**（Word 不认 Mermaid 代码块，会原样变文本） | 转换器出 Word 表格 |

两条纪律：

1. **图源进仓库。** 每张图的 DSL 源文件放 `fig/` 目录（`fig-3-A-02.drawio`、`fig-3-B-01.wavedrom`），正文引用编号与文件名对应。图脚标注明：`源：fig/fig-3-A-02.drawio · 由 figrender.py 生成 · 勿手改`。与附录 A 同一原则：**图是生成物，源码才是可维护的。**
2. **不许在 Word 里手画图再贴回 Markdown。** 手画的图不可 diff、ECO 时改不动，等于把最常变的部分放进了最不可追溯的容器。

### 1.1 选型：三类图，三种工具，别混用

| 图的性质 | 用什么 | 判据 |
|---|---|---|
| **架构框图 / 结构框图 / 层次图** | **draw.io（`.drawio`）** | 有容器嵌套、有并排方块、要人工微调位置 |
| 流程图 / 状态机 / 数据流 | Mermaid（`.mmd`） | 节点关系比位置重要，拓扑自动排即可 |
| 拍级波形 | WaveDrom（`.wavedrom`） | 有电平、有时钟沿、有反压 |

**架构框图必须用 draw.io，不能用 Mermaid——这条是实测出来的，不是偏好。**

Mermaid 的 `flowchart` 带 `subgraph` 画 SoC 框图时会翻车：只要两个子图之间有连线（SoC 图里必然有——CPU 和存储都要连到 interconnect），**嵌套关系就会失效，子图被甩到父容器外面去**。实拍过的样子：`从设备` 子图跑出了 `AXI 子系统` 的边框，中断信号标签被挤成竖排小字压在边框上。

```
Mermaid 能画：拓扑对不对（评审阶段够用）
Mermaid 画不了：容器归属、方块对齐、走线避让 —— 而这三点正是芯片框图的全部
```

draw.io 的 XML 是**手写坐标**，也就是位置完全可控。AI 直接写 XML 就相当于"AI 用手画图"，不需要人拖鼠标，也不需要 MCP。

> **为什么不用 draw.io 的 MCP？**
> 官方 MCP（`npx @drawio/mcp`、`https://mcp.draw.io/mcp`）做的是"把图打开在浏览器里让你看和改"，产物是一次性会话。
> 我们要的是**能进仓库、重跑一条命令就重新出来**的文件。直接写 `.drawio` XML + CLI 导出，可 diff、可复现、可版本追溯。MCP 适合临时看一张图，不适合交付链路。
> 如果需要交互调图，`.drawio` 文件双击就能用 draw.io 打开，那时再改也不迟。

### 1.2 draw.io 骨架：坐标是手写的，所以布局要自己想清楚

最小可用骨架（一个容器 + 一个方块 + 一条连线）：

```xml
<mxfile host="app.diagrams.net" type="device">
  <diagram id="arch" name="架构">
    <mxGraphModel pageWidth="960" pageHeight="640">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <mxCell id="top" value="SoC 顶层" style="swimlane;startSize=28;container=1;collapsible=0;" vertex="1" parent="1">
          <mxGeometry x="30" y="30" width="880" height="540" as="geometry" />
        </mxCell>
        <mxCell id="cpu" value="CPU Core" style="rounded=0;whiteSpace=wrap;html=1;" vertex="1" parent="top">
          <mxGeometry x="20" y="38" width="108" height="48" as="geometry" />
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

四条硬约束（漏一条图就散）：

1. **`id="0"` 和 `id="1"` 是保留的根单元**，永远不要复用这两个 id。
2. **容器必须写 `container=1`**，子单元的 `parent` 指向容器 id，`mxGeometry` 的 `x/y` 是**相对容器**的坐标，不是页面坐标。
3. **连线单元的 `parent` 要设成两端共同的祖先容器**，否则线会画到容器外面。跨容器连线时 `parent` 设最外层容器，用 `exitX/exitY` 和 `entryX/entryY`（0–1 的相对位置）指定接点。
4. **别让连线穿过无关方块。** 正交走线（`edgeStyle=orthogonalEdgeStyle`）会自己找路，但方块排布不配合时它照样穿。原则：**容器对容器连，不要方块对方块跨列连**；同列内才用方块直连。

排布经验（三轮实拍才定下来的）：把方块按列排成网格，**同列内上下相邻的才连线**，跨列的一律从容器边缘出。这样做完基本不用调 `waypoints`。

**别往架构图里塞信号级细节。** 中断汇集、时钟树这类"取值型关系"放表格，不放框图——画进去要么绕一大圈像条总线，要么压住别的方块。框图只回答"有哪些块、怎么层次、谁连谁"。

### 1.3 图能不能被人改：可以，但要注意三件事

这是选 draw.io 的一半理由。**`.drawio` 是文本 XML，用 draw.io 打开就能拖能改；改完重跑一条命令，文档跟着变。**

**怎么改（两条路，都对）：**

| 改法 | 适合谁 | 怎么操作 | 改完 |
|---|---|---|---|
| **draw.io 打开改**（推荐） | 想把图拖好看的 | 双击 `fig/xxx.drawio`（或拖进 app.diagrams.net），改完 Ctrl+S | 重跑 `figrender.py fig/` |
| 直接改 XML | 只想改个名字／加个方块的 | 文本编辑器改 `value="..."` | 同上 |

**draw.io GUI 保存后的压缩格式照样能渲染**——它会把 XML 压成 base64 存在 `<diagram>` 里，尺寸从 10 KB 缩到 2 KB。实测这条路是通的，`figrender.py` 不用额外处理。
唯一要注意：**GUI 里另存时选 `File > Save`，别选 `Export as > XML unzipped`**，后者会多包一层文件结构，脚本认不出。

**三件事必须知道：**

1. **改完必须重跑 `figrender.py`，否则文档里还是旧图。** 这是这条链路最隐蔽的错误——`md2doc.py` 只看 `.svg/.png` 存不存在，不看你什么时候改的。**已经加了防护**：图源比产物新时，`md2doc.py` 会打 `[过期] …` 警告。看到这行就是"你改了图但没重渲染"。
2. **加方块后要把容器撑大，且由内向外撑。** draw.io 不会自动撑开父容器：往"低速外设"里加一个方块，方块会掉到容器框外面；把"低速外设"撑大后，"顶层"容器又装不下它，边框被顶出画布。**顺序是：先撑最内层，再逐层往外撑**，每撑一层重跑一次看一眼。
3. **`fig/` 里的 `.svg` 和 `.png` 是产物，别手改。** 改了下次渲染就被覆盖。要改就改 `.drawio`。md 里那行注释写清了哪个是源、哪个是产物。

**人工改的东西会不会被覆盖？** 不会——`--inline` 只在 md 里还有 ```drawio 代码块时才写 `fig/`；一旦块已经被抽走（正常状态），再跑 `--inline` 是空操作。所以人工改 `fig/*.drawio` 是安全的持久改动。

**共享给同事**：`.drawio` 文件对方直接能打开，不需要装什么（网页版 app.diagrams.net 免费）。只有要重新导出图片的人才需要装 Desktop。



## 二、图的工具链：两个脚本把 DSL 变成交付物

选型定了不等于能跑。这一节写清谁调用谁、失败怎么看，**因为"图渲染不出来"最常见的表现不是报错，而是正文里安静地留一段 Mermaid 代码——评审时才发现**。

### 2.1 三段链路

```
spec.md（含 ```drawio / ```mermaid / ```wavedrom 块）
   │  ① figrender.py --inline  抽成 fig/*.drawio|*.mmd|*.wavedrom，原地把块换成 ![](fig/x.svg)
   ▼
fig/*.drawio  fig/*.mmd  fig/*.wavedrom   ← 图源，进仓库，可 diff
   │  ② figrender.py fig/      渲染出 fig/*.svg + fig/*.png
   ▼
fig/*.svg（Markdown 引用）   fig/*.png（Word 用）
   │  ③ md2doc.py spec.md      嵌图出 docx / pdf
   ▼
spec.docx  spec.pdf
```

**一条命令跑完 ①+②**：

```bash
python figrender.py spec.md --inline      # 抽源 + 渲染（含 PNG），一步到位
python md2doc.py spec.md                  # 再出 docx + pdf
```

**Word 必须用 PNG**：`python-docx` 不认 SVG，直接塞会抛 `UnrecognizedImageError`。`md2doc.py` 遇到 `.svg` 会自动换成同名 `.png`，没有就现烤一张——所以 `figrender.py` 默认出 PNG，`--no-png` 才关。

### 2.2 装什么、国内怎么装

| 工具 | 装法 | 用途 | 备注 |
|---|---|---|---|
| `draw.io Desktop` | `winget install JGraph.Draw` | **架构框图**导出 SVG/PNG | **装了才能自动导出图片**；跑起来不需要开界面 |
| `wavedrom-cli` | `npm i -g wavedrom-cli` | 拍级波形 | 轻量，无额外依赖 |
| `@mermaid-js/mermaid-cli` | `npm i -g @mermaid-js/mermaid-cli` | 流程图 / 状态机 / 拓扑 | 首次运行下载 Chromium（约 200 MB） |
| Edge 或 Chrome | 系统自带 | SVG→PNG、PDF 打印 | 零安装 |

国内先把源换掉，否则 Chromium 下载容易卡死：

```bash
npm config set registry https://registry.npmmirror.com
```

**draw.io 的导出是纯命令行、无需界面**（Electron 套壳，但 `-x` 模式下不开窗口）：

```bash
drawio -x -f svg -o fig/x.svg fig/x.drawio --disable-gpu          # SVG
drawio -x -f png -s 2 -o fig/x.png fig/x.drawio --disable-gpu     # PNG（2 倍图）
```

`figrender.py` 已封装好，不用手敲这两条。


### 2.3 失败怎么发现

三个脚本都遵循同一条：**失败要吵，不许静默**。

| 情况 | 表现 | 是否放行 |
|---|---|---|
| 图源语法错 | `figrender.py` 打印 `[失败] 文件: 原因`，退出码 1 | 否 |
| 缺 mmdc / wavedrom-cli / draw.io | 启动时打 `[提示] 未找到 …`，对应类型跳过 | 部分 |
| md 里引用的图不存在 | `md2doc.py` 在 Word 里写红字 `[缺图：路径]` + stderr 警告 | 是，但留痕 |
| SVG 没有对应 PNG | 自动用浏览器烤一张；烤不出来才算缺图 | 自动降级 |
| **图源改过但没重渲染** | `md2doc.py` 打 `[过期] xxx：图源改过…交付物里这张图是旧的` | 是，但留痕 |

**最危险的失败是最后一种没被发现**：Word 打开图没了、正文只剩图注，翻的时候看不出缺了什么。所以缺图一律红字留痕，不静默跳过。

**还有一个更隐蔽的失败：图生成出来了，但画的是错的。** 脚本只能保证"文件存在且非空"，画得对不对只能靠人眼。所以每一步出图之后都必须**打开看一眼**——特别是架构图，走线穿过方块、子图跑出边框这类问题，退出码永远是 0。


### 2.4 选型与取名

见 1.1 的选型表。**架构框图用 draw.io，拓扑/状态机用 Mermaid，波形用 WaveDrom。**

`--inline` 生成的编号规则：`fig-<章节号>-<序号>.<ext>`，章节号取标题里的点号段转连字符（`### 3.2.1 状态机` → `fig-3-2-1-01.mmd`），换节序号归零。**编号跟着章节走，插入新节时旧编号不会乱**——这是为了让"见图 3-2-1-01"这种引用稳定。

Mermaid 骨架（状态机，`stateDiagram-v2` 比 `flowchart` 更适合状态——它自带起始/终止标记）：

```
stateDiagram-v2
    [*] --> IDLE
    IDLE --> WR: start & !full
    WR --> WAIT: 写满一拍
    WAIT --> RD: grant
    RD --> IDLE: 计数到阈值
    WAIT --> IDLE: timeout
```

WaveDrom 骨架（valid-ready 反压场景）：

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


## 三、转换链与脚本

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

## 四、常见错误

- **三份手写**：md、docx 各改各的，第一个 ECO 后就分叉。
- **Word 改完当新主**：评审批注直接在 Word 里改正文，改完不回 Markdown——从这版起源文件失效。
- **Markdown 里贴截图不贴源码**：图变成不可追溯的位图，下次改模块名图不跟着变。
- **Word 里手画结构图**：不可 diff，评审看不出两版差异。
- **用 Mermaid 画架构框图**：子图之间有连线时嵌套必失效，子图会跑出父容器。SoC 图一定有跨组连线，所以一定会翻车。架构图用 draw.io。
- **没有 draw.io Desktop 就想导出图片**：CLI 不存在，`.drawio` 永远停在源文件状态，Word 里就是红字缺图。
- **图跑出来了没打开看**：走线穿过方块、子图出界，退出码照样是 0。架构图必须开开眼睛验一遍。
- **改了 `.drawio` 却不重跑 `figrender.py`**：文档里还是旧图，而且 Word 看不出任何异常。看到 `[过期]` 警告就是这件事。
- **改图时加了方块不撑容器**：方块掉到容器框外；撑了内层忘了外层，父容器边框被顶出画布。由内向外撑，每层看一眼。
- **手改 `.svg`/`.png`**：下次渲染就被覆盖。要改改 `.drawio`。
- **用 Mermaid sequenceDiagram 画波形**：画的是消息序列不是电平，反压与采样拍全丢。波形必须 WaveDrom。
- **中文 PDF 走 pandoc 默认引擎**：没配 CJK 字体就是满页方框。走浏览器打印路径。
- **寄存器表 40 行跨 3 页、表头不重复**：转换器已设 `tblHeader`；若换工具生成，先查这一项——没它这表没法读。

