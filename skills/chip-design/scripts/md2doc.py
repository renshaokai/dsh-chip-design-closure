#!/usr/bin/env python3
"""spec 单一源 -> Word / PDF 生成器

Markdown 是唯一可编辑源；docx 与 pdf 都是生成物，不手改。

用法:
    python md2doc.py spec.md                  # 出 spec.docx + spec.pdf
    python md2doc.py spec.md --only docx
    python md2doc.py spec.md --only pdf --html-also

依赖:
    python-docx  (pip install python-docx -i https://mirrors.aliyun.com/pypi/simple/)
    Microsoft Edge 或 Chrome （PDF，走 --headless --print-to-pdf，无需额外安装）
"""
import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------- Markdown 解析

INLINE_BOLD = re.compile(r"\*\*(.+?)\*\*")
INLINE_CODE = re.compile(r"`([^`]+)`")


def parse_blocks(lines):
    """把 md 行流切成块：h1..h6 / table / code / ul / ol / quote / para / hr"""
    blocks, i, n = [], 0, len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()

        if not s:
            i += 1
            continue

        # 代码块
        if s.startswith("```"):
            lang = s[3:].strip()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append(("code", lang, "\n".join(buf)))
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            blocks.append(("h", len(m.group(1)), m.group(2).strip()))
            i += 1
            continue

        # 分隔线
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            blocks.append(("hr",))
            i += 1
            continue

        # 表格：当前行含 | 且下一行是分隔行
        if "|" in s and i + 1 < n and re.match(r"^\s*\|?[\s:\-|]+\|[\s:\-|]*$", lines[i + 1]):
            header = split_row(s)
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(split_row(lines[i].strip()))
                i += 1
            blocks.append(("table", header, rows))
            continue

        # 引用
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            blocks.append(("quote", "\n".join(buf).strip()))
            continue

        # 列表
        if re.match(r"^\s*([-*+]|\d+\.)\s+", line):
            ordered = bool(re.match(r"^\s*\d+\.\s+", line))
            items = []
            while i < n and re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i]):
                items.append(re.sub(r"^\s*([-*+]|\d+\.)\s+", "", lines[i]).strip())
                i += 1
            blocks.append(("ol" if ordered else "ul", items))
            continue

        # 段落
        buf = []
        while i < n and lines[i].strip() and not re.match(
            r"^(#{1,6}\s|```|>|\s*([-*+]|\d+\.)\s)", lines[i]
        ):
            if "|" in lines[i] and i + 1 < n and re.match(r"^\s*\|?[\s:\-|]+\|", lines[i + 1]):
                break
            buf.append(lines[i].strip())
            i += 1
        if buf:
            blocks.append(("para", " ".join(buf)))
        else:
            i += 1
    return blocks


def split_row(s):
    s = s.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


# ---------------------------------------------------------------- Word

