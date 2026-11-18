#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_upstream.py — 把 `my-experts/` 的专家包同步进 DSH bundle（本仓）。

为什么需要脚本：这条同步手工做过五轮，每轮都要盯五件事，漏一样就出事故——
漏换行 → 上游一次 CRLF 事故的复制；漏改页脚 → `顾芯` 这个上游署名胜留在下游；
漏查冒烟词 → 借客户个案导致的信息泄漏复发；漏核条数 → 声明与实际不符；
漏更新版本 → 包与 `package.json` 说两套话。

所以断言写死在脚本里，跑不过就不许提交。任何一条失败都打印"修哪一步"，
不是只报一个 False。

用法：
    python tools/sync_upstream.py --dry-run     # 只检查与报告，不写任何文件
    python tools/sync_upstream.py               # 执行同步并跑全部断言
    python tools/sync_upstream.py --check-only  # 只跑断言（检查当前状态）

上游默认取 `~/.workbuddy/plugins/marketplaces/my-experts/plugins/chip-arch-expert`；
换机器或换目录用 `--upstream <dir>`、`--bundle <dir>` 显式指定。

退出码：有任何断言失败 → 1。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- 路径

# 两种布局都支持：脚本放在 bundle 仓内（`tools/`，推荐 —— 随 git 走、换机器就有），
# 或放在工作区根的 `tools/`（bundle 的兄弟目录，历史布局）。判据是上一级有没有 cordis.patch.yml。
HERE = Path(__file__).resolve().parent
BUNDLE = (HERE.parent if (HERE.parent / "cordis.patch.yml").is_file()
          else HERE.parent / "dsh-chip-design-closure")
# 工作区：`src/`、`out/` 所在层。新机器上通常没有，相关断言自动降级为"仅报告"。
WORKSPACE = BUNDLE.parent
UPSTREAM = Path.home() / ".workbuddy" / "plugins" / "marketplaces" / "my-experts" / "plugins" / "chip-arch-expert"

# 上游署名 → 下游署名（人格里的"顾芯"必须换成"设计收口"）
UP_NAME = "顾芯"
DOWN_NAME = "设计收口"

# 下游正文里不该出现的词。选词原则：**只放"一出现就必然是事故"的**，
# 不放通用前缀。`tx_` / `ic_` / `mst_` 在新版里被有意用作反面示例
# （"`tx_fifo` 使用 8 级同步 FIFO" → 应改成概念名），它们出现在正文是规则的组成部分，
# 拿来当冒烟词只会天天误报，最后没人再看这个脚本。
SMOKE_WORDS = [UP_NAME, "GEN_STOP", "字节级事务启动", "字节引擎规格"]

# 元描述行：讲"曾经犯过这个错"的段落。这类行里出现旧词是被允许的，
# 因为它描述的是历史，不是当前内容。判据是语气而不是词本身。
META_MARKERS = ("已全部改为", "这类前缀", "泄漏", "曾经", "早先", "原来", "历史",
                "当初", "改掉", "修正", "v1.11.0 —", "不许", "禁止")

# 必须是 LF 的文件（上游基线；1.12.0 起）
MUST_LF = [
    ".codebuddy-plugin/plugin.json", "agents/chip-arch-expert.md", "README.md",
    "skills/chip-design/SKILL.md",
    "skills/chip-design/references/arch-budget.md",
    "skills/chip-design/references/fp-vp-generation.md",
    "skills/chip-design/references/ppa-optimization.md",
    "skills/chip-design/references/rtl-checklist.md",
    "skills/chip-design/references/soc-integration.md",
    "skills/chip-design/references/spec-outline.md",
    "skills/chip-design/scripts/spec_lint.py",
]


def rels(root: Path) -> list[str]:
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def norm_lf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def swap_footer(text: str) -> str:
    """把上游人格名换成下游名。三处都要改，漏一处就前功尽弃：

    1. 标题行：`# 数字芯片架构与前端设计专家 - 顾芯`
    2. 正文首位：`顾芯，集成电路行业资深...`（逗号，不是间隔号）
    3. 页脚署名：`<sub>顾芯 · chip-arch-expert vX · 作者 ...`

    只匹配"间隔号/逗号/行尾"这些**人格名所在的语法位置**，不动正文里偶然提到的名字
    （比如讲规则时引用了这个名字本身）。副作用可控，因为下游改名后正文不该再有它。
    """
    t = re.sub(rf"(#\s*[^\n]*?[-—–]\s*){re.escape(UP_NAME)}(\s*$)",
               rf"\g<1>{DOWN_NAME}\2", text, flags=re.M)
    t = re.sub(rf"^{re.escape(UP_NAME)}(?=[，,])", DOWN_NAME, t, flags=re.M)
    t = re.sub(rf"(<sub>\s*){re.escape(UP_NAME)}(\s*·)", rf"\g<1>{DOWN_NAME}\2", t)
    t = re.sub(rf"^({re.escape(UP_NAME)})(\s*·)", rf"{DOWN_NAME}\2", t, flags=re.M)
    return t


