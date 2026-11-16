#!/usr/bin/env python3
"""spec 里的图：DSL 源码 -> SVG / PNG

设计原则（与 delivery-formats.md 同一纪律）：
    图是生成物，DSL 源码才是可维护的。
    所以这里只做一件事：把 fig/*.mmd 与 fig/*.wavedrom 渲染出来，
    不让任何人在 Word 里手画图。

三类图源，按图的性质分工（见 delivery-formats.md 第二节）:
    .mmd        Mermaid    流程图 / 状态机 / 时序关系 / 拓扑草图
    .wavedrom   WaveDrom   拍级波形（有电平、有反压、有时钟沿）
    .drawio     draw.io    架构框图 / 结构框图 / 带容器的层次图  ← 定稿用这个

用法:
    python figrender.py fig/                     # 渲染目录下全部图源
    python figrender.py fig/fig-3-A-02.mmd       # 渲染单个
    python figrender.py spec.md --inline         # 把 md 里的 mermaid/wavedrom 块抽成 fig/ 文件并渲染
    python figrender.py fig/ --png               # 额外出 PNG（Word 老版本友好）

依赖:
    wavedrom-cli   npm i -g wavedrom-cli
    mermaid-cli    npm i -g @mermaid-js/mermaid-cli     （首次运行会下载 Chromium，约 200 MB）
    draw.io        winget install JGraph.Draw           （导出 PNG/SVG 必需，跑起来不需要开界面）
    国内加速:      npm config set registry https://registry.npmmirror.com

退出码: 0 全部成功；1 有图失败（失败清单打印到 stderr，不会静默跳过）
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

FENCE = re.compile(r"^(\s*)```(mermaid|wavedrom|wavedrom-json|json|drawio|drawio-xml)\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def find_cmd(name, fallbacks=()):
    """找可执行文件；npm 全局装的在 Windows 上是 .cmd，shutil.which 能处理。"""
    for c in (name,) + tuple(fallbacks):
        p = shutil.which(c)
        if p:
            return p
    return None


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def render_mermaid(src_path, out_svg, mmdc):
    r = run([mmdc, "-i", src_path, "-o", out_svg, "-b", "white"])
    if r.returncode != 0 or not os.path.exists(out_svg):
        raise RuntimeError((r.stderr or r.stdout or "mmdc 失败").strip()[:500])


def render_wavedrom(src_path, out_svg, wd):
    r = run([wd, "-i", src_path, "-s", out_svg])
    if r.returncode != 0 or not os.path.exists(out_svg):
        raise RuntimeError((r.stderr or r.stdout or "wavedrom-cli 失败").strip()[:500])


def find_drawio():
    """找 draw.io Desktop。它自带无头导出（-x -f png），不需要开界面。"""
    p = find_cmd("drawio", ("draw.io",))
    if p:
        return p
    for c in (
        r"C:\Program Files\draw.io\draw.io.exe",
        r"C:\Program Files (x86)\draw.io\drawio.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\draw.io\draw.io.exe"),
        "/Applications/draw.io.app/Contents/MacOS/draw.io",
        "/usr/bin/drawio",
    ):
        if c and os.path.exists(c):
            return c
    return None


def render_drawio(src_path, out, fmt, drawio):
    """draw.io 导出。fmt: svg / png。

    draw.io 的 CLI 是 Electron 套壳，即使无头也会输出一堆无关日志，
    所以只以「产物是否生成」判成败，不看 returncode。
    """
    cmd = [drawio, "-x", "-f", fmt]
    if fmt == "png":
        cmd += ["-s", "2"]          # 2 倍图，Word 里缩放才不糊
    cmd += ["-o", out, src_path, "--disable-gpu"]
    if os.path.exists(out):
        os.remove(out)              # 防止把上次的旧产物当成功
    run(cmd)
    if not os.path.exists(out) or os.path.getsize(out) == 0:
        raise RuntimeError("drawio 导出失败（先确认 draw.io Desktop 已安装并能打开该文件）")



def svg_size(svg_path, default=(1400, 900)):
    """读 SVG 的 width/height 或 viewBox，用来定截图窗口尺寸。
    不这么做的话 headless 截图会按固定窗口裁，图小的时候四周全是白边。"""
    try:
        head = open(svg_path, encoding="utf-8", errors="ignore").read(4000)
    except Exception:
        return default
    def num(attr):
        m = re.search(attr + r'\s*=\s*"([\d.]+)', head)
        return float(m.group(1)) if m else None
    w, h = num("width"), num("height")
    if not (w and h):
        m = re.search(r'viewBox\s*=\s*"([\d.\s-]+)"', head)
        if m:
            parts = m.group(1).split()
            if len(parts) == 4:
                w, h = float(parts[2]), float(parts[3])
    if not (w and h):
        return default
    # 留一点边距，超过 4000 会被浏览器拒绝布局
    return int(min(w, 4000)) + 40, int(min(h, 4000)) + 40


def svg_to_png(svg_path, png_path):
    """优先用本机浏览器 headless 截图，避免再装一个渲染器。
    这只是给老版本 Word 用的降级路径，失败不算错误。"""
    w, h = svg_size(svg_path)
    url = "file:///" + os.path.abspath(svg_path).replace("\\", "/")
    for exe in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
    ):
        if exe and os.path.exists(exe):
            run([exe, "--headless", "--disable-gpu", "--no-sandbox",
                 "--hide-scrollbars", "--force-device-scale-factor=2",
                 f"--window-size={w},{h}", f"--screenshot={png_path}", url])
            if os.path.exists(png_path):
                return True
    return False


def kind_of(path):
    low = path.lower()
    if low.endswith(".mmd") or low.endswith(".mermaid"):
        return "mermaid"
    if low.endswith(".wavedrom") or low.endswith(".wave.json"):
        return "wavedrom"
    if low.endswith(".drawio") or low.endswith(".drawio.xml"):
        return "drawio"
    return None


def render_one(src_path, outdir, mmdc, wd, want_png, drawio=None):
    k = kind_of(src_path)
    if not k:
        return None
    stem = os.path.splitext(os.path.basename(src_path))[0]
    if stem.endswith(".drawio"):        # xxx.drawio.xml
        stem = stem[:-len(".drawio")]
    out_svg = os.path.join(outdir, stem + ".svg")
    if k == "drawio":
        if not drawio:
            raise RuntimeError("找不到 draw.io Desktop：winget install JGraph.Draw")
        render_drawio(src_path, out_svg, "svg", drawio)
        if want_png:
            render_drawio(src_path, os.path.join(outdir, stem + ".png"), "png", drawio)
        return out_svg
    if k == "mermaid":
        if not mmdc:
            raise RuntimeError("找不到 mmdc：npm i -g @mermaid-js/mermaid-cli")
        render_mermaid(src_path, out_svg, mmdc)
    else:
        if not wd:
            raise RuntimeError("找不到 wavedrom-cli：npm i -g wavedrom-cli")
        # wavedrom-cli 对 .wavedrom 后缀可能不认，检查内容是否合法 JSON
        try:
            json.load(open(src_path, encoding="utf-8"))
        except Exception as e:
            raise RuntimeError(f"WaveDrom 源不是合法 JSON: {e}")
        render_wavedrom(src_path, out_svg, wd)
    if want_png:
        svg_to_png(out_svg, os.path.join(outdir, stem + ".png"))
    return out_svg


def collect(targets):
    out = []
    for t in targets:
        if os.path.isdir(t):
            for f in sorted(os.listdir(t)):
                p = os.path.join(t, f)
                if os.path.isfile(p) and kind_of(p):
                    out.append(p)
        elif os.path.isfile(t) and kind_of(t):
            out.append(t)
    return out


# ---------------------------------------------------------------- 从 md 抽图源

def extract_from_md(md_path, figdir):
    """把 md 里 ```mermaid / ```wavedrom 块抽成 fig/ 下的源文件，
    并把块替换成 ![caption](fig/xxx.ext)。

    幂等：已有同名文件且内容一致就复用，不重复编号。
    返回 (新文本, 生成的源文件列表)。
    """
    with open(md_path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    os.makedirs(figdir, exist_ok=True)
    made, out, i, n = [], [], 0, len(lines)
    sec = "0"  # 当前章节，用于生成 fig-<sec>-NN
    seq = 0

    while i < n:
        line = lines[i]
        mh = HEADING.match(line)
        if mh:
            # 章节号取完整的点号段（"### 3.2.1 状态机" -> "3-2-1"），每节独立编号
            num = re.match(r"^\s*第?\s*([0-9]+(?:\.[0-9]+)*)", mh.group(2))
            if num:
                sec = num.group(1).replace(".", "-")
            seq = 0

        mf = FENCE.match(line)
        if mf:
            indent, lang = mf.group(1), mf.group(2)
            buf, i = [], i + 1
            while i < n and not re.match(r"^\s*```\s*$", lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1  # 跳过结束围栏

            if lang in ("mermaid", "wavedrom", "wavedrom-json", "drawio", "drawio-xml"):
                if lang in ("mermaid",):
                    ext = ".mmd"
                elif lang in ("drawio", "drawio-xml"):
                    ext = ".drawio"
                else:
                    ext = ".wavedrom"
                body = "\n".join(buf).rstrip() + "\n"
                if lang.startswith("wavedrom"):
                    # md 里允许写非严格 JSON（注释/尾逗号），这里不校验，交给渲染器报错
                    pass
                seq += 1
                name = f"fig-{sec}-{seq:02d}{ext}"
                path = os.path.join(figdir, name)
                old = None
                if os.path.exists(path):
                    old = open(path, encoding="utf-8").read()
                if old != body:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(body)
                made.append(path)
                # 找块前面的标题做 caption
                cap = ""
                for back in range(len(out) - 1, max(-1, len(out) - 4), -1):
                    m = re.match(r"^#{3,6}\s+(.*)$", out[back])
                    if m:
                        cap = m.group(1).strip()
                        break
                mddir = os.path.dirname(os.path.abspath(md_path))
                rel_src = os.path.relpath(path, mddir).replace(os.sep, "/")
                rel_out = rel_src[:-len(ext)] + ".svg"   # 正文引用渲染产物
                out.append(f"{indent}![{cap or name}]({rel_out})")
                # 注释写清楚"该改哪个、别改哪个"。图源是可改的，.svg/.png 才是生成物。
                how = "用 draw.io 打开改" if ext == ".drawio" else f"改这个 {ext} 源文件"
                out.append(
                    f"{indent}<!-- 图源：{rel_src}（要改图就{how}，改完重跑 "
                    f"figrender.py 再出文档）· {rel_out} 是渲染产物，别手改 -->")
                continue
            else:
                out.append(line)
                out.extend(buf)
                out.append(lines[i - 1])
                continue

        out.append(line)
        i += 1

    return "\n".join(out), made


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="spec 图源 DSL -> SVG/PNG")
    ap.add_argument("targets", nargs="+", help="图源文件、目录，或（配 --inline）md 文件")
    ap.add_argument("--inline", action="store_true",
                    help="把 md 里的 mermaid/wavedrom 块抽成 fig/ 源文件再渲染（原地改 md）")
    ap.add_argument("--figdir", default="fig", help="--inline 时的图源目录，默认 fig/")
    ap.add_argument("--no-png", action="store_true",
                    help="不出 PNG（默认会出：python-docx 不认 SVG，Word 里必须用 PNG）")
    ap.add_argument("--mmdc", default=None, help="mmdc 路径（默认自动查找）")
    args = ap.parse_args()

    mmdc = args.mmdc or find_cmd("mmdc", ("mermaid-cli",))
    wd = find_cmd("wavedrom-cli", ("wavedrom",))
    drawio = find_drawio()

    need_m = any(kind_of(t) != "wavedrom" for t in args.targets)
    if not mmdc and (not args.inline or True):
        print("[提示] 未找到 mmdc，Mermaid 图会跳过。安装：npm i -g @mermaid-js/mermaid-cli",
              file=sys.stderr)
    if not wd:
        print("[提示] 未找到 wavedrom-cli，波形图会跳过。安装：npm i -g wavedrom-cli",
              file=sys.stderr)
    if not drawio:
        print("[提示] 未找到 draw.io Desktop，.drawio 架构图会跳过。"
              "安装：winget install JGraph.Draw", file=sys.stderr)

    if args.inline:
        for md in args.targets:
            if not md.lower().endswith((".md", ".markdown")):
                continue
            text, made = extract_from_md(md, args.figdir)
            with open(md, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"{md}: 抽出 {len(made)} 张图源 -> {args.figdir}/")
            for p in made:
                print("   ", p)
        targets = [args.figdir]
    else:
        targets = args.targets

    files = collect(targets)
    if not files:
        print("没有找到图源（.mmd / .wavedrom）", file=sys.stderr)
        return 1

    want_png = not args.no_png
    ok, fail = [], []
    for p in files:
        try:
            out = render_one(p, os.path.dirname(os.path.abspath(p)), mmdc, wd, want_png, drawio)
            if out:
                ok.append(out)
                print(f"{os.path.getsize(out):>9,} B  {out}")
        except Exception as e:
            fail.append((p, str(e)))
            print(f"[失败] {p}: {e}", file=sys.stderr)

    if fail:
        print(f"\n{len(fail)} 张失败 / 共 {len(files)} 张", file=sys.stderr)
        return 1
    print(f"\n全部完成：{len(ok)} 张")
    return 0


if __name__ == "__main__":
    sys.exit(main())