def build_docx(blocks, out_path, font_cjk="等线", font_mono="Consolas", title=""):
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor, Cm

    doc = Document()

    # 正文样式：中西文分别设字体，中文必须走 eastAsia 才生效
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), font_cjk)
    st.paragraph_format.space_after = Pt(4)
    st.paragraph_format.line_spacing = 1.25

    for name, size in (("Heading 1", 16), ("Heading 2", 14), ("Heading 3", 12), ("Heading 4", 11)):
        h = doc.styles[name]
        h.font.name = "Calibri"
        h.font.size = Pt(size)
        h.font.bold = True
        h.font.color.rgb = RGBColor(0x1F, 0x1F, 0x1F)
        h.element.rPr.rFonts.set(qn("w:eastAsia"), font_cjk)
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(6)

    # 页边距：A4 常规
    for sec in doc.sections:
        sec.top_margin = Cm(2.2)
        sec.bottom_margin = Cm(2.2)
        sec.left_margin = Cm(2.4)
        sec.right_margin = Cm(2.4)

    def add_inline(par, text):
        """处理 **粗体** 与 `行内代码`"""
        pos = 0
        pattern = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")
        for m in pattern.finditer(text):
            if m.start() > pos:
                par.add_run(text[pos:m.start()])
            if m.group(1):
                r = par.add_run(m.group(1))
                r.bold = True
            else:
                r = par.add_run(m.group(2))
                r.font.name = font_mono
                r.element.rPr.rFonts.set(qn("w:eastAsia"), font_mono)
                r.font.size = Pt(9.5)
            pos = m.end()
        if pos < len(text):
            par.add_run(text[pos:])

    def shade(cell, hexcolor):
        tcPr = cell._tc.get_or_add_tcPr()
        el = OxmlElement("w:shd")
        el.set(qn("w:val"), "clear")
        el.set(qn("w:fill"), hexcolor)
        tcPr.append(el)

    def set_cell_text(cell, text, bold=False, size=9.5):
        cell.text = ""
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.space_before = Pt(1)
        add_inline(p, text)
        for r in p.runs:
            r.font.size = Pt(size)
            if bold:
                r.bold = True

    for b in blocks:
        kind = b[0]

        if kind == "h":
            level, text = b[1], b[2]
            doc.add_heading(text, level=min(level, 4))

        elif kind == "para":
            p = doc.add_paragraph()
            add_inline(p, b[1])

        elif kind == "ul":
            for it in b[1]:
                p = doc.add_paragraph(style="List Bullet")
                p.paragraph_format.space_after = Pt(2)
                add_inline(p, it)

        elif kind == "ol":
            for it in b[1]:
                p = doc.add_paragraph(style="List Number")
                p.paragraph_format.space_after = Pt(2)
                add_inline(p, it)

        elif kind == "quote":
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(18)
            r = p.add_run(b[1])
            r.italic = True
            r.font.size = Pt(10)
            r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

        elif kind == "code":
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(12)
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.line_spacing = 1.0
            # 底纹
            pPr = p._p.get_or_add_pPr()
            el = OxmlElement("w:shd")
            el.set(qn("w:val"), "clear")
            el.set(qn("w:fill"), "F4F4F2")
            pPr.append(el)
            r = p.add_run(b[2])
            r.font.name = font_mono
            r.element.rPr.rFonts.set(qn("w:eastAsia"), font_mono)
            r.font.size = Pt(9)

        elif kind == "table":
            header, rows = b[1], b[2]
            ncol = max(len(header), max((len(r) for r in rows), default=0))
            t = doc.add_table(rows=1, cols=ncol)
            t.style = "Table Grid"
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            t.autofit = True
            for j in range(ncol):
                c = t.rows[0].cells[j]
                set_cell_text(c, header[j] if j < len(header) else "", bold=True)
                shade(c, "E8E8E4")
            # 表头跨页重复
            trPr = t.rows[0]._tr.get_or_add_trPr()
            el = OxmlElement("w:tblHeader")
            el.set(qn("w:val"), "true")
            trPr.append(el)
            for row in rows:
                cells = t.add_row().cells
                for j in range(ncol):
                    set_cell_text(cells[j], row[j] if j < len(row) else "")
            doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # 页脚页码
    footer = doc.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run()
    for instr, kind_ in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind_:
            fld = OxmlElement("w:instrText")
            fld.set(qn("xml:space"), "preserve")
            fld.text = " PAGE "
            run._r.append(fld)
        else:
            fld = OxmlElement("w:fldChar")
            fld.set(qn("w:fldCharType"), instr)
            run._r.append(fld)

    doc.save(out_path)


# ---------------------------------------------------------------- PDF (HTML 中转)

CSS = """
@page { size: A4; margin: 20mm 18mm; }
body { font-family: "Microsoft YaHei","PingFang SC",sans-serif; font-size: 10.5pt;
       line-height: 1.55; color:#1a1a1a; }
h1 { font-size: 17pt; border-bottom: 1.5pt solid #333; padding-bottom: 6px; margin: 0 0 14px; }
h2 { font-size: 14pt; margin: 18px 0 8px; border-left: 3pt solid #534AB7; padding-left: 8px; }
h3 { font-size: 12pt; margin: 14px 0 6px; }
h4 { font-size: 11pt; margin: 12px 0 5px; color:#333; }
p { margin: 5px 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 9pt; }
th, td { border: 0.5pt solid #999; padding: 4px 7px; text-align: left; vertical-align: top; }
th { background: #efefec; font-weight: 600; }
tr { page-break-inside: avoid; }
thead { display: table-header-group; }
pre { background: #f5f5f2; border-left: 2.5pt solid #bbb; padding: 8px 10px;
      font-family: Consolas,"Courier New",monospace; font-size: 8.5pt; line-height: 1.35;
      white-space: pre-wrap; page-break-inside: avoid; }
code { font-family: Consolas,monospace; background:#f0f0ee; padding: 1px 3px; font-size: 9pt; }
blockquote { margin: 8px 0 8px 14px; padding-left: 10px; border-left: 2pt solid #ccc;
             color:#555; font-style: italic; }
ul, ol { margin: 5px 0 5px 0; padding-left: 22px; }
li { margin: 2px 0; }
hr { border: none; border-top: 0.5pt solid #ddd; margin: 14px 0; }
"""