# ---------------------------------------------------------------- 断言


class Result:
    def __init__(self) -> None:
        self.items: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.items.append((name, ok, detail))

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.items)

    def report(self) -> None:
        for name, ok, detail in self.items:
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


def assert_no_crlf(root: Path, res: Result) -> None:
    bad = []
    for r in MUST_LF:
        p = root / r
        if not p.exists():
            continue
        n = p.read_bytes().count(b"\r\n")
        if n:
            bad.append(f"{r}({n})")
    res.add("上游基线文件无 CRLF", not bad, "、".join(bad) if bad else f"{len(MUST_LF)} 个文件全 LF")


def assert_smoke_words(root: Path, res: Result, scope: str = "上游") -> None:
    """冒烟词检查。

    对上游：只查"泄漏"类词（`顾芯` 是合法署名，跳过）；元描述行允许出现。
    对下游：`顾芯` 必须零命中（署名已换），其余同上游。
    """
    words = SMOKE_WORDS[1:] if scope == "上游" else SMOKE_WORDS
    hits: list[str] = []
    for r in rels(root):
        if Path(r).suffix in (".png", ".jpg", ".zip"):
            continue
        for ln, line in enumerate(
            (root / r).read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            if any(k in line for k in META_MARKERS):
                continue  # 描述历史的行，不算违规
            for w in words:
                if w in line:
                    hits.append(f"{r}:{ln} {w}")
    res.add(f"冒烟词零命中（{scope}）", not hits,
            "；".join(hits[:6]) if hits else f"{len(words)} 个词全零")


def assert_counts(root: Path, res: Result) -> None:
    """声明条数 = 实际条数。

    数字散布在两处：清单文件实际有 N 条勾选框，而 SKILL / 清单正文里会写"第一节 X 条"。
    断言就是核对这两者。写法容错：清单不要求自称总数（它是单一来源），
    但**凡是在别处声称了条数的地方，必须与实际相符**。
    """
    chk = root / "skills/chip-design/references/review-checklist.md"
    sk = root / "skills/chip-design/SKILL.md"
    if not chk.exists():
        res.add("声明条数 = 实际条数", False, "review-checklist.md 不存在")
        return
    text = chk.read_text(encoding="utf-8")

    def span(a: str, b: str) -> int:
        i = text.find(a)
        if i < 0:
            return -1
        j = text.find(b, i + 1)
        return len(re.findall(r"^\s*- \[ \]", text[i:j if j > 0 else None], re.M))

    n_first = span("## 一、Spec 自身检查", "## 一·B")
    n_b = span("## 一·B", "## 二、")
    n_total = len(re.findall(r"^\s*- \[ \]", text, re.M))

    problems: list[str] = []
    # SKILL 路由表里声称的条数
    if sk.exists():
        s = sk.read_text(encoding="utf-8")
        m = re.search(r"正向\s*(\d+)\s*条\s*/\s*反向\s*(\d+)\s*条", s)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a != n_first:
                problems.append(f"SKILL 称正向 {a} 条，实际第一节 {n_first} 条")
            if b != n_b:
                problems.append(f"SKILL 称反向 {b} 条，实际一·B {n_b} 条")
        else:
            problems.append("SKILL 路由表里找不到「正向 N 条 / 反向 M 条」的声明")

    # 清单正文里若自称总数，必须等于实际
    for m in re.finditer(r"共\s*(\d+)\s*条", text):
        n = int(m.group(1))
        if n not in (n_total, n_first, n_b):
            problems.append(f"清单声称「共 {n} 条」，与实际（总 {n_total} / 正 {n_first} / 反 {n_b}）不符")

    res.add("声明条数 = 实际条数", not problems,
            "；".join(problems) if problems else
            f"总 {n_total} / 第一节 {n_first} / 一·B {n_b}，各处声明一致")


def assert_persona_roundtrip(root: Path, bundle: Path, res: Result) -> None:
    """人格：上游 agents 正文 → 改署名 → 写进 cordis prefix，再读回来必须一致。"""
    src = root / "agents/chip-arch-expert.md"
    patch = bundle / "cordis.patch.yml"
    if not src.exists() or not patch.exists():
        res.add("persona 往返一致", False, "源或 cordis.patch.yml 缺失")
        return
    want = swap_footer(norm_lf(src.read_bytes()).decode("utf-8"))

    text = patch.read_text(encoding="utf-8")
    m = re.search(r"^(\s*)prefix:\s*\|-?\n((?:(?:\1  .*)?\n)+)", text, re.M)
    if not m:
        res.add("persona 往返一致", False, "cordis.patch.yml 里找不到 prefix 块")
        return
    indent = m.group(1) + "  "
    lines = []
    for line in m.group(2).splitlines():
        if line.startswith(indent):
            lines.append(line[len(indent):])
        elif not line.strip():
            lines.append("")
    got = "\n".join(lines).strip()

    # 上游正文去掉 frontmatter 与首尾空行后比对（下游人格没有 frontmatter）
    body = re.sub(r"^---\n.*?\n---\n", "", want, flags=re.S).strip()
    ok = got.strip() == body
    detail = (f"上游 {len(body)} 字符 / 下游 {len(got)} 字符" if not ok
              else f"{len(got)} 字符一致")
    if not ok:
        # 给出第一个不一致位置，便于定位
        for i, (a, b) in enumerate(zip(body, got)):
            if a != b:
                detail += f"；首个差异在第 {i} 字符：上游 {a!r} vs 下游 {b!r}"
                break
    res.add("persona 往返一致", ok, detail)


def assert_skill_bytes(root: Path, bundle: Path, res: Result) -> None:
    """技能文件：逐字节一致，只允许 LF 归一与页脚署名两处差异。"""
    us = root / "skills/chip-design"
    bs = bundle / "skills/chip-design"
    if not us.is_dir() or not bs.is_dir():
        res.add("技能文件逐字节一致", False, "技能目录缺失")
        return
    u, b = set(rels(us)), set(rels(bs))
    only_u, only_b = sorted(u - b), sorted(b - u)
    diffs: list[str] = []
    for r in sorted(u & b):
        a = norm_lf((us / r).read_bytes()).decode("utf-8", "replace")
        c = norm_lf((bs / r).read_bytes()).decode("utf-8", "replace")
        if swap_footer(a) != swap_footer(c):
            diffs.append(r)
    problems = []
    if only_u:
        problems.append(f"下游缺 {len(only_u)} 个：{only_u[:4]}")
    if only_b:
        problems.append(f"下游多 {len(only_b)} 个：{only_b[:4]}")
    if diffs:
        problems.append(f"内容不同：{diffs[:4]}")
    res.add("技能文件逐字节一致（除 LF 与页脚）", not problems,
            "；".join(problems) if problems else f"{len(u & b)} 个文件一致")


def assert_mdmodel_wired(root: Path, bundle: Path, res: Result) -> None:
    """建议项：`src/spec_agent/mdmodel.py` 是否真被接线。

    这条断言不判失败，只报状态——mdmodel 是"孤立模块"，注释写着
    'so every checker works unchanged'，但全库零调用。它的存在容易让人
    以为 md 链路已通，实际是死代码。报出来，避免下一轮又误判。
    """
    md_path = WORKSPACE / "src" / "spec_agent" / "mdmodel.py"
    if not md_path.exists():
        res.add("mdmodel 是否被接线（仅报告）", True, "src/spec_agent/mdmodel.py 不存在")
        return
    callers = []
    for p in (WORKSPACE / "src").rglob("*.py"):
        if p.name == "mdmodel.py":
            continue
        if "mdmodel" in p.read_text(encoding="utf-8", errors="ignore"):
            callers.append(p.relative_to(WORKSPACE).as_posix())
    res.add("mdmodel 是否被接线（仅报告）", True,
            f"调用方 {callers}" if callers else "零调用（孤立模块，勿当作 md 链路已通）")


# ---------------------------------------------------------------- 主流程


def assert_persona_independent(bundle: Path, res: Result) -> None:
    """独立断言：人格块里不许残留上游名。

    这条是补 `persona 往返一致` 的漏洞——往返比对的是"写进去的和读出来的"，
    如果**写进去的内容本身就错**（忘了改名），两头比对照样相等，断言会假通过。
    这一条不看比对，直接对下游文件的内容下判断，所以能抓住那种错。
    """
    patch = bundle / "cordis.patch.yml"
    if not patch.exists():
        res.add("persona 无上游名残留（独立检查）", False, "cordis.patch.yml 不存在")
        return
    txt = patch.read_text(encoding="utf-8")
    hits = [f"L{i}" for i, ln in enumerate(txt.splitlines(), 1) if UP_NAME in ln]
    res.add("persona 无上游名残留（独立检查）", not hits,
            f"残留于 {hits[:6]}" if hits else f"`{UP_NAME}` 零命中")


def assert_downlink_lf(bundle: Path, res: Result) -> None:
    """下游基线文件必须 LF。这两处栽过两次，写死不许绕过。"""
    bad = []
    for r in ("cordis.patch.yml", "package.json"):
        p = bundle / r
        if p.exists() and p.read_bytes().count(b"\r\n"):
            bad.append(f"{r}({p.read_bytes().count(chr(13).encode()+chr(10).encode())})")
    res.add("下游基线文件无 CRLF", not bad, "、".join(bad) if bad else "cordis.patch.yml / package.json 均 LF")


def do_sync(root: Path, bundle: Path) -> None:
    """技能整份替换；人格改署名后写回 prefix；版本号对齐。"""
    us, bs = root / "skills/chip-design", bundle / "skills/chip-design"
    if bs.exists():
        shutil.rmtree(bs)
    shutil.copytree(us, bs)

    # 技能页脚署名
    for p in bs.rglob("*.md"):
        t = norm_lf(p.read_bytes()).decode("utf-8")
        t2 = swap_footer(t)
        if t2 != t:
            p.write_bytes(t2.encode("utf-8"))

    # 人格
    src = root / "agents/chip-arch-expert.md"
    persona = swap_footer(norm_lf(src.read_bytes()).decode("utf-8"))
    persona = re.sub(r"^---\n.*?\n---\n", "", persona, flags=re.S).strip()

    patch = bundle / "cordis.patch.yml"
    text = patch.read_text(encoding="utf-8")
    m = re.search(r"^(\s*)prefix:\s*\|-?\n((?:(?:\1  .*)?\n)+)", text, re.M)
    if not m:
        raise SystemExit("cordis.patch.yml 里找不到 prefix 块，拒绝改写")
    indent = m.group(1) + "  "
    body = "\n".join((indent + ln) if ln.strip() else "" for ln in persona.splitlines())
    text = text[:m.start(2)] + body + "\n" + text[m.end(2):]
    # 强制 LF：Windows 上 write_text 会把 \n 落成 \r\n，而仓库基线是 LF。
    # 这个坑踩过两次（一次上游包、一次这里），所以写回时直接按字节断言。
    patch.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))

    # 版本号
    ver = json.loads((root / ".codebuddy-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
    pj = bundle / "package.json"
    pj_text = pj.read_text(encoding="utf-8")
    pj_text = re.sub(r'("version"\s*:\s*")[^"]+(")', rf"\g<1>{ver}\g<2>", pj_text, count=1)
    pj.write_bytes(pj_text.replace("\r\n", "\n").encode("utf-8"))
    print(f"  已对齐版本：{ver}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="把 my-experts 专家包同步进 DSH bundle")
    ap.add_argument("--dry-run", action="store_true", help="只检查，不写文件")
    ap.add_argument("--check-only", action="store_true", help="只跑断言（当前状态）")
    ap.add_argument("--upstream", default=str(UPSTREAM), help="上游包目录")
    ap.add_argument("--bundle", default=str(BUNDLE), help="下游 bundle 目录")
    args = ap.parse_args(argv)

    root, bundle = Path(args.upstream), Path(args.bundle)
    if not (root / ".codebuddy-plugin/plugin.json").exists():
        print(f"上游不完整：{root}", file=sys.stderr)
        return 1
    if not bundle.exists():
        print(f"下游不存在：{bundle}", file=sys.stderr)
        return 1

    ver = json.loads((root / ".codebuddy-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
    print(f"上游 {root.name} 版本 {ver}")
    print(f"下游 {bundle.name}")

    res = Result()
    assert_no_crlf(root, res)
    assert_smoke_words(root, res, "上游")
    assert_counts(root, res)
    print("\n[同步前：上游自身]")
    res.report()

    if not res.ok:
        print("\n上游自身不合格，先修上游再同步。")
        return 1

    if args.check_only:
        res2 = Result()
        assert_persona_roundtrip(root, bundle, res2)
        assert_persona_independent(bundle, res2)
        assert_skill_bytes(root, bundle, res2)
        assert_downlink_lf(bundle, res2)
        assert_mdmodel_wired(root, bundle, res2)
        print("\n[下游状态]")
        res2.report()
        return 0 if res2.ok else 1

    if not args.dry_run:
        print("\n[同步]")
        do_sync(root, bundle)
    else:
        print("\n[dry-run] 跳过写入")

    res2 = Result()
    assert_persona_roundtrip(root, bundle, res2)
    assert_persona_independent(bundle, res2)
    assert_skill_bytes(root, bundle, res2)
    assert_downlink_lf(bundle, res2)
    assert_mdmodel_wired(root, bundle, res2)
    print("\n[同步后：下游断言]")
    res2.report()
    print()
    print("全部通过。" if res2.ok else "有断言失败，不要提交。")
    return 0 if res2.ok else 1


if __name__ == "__main__":
    sys.exit(main())