def esc(s):
    return html.escape(s, quote=False)


def inline_md(s):
    s = esc(s)
    s = INLINE_BOLD.sub(r"<strong>\1</strong>", s)
    s = INLINE_CODE.sub(r"<code>\1</code>", s)
    return s


def build_html(blocks, title=""):
    out = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>{esc(title)}</title><style>{CSS}</style></head><body>",
    ]
    for b in blocks:
        kind = b[0]
        if kind == "h":
            lv = min(b[1], 6)
            out.append(f"<h{lv}>{inline_md(b[2])}</h{lv}>")
        elif kind == "para":
            out.append(f"<p>{inline_md(b[1])}</p>")
        elif kind == "ul":
            out.append("<ul>" + "".join(f"<li>{inline_md(x)}</li>" for x in b[1]) + "</ul>")
        elif kind == "ol":
            out.append("<ol>" + "".join(f"<li>{inline_md(x)}</li>" for x in b[1]) + "</ol>")
        elif kind == "quote":
            out.append(f"<blockquote>{inline_md(b[1])}</blockquote>")
        elif kind == "code":
            out.append(f"<pre>{esc(b[2])}</pre>")
        elif kind == "hr":
            out.append("<hr>")
        elif kind == "table":
            header, rows = b[1], b[2]
            ncol = max(len(header), max((len(r) for r in rows), default=0))
            out.append("<table><thead><tr>")
            for j in range(ncol):
                out.append(f"<th>{inline_md(header[j]) if j < len(header) else ''}</th>")
            out.append("</tr></thead><tbody>")
            for r in rows:
                out.append("<tr>" + "".join(
                    f"<td>{inline_md(r[j]) if j < len(r) else ''}</td>" for j in range(ncol)
                ) + "</tr>")
            out.append("</tbody></table>")
    out.append("</body></html>")
    return "\n".join(out)


def find_browser():
    cands = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("microsoft-edge"),
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def build_pdf(html_str, out_path, title=""):
    browser = find_browser()
    if not browser:
        raise RuntimeError("未找到 Edge/Chrome，无法生成 PDF。请安装其一，或改用 --only docx。")
    tmpd = tempfile.mkdtemp(prefix="md2doc_")
    html_path = os.path.join(tmpd, "doc.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_str)
    pdf_abs = os.path.abspath(out_path)
    cmd = [
        browser, "--headless", "--disable-gpu", "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_abs}",
        "file:///" + html_path.replace("\\", "/"),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=180)
    if not os.path.exists(pdf_abs) or os.path.getsize(pdf_abs) < 1000:
        raise RuntimeError("PDF 生成失败：" + (r.stderr.decode("utf-8", "ignore")[:400]))
    shutil.rmtree(tmpd, ignore_errors=True)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Markdown spec 单一源 -> Word / PDF")
    ap.add_argument("src", help="源 Markdown 文件")
    ap.add_argument("-o", "--out", help="输出前缀（默认与源同名）")
    ap.add_argument("--only", choices=["docx", "pdf"], help="只出一种格式")
    ap.add_argument("--html-also", action="store_true", help="同时保留中转 HTML（排查版式用）")
    ap.add_argument("--font", default="等线", help="Word 中文字体，默认等线")
    args = ap.parse_args()

    with open(args.src, encoding="utf-8") as f:
        text = f.read()
    lines = text.splitlines()
    blocks = parse_blocks(lines)

    stem = args.out or os.path.splitext(args.src)[0]
    title = os.path.basename(stem)
    made = []

    if args.only in (None, "docx"):
        p = stem + ".docx"
        build_docx(blocks, p, font_cjk=args.font, title=title)
        made.append(p)

    if args.only in (None, "pdf"):
        h = build_html(blocks, title)
        if args.html_also:
            hp = stem + ".html"
            with open(hp, "w", encoding="utf-8") as f:
                f.write(h)
            made.append(hp)
        p = stem + ".pdf"
        build_pdf(h, p, title)
        made.append(p)

    for p in made:
        print(f"{os.path.getsize(p):>9,} B  {p}")


if __name__ == "__main__":
    main()
