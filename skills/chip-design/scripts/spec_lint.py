#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""spec_lint.py — 设计规格的机械项校验。

定位：review-checklist.md 第一节 / 一·B 里**能机器判**的那批条目的执行器。
清单是权威文本（说为什么），本脚本只负责把它们跑成可定位的结论（说在哪里）。
两者冲突时以清单为准——脚本漏判是脚本的缺陷，不是清单允许。

用法：
    python spec_lint.py spec.md                  # 控制台报告
    python spec_lint.py spec.md --json out.json  # 机读
    python spec_lint.py spec.md --md out.md      # md 报告
    python spec_lint.py spec.md --only R,I       # 只跑指定组
    python spec_lint.py --selftest               # 自检（不需要输入文件）

退出码：有 error → 1；否则 0。警告不判失败——它们大多需要人判。

三条设计约束（改脚本时不要破）：
1. **零第三方依赖、单文件**。它要跟技能包一起分发，不能 import 本仓的 src/。
2. **每条结论带位置**。没有行号与章节路径的 finding 等于观后感。
3. **certain 与 review 分开报**。脚本能确证的（位域重叠、offset 重复）才叫错误；
   近似判断（命名只差一个字母、散文句数）一律进"待人工确认"，不许冒充铁证。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- 规则表

# id: (组, 严重度, certain?, 标题)
RULES: dict[str, tuple[str, str, bool, str]] = {
    # —— S 组：结构与必备件 ——
    "S01": ("S", "error", True,  "八章齐备"),
    "S02": ("S", "warn",  False, "空章节（无内容且未声明不适用）"),
    "S03": ("S", "error", True,  "内容里 TBD 零命中"),
    "S04": ("S", "error", False, "1.0 文档控制区字段齐备"),
    "S05": ("S", "error", False, "1.2.1 编号族总表存在"),
    "S06": ("S", "warn",  False, "1.1 修订记录存在"),
    "S07": ("S", "warn",  False, "1.6 阅读路径存在"),
    "S08": ("S", "error", False, "3.c 决策台账存在且失效条件一列无空"),
    "S09": ("S", "warn",  False, "3.d 可观测出口表存在"),
    "S10": ("S", "error", True,  "6A 与 6B 不同时出现"),
    "S11": ("S", "error", False, "7.1 需求追溯矩阵存在"),
    "S12": ("S", "error", False, "反向档有附录 E 问题清单"),
    "S13": ("S", "warn",  False, "4.4 冲突检查结论存在"),
    # —— R 组：寄存器表 ——
    "R01": ("R", "error", True,  "offset 可解析"),
    "R02": ("R", "warn",  True,  "offset 4 字节对齐"),
    "R03": ("R", "error", True,  "同 offset 命名一致（无重复 offset 不同名）"),
    "R04": ("R", "error", True,  "lsb ≤ msb"),
    "R05": ("R", "error", True,  "msb < 位宽"),
    "R06": ("R", "error", True,  "位域不重叠"),
    "R07": ("R", "error", True,  "非 Reserved 位域有 attr"),
    "R08": ("R", "warn",  True,  "非 Reserved 位域有 reset"),
    "R09": ("R", "error", True,  "同寄存器各行的位宽声明一致"),
    "R10": ("R", "warn",  False, "寄存器名近似（可能是少一个字母的笔误）"),
    "R11": ("R", "error", True,  "寄存器 offset 落在 4.1 声明的段内"),
    "R12": ("R", "error", True,  "4.1 地址段不重叠"),
    # —— I 组：接口表 ——
    "I01": ("I", "error", True,  "端口位宽是数值或参数名"),
    "I02": ("I", "error", True,  "每个信号有时钟域"),
    "I03": ("I", "error", False, "复位表写了极性与同步方式"),
    "I04": ("I", "warn",  True,  "协议接口有通道表"),
    "I05": ("I", "warn",  True,  "AXI 五通道齐全"),
    "I06": ("I", "error", True,  "参数化位宽的参数在 5.1.1 有定义与取值"),
    # —— T 组：文本 ——
    "T01": ("T", "warn",  False, "没有用散文写契约（模糊措辞）"),
    "T02": ("T", "info",  False, "散文段超过三句"),    "T03": ("T", "error", True,  "正文没有语句级内容"),
    "T04": ("T", "warn",  False, "编号引用不悬空（Q/A/REQ/CPL/INV）"),
    # —— C 组：闭环 ——
    "C01": ("C", "warn",  False, "正文 [?Q-xx] 与附录 E 双向对账"),
    "C02": ("C", "info",  False, "证据等级标记存在（反向档）"),
    "C03": ("C", "warn",  False, "As-Built 状态没有暗示契约效力"),
}

GROUPS = {
    "S": "结构与必备件", "R": "寄存器表", "I": "接口表",
    "T": "文本与措辞", "C": "闭环与对账",
}

# ---------------------------------------------------------------- 数据结构


@dataclass
class Table:
    lineno: int
    header: list[str]
    rows: list[tuple[int, list[str]]] = field(default_factory=list)

    def col(self, *keys: str, exclude: tuple[str, ...] = ()) -> int | None:
        for i, h in enumerate(self.header):
            low = (h or "").lower().replace(" ", "").replace("_", "")
            if any(k.replace(" ", "") in low for k in keys) and not any(
                e in low for e in exclude
            ):
                return i
        return None

    def cell(self, row: list[str], i: int | None) -> str:
        if i is None or i >= len(row):
            return ""
        return (row[i] or "").strip()

    @property
    def filled_rows(self) -> list[tuple[int, list[str]]]:
        return [(ln, r) for ln, r in self.rows if any((c or "").strip() for c in r)]


@dataclass
class Section:
    level: int
    title: str
    lineno: int
    path: list[str] = field(default_factory=list)
    paras: list[tuple[int, str, bool]] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    images: int = 0

    @property
    def label(self) -> str:
        """报告里用的短定位：标题去掉反引号注释。"""
        t = re.sub(r"`[^`]*`", "", self.title).strip()
        return t[:36] if len(t) > 36 else t


@dataclass
class Doc:
    file: str
    lines: list[str]
    sections: list[Section]
    _owner: dict[int, Section] | None = field(default=None, repr=False, compare=False)

    def body_sections(self) -> list[Section]:
        return [s for s in self.sections if s.level >= 1]

    @property
    def owner(self) -> dict[int, "Section"]:
        """行号 → 所属节（最近的、起始行不大于该行的节）。"""
        if self._owner is None:
            idx: dict[int, Section] = {}
            starts = {s.lineno: s for s in self.sections if s.lineno}
            cur: Section | None = None
            for i in range(1, len(self.lines) + 1):
                if i in starts:
                    cur = starts[i]
                if cur is not None:
                    idx[i] = cur
            self._owner = idx
        return self._owner

    def section_at(self, lineno: int) -> Section | None:
        return self.owner.get(lineno)

    def in_instruction(self, lineno: int) -> bool:
        """该行是否落在"讲解规矩"的段落里（模板使用说明等）。"""
        s = self.section_at(lineno)
        while s is not None and s.level > 0:
            if _is_instruction(s):
                return True
            parent = None
            for cand in self.sections:
                if cand.level < s.level and cand.lineno < s.lineno:
                    parent = cand
            s = parent
        return False

    def subtree_has_content(self, sec: Section) -> bool:
        """本节或其后代是否有实际内容。有子节且子节有内容的父节不算空。"""
        if any(t for _, t, _ in sec.paras) or any(t.filled_rows for t in sec.tables) or sec.images:
            return True
        # 代码块、行间说明也算内容
        end = len(self.lines) + 1
        for s in self.sections:
            if s.lineno > sec.lineno and s.level <= sec.level:
                end = s.lineno
                break
        for i in range(sec.lineno + 1, min(end, len(self.lines) + 1)):
            line = self.lines[i - 1].strip()
            if line and not HEAD.match(line) and not line.startswith("|"):
                return True
        # 子节有内容则父节不算空
        for s in self.sections:
            if s.lineno > sec.lineno and s.level > sec.level:
                if any(t for _, t, _ in s.paras) or any(t.filled_rows for t in s.tables) or s.images:
                    return True
        return False

    def find(self, *keys: str) -> Section | None:
        """按标题关键字找节，返回第一个命中的。"""
        for s in self.sections:
            t = s.title
            if all(k in t for k in keys):
                return s
        return None

    def find_all(self, *keys: str) -> list[Section]:
        return [s for s in self.sections if all(k in s.title for k in keys)]


@dataclass
class Issue:
    rule: str
    line: int
    sec: str
    target: str
    detail: str

    @property
    def group(self) -> str:
        return RULES[self.rule][0]

    @property
    def sev(self) -> str:
        return RULES[self.rule][1]

    @property
    def certain(self) -> bool:
        return RULES[self.rule][2]

    def as_dict(self) -> dict:
        return {
            "rule": self.rule, "group": self.group, "sev": self.sev,
            "certain": self.certain, "line": self.line, "section": self.sec,
            "target": self.target, "detail": self.detail,
            "title": RULES[self.rule][3],
        }


# ---------------------------------------------------------------- 解析

HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def _is_sep(cells: list[str]) -> bool:
    vals = [c.strip() for c in cells if c.strip()]
    if not vals:
        return False
    return all(re.fullmatch(r":?-{1,}:?", v) for v in vals)


def parse(path: str) -> Doc:
    raw = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    root = Section(0, "", 0, [], [], [], 0)
    secs = [root]
    cur = root
    n = len(raw)
    i = 0
    in_fence = False
    buf: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        text = " ".join(t for _, t in buf).strip()
        if text:
            cur.paras.append((buf[0][0], text, bool(LIST.match(buf[0][1]))))
        buf = []

    while i < n:
        line, ln = raw[i], i + 1
        m = FENCE.match(line)
        if m:
            flush()
            in_fence = not in_fence
            i += 1
            continue
        if in_fence:
            i += 1
            continue

        h = HEAD.match(line)
        if h:
            flush()
            cur = Section(len(h.group(1)), h.group(2).strip(), ln)
            secs.append(cur)
            i += 1
            continue

        if line.strip().startswith("|"):
            flush()
            tbl = Table(ln, [])
            first = True
            while i < n and raw[i].strip().startswith("|"):
                cells = [c.strip() for c in raw[i].strip().strip("|").split("|")]
                if first:
                    tbl.header = cells
                    first = False
                elif _is_sep(cells):
                    pass
                else:
                    tbl.rows.append((i + 1, cells))
                i += 1
            cur.tables.append(tbl)
            continue

        cur.images += line.count("![")
        if line.strip():
            buf.append((ln, line.strip()))
        else:
            flush()
        i += 1
    flush()

    stack: list[tuple[int, str]] = []
    for s in secs:
        if s.level == 0:
            s.path = []
            continue
        stack = [x for x in stack if x[0] < s.level]
        stack.append((s.level, s.title))
        s.path = [t for _, t in stack]
    return Doc(path, raw, secs)


# ---------------------------------------------------------------- 提取器

NUM_RE = re.compile(r"^(?:0x)?[0-9A-Fa-f]+$")
RESERVED = {"reserved", "rsvd", "-", "", "—", "保留"}


def parse_offset(text: str) -> int | None:
    t = (text or "").strip().lower()
    t = t.replace("_", "")
    if t.endswith("h"):
        t = t[:-1]
        try:
            return int(t, 16)
        except ValueError:
            return None
    if t.startswith("0x"):
        try:
            return int(t[2:], 16)
        except ValueError:
            return None
    if re.fullmatch(r"\d+", t):
        return int(t)
    return None


def parse_bits_val(text: str) -> int | None:
    t = (text or "").strip()
    if re.fullmatch(r"\d+", t):
        return int(t)
    return None


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


@dataclass
class Reg:
    offset: int | None
    offset_raw: str
    name: str
    bits: int | None
    lineno: int
    fields: list[dict] = field(default_factory=list)


def extract_registers(doc: Doc) -> tuple[list[Reg], list[str]]:
    """按模板 4.2 的宽表格式聚合：(offset, name) 相同的连续行视为同一寄存器的多个位域。

    同时兼容窄表（Bit / Field / Attr）与只有 offset+name 的汇总表。
    返回 (寄存器列表, 跳过的表说明)。
    """
    regs: list[Reg] = []
    index: dict[tuple[int | None, str], Reg] = {}
    notes: list[str] = []

    for sec in doc.sections:
        for tbl in sec.tables:
            i_off = tbl.col("offset", "地址")
            i_name = tbl.col("name", "寄存器名", "reg")
            i_msb = tbl.col("msb") if tbl.col("msb") is not None else tbl.col("高位")
            i_lsb = tbl.col("lsb") if tbl.col("lsb") is not None else tbl.col("低位")
            i_bit = tbl.col("bit") if i_msb is None else None
            i_field = tbl.col("field", "位域", "字段", exclude=("bits", "位宽"))
            i_bits = tbl.col("bits", "位宽", exclude=("field",))
            i_attr = tbl.col("attr", "属性")
            i_reset = tbl.col("reset", "复位", "deflt", "default")

            if i_off is None or i_name is None:
                continue
            if i_msb is None and i_lsb is None and i_bit is None and i_field is None:
                # 只有 offset + name：汇总表，不参与位域检查
                continue

            prev_off: int | None = None
            prev_off_raw = ""
            prev_name = ""
            for ln, row in tbl.filled_rows:
                off_raw = tbl.cell(row, i_off)
                name = tbl.cell(row, i_name)
                if not off_raw and prev_off_raw:
                    off_raw = prev_off_raw
                if not name and prev_name:
                    name = prev_name
                if not name:
                    continue
                off = parse_offset(off_raw)
                bits = parse_bits_val(tbl.cell(row, i_bits))
                key = (off, norm_name(name))
                reg = index.get(key)
                if reg is None:
                    reg = Reg(off, off_raw, name, bits, ln)
                    index[key] = reg
                    regs.append(reg)
                if bits is not None and reg.bits is None:
                    reg.bits = bits

                f: dict = {"lineno": ln, "name": "", "msb": None, "lsb": None,
                           "attr": "", "reset": "", "bits": bits}
                if i_field is not None:
                    f["name"] = tbl.cell(row, i_field)
                if i_msb is not None and i_lsb is not None:
                    msb, lsb = tbl.cell(row, i_msb), tbl.cell(row, i_lsb)
                    f["msb"] = int(msb) if re.fullmatch(r"\d+", msb) else None
                    f["lsb"] = int(lsb) if re.fullmatch(r"\d+", lsb) else None
                elif i_bit is not None:
                    bit = tbl.cell(row, i_bit)
                    mm = re.search(r"\[?\s*(\d+)\s*(?::\s*(\d+))?\s*\]?", bit)
                    if mm:
                        a = int(mm.group(1))
                        b = int(mm.group(2)) if mm.group(2) else a
                        f["msb"], f["lsb"] = max(a, b), min(a, b)
                f["attr"] = tbl.cell(row, i_attr)
                f["reset"] = tbl.cell(row, i_reset)
                reg.fields.append(f)

                prev_off, prev_off_raw, prev_name = off, off_raw, name

    if not regs:
        notes.append("未找到带位域的寄存器表（需 offset + name + msb/lsb 或 bit 列）")
    return regs, notes


def extract_segments(doc: Doc) -> list[tuple[int, int, int, str]]:
    """读 4.1 地址段表：(start, end_inclusive, lineno, name)。"""
    segs: list[tuple[int, int, int, str]] = []
    for sec in doc.sections:
        if not ("段" in sec.title or "地址分配" in sec.title or "4.1" in sec.title):
            continue
        for tbl in sec.tables:
            i_s = tbl.col("起始", "start", "begin")
            i_e = tbl.col("结束", "end")
            i_n = tbl.col("段名", "段", "name")
            if i_s is None or i_e is None:
                continue
            for ln, row in tbl.filled_rows:
                s = parse_offset(tbl.cell(row, i_s))
                e = parse_offset(tbl.cell(row, i_e))
                if s is None or e is None:
                    continue
                segs.append((s, e, ln, tbl.cell(row, i_n) if i_n is not None else ""))
    return segs


# ---------------------------------------------------------------- S 组规则

REQUIRED_CHAPTERS = ["文档信息", "功能描述", "架构设计", "寄存器", "接口定义",
                     "验证方案", "闭环", "可测性"]

# 讲解规矩的段落不是被检查的对象。模板与规范文档里大量这类文字，
# 若不排除，lint 会把"禁止写 X"判成"写了 X"——这是最容易让工具失去信任的误报。
INSTRUCTION_TITLES = ("模板使用说明", "使用说明", "交付前删除", "本节说明",
                      "怎么用", "填写说明", "写法说明")
DENY_WORDS = ("零命中", "零出现", "禁止", "不许", "不允许", "不写", "别写",
              "三种替代", "错误写法", "反面教材", "只写一处", "不在这里重抄",
              "判据", "规矩", "纪律", "本节只列", "自检时")
# 规则行的判定要**窄**，不能宽。宽了会把正常内容句一起跳过，检查就静默失效了
# ——那比误报更糟：误报看得见，漏判看不见。
# 所以这里只认"明确在谈怎么写文档"的词，不认"必须 / 应 / 须"这类规范动词：
# 规范动词出现在正文里是契约本身，恰恰是要检查的对象。


def _is_instruction(sec: Section) -> bool:
    return any(k in sec.title for k in INSTRUCTION_TITLES)


def _is_rule_line(text: str) -> bool:
    return any(d in text for d in DENY_WORDS)



def check_structure(doc: Doc) -> list[Issue]:
    out: list[Issue] = []
    heads = doc.body_sections()
    titles = " ".join(s.title for s in heads)

    # S01 八章齐备
    for ch in REQUIRED_CHAPTERS:
        if ch not in titles:
            out.append(Issue("S01", 0, "全文", f"第{REQUIRED_CHAPTERS.index(ch)+1}章",
                             f"未找到标题含「{ch}」的章节；裁掉的章节要在 1.3 记原因"))

    # S02 空章节（有子节内容的父节不算空；模板里的占位空节是设计如此，不判）
    is_template = doc.find("模板使用说明") is not None or doc.find("交付前删除") is not None
    for s in heads:
        if is_template or s.level < 2 or not s.title:
            continue
        if doc.subtree_has_content(s):
            continue
        tail = " ".join(t for _, t, _ in s.paras).lower()
        if any(k in tail for k in ("不适用", "无内容", "裁", "n/a", "不涉及")):
            continue
        out.append(Issue("S02", s.lineno, s.label, s.label,
                         "标题下没有任何段落、表格或图；确实不适用就写「本模块不适用」并给理由"))

    # S03 TBD 零命中（排除讲规矩的段落）
    deny = ("零命中", "零出现", "禁止", "不许", "不得", "不允许", "三种替代", "不含",
            "不写", "不是", "而非", "自检")
    for i, line in enumerate(doc.lines, 1):
        if "TBD" not in line:
            continue
        if any(d in line for d in deny):
            continue
        if doc.in_instruction(i):
            continue
        out.append(Issue("S03", i, "", "TBD",
                         "内容里出现了裸 TBD；应改「本模块不适用」/「TBC－见 Q-xx」/「由 XX 文档给出」"))

    # S04 文档控制区
    sec = doc.find("文档控制")
    if sec is None:
        out.append(Issue("S04", 0, "1.0", "文档控制", "没有 1.0 文档控制区"))
    else:
        blob = " ".join(t for _, t, _ in sec.paras)
        for tbl in sec.tables:
            blob += " " + " ".join(c for _, r in tbl.rows for c in r)
            blob += " " + " ".join(tbl.header)
        for key in ("编号", "密级", "状态", "生效日期", "主笔", "复核", "批准", "分发"):
            if key not in blob:
                out.append(Issue("S04", sec.lineno, sec.label, key,
                                 f"文档控制区缺「{key}」"))

    # S05 / S06 / S07 / S13 存在性
    for rid, keys, hint in (
        ("S05", ("编号族",), "1.2.1 编号族总表"),
        ("S06", ("修订记录",), "1.1 修订记录"),
        ("S07", ("阅读路径",), "1.6 阅读路径与代码地图"),
        ("S13", ("冲突检查",), "4.4 冲突检查结论"),
    ):
        if doc.find(*keys) is None:
            out.append(Issue(rid, 0, "", hint, f"未找到「{hint}」"))

    # S08 决策台账 + 失效条件列无空（只对已填决策的行判空）
    sec = doc.find("决策台账")
    if sec is None:
        out.append(Issue("S08", 0, "3.c", "决策台账", "没有 3.c 关键决策台账"))
    else:
        for tbl in sec.tables:
            i = tbl.col("失效条件")
            i_dec = tbl.col("决策")
            if i is None:
                out.append(Issue("S08", tbl.lineno, sec.label, "失效条件",
                                 "决策台账没有「失效条件」列；这一列是台账的全部价值"))
                continue
            for ln, row in tbl.filled_rows:
                filled_dec = bool((row[i_dec] if i_dec is not None and i_dec < len(row) else "").strip())
                blank = not (row[i] if i < len(row) else "").strip()
                if not blank:
                    continue
                if i_dec is not None and not filled_dec:
                    continue  # 整行未填的占位行，不是漏填
                nm = (row[0] or "").strip() or "?"
                out.append(Issue("S08", ln, sec.label, nm,
                                 "失效条件为空；三个月后没人敢动这条决策"))

    # S09 可观测出口
    if doc.find("可观测") is None:
        out.append(Issue("S09", 0, "3.d", "可观测出口", "没有 3.d 内部状态的可观测出口"))

    # S10 6A / 6B 二选一（模板本身两种都排了版，标注清楚即不算错；只在两节都有实内容时报）
    has_a = doc.find("6A") is not None
    has_b = doc.find("6B") is not None
    if has_a and has_b:
        sa, sb = doc.find("6A"), doc.find("6B")
        real_a = sum(len(t.filled_rows) for t in sa.tables) + len(sa.paras)
        real_b = sum(len(t.filled_rows) for t in sb.tables) + len(sb.paras)
        if real_a > 2 and real_b > 2:
            out.append(Issue("S10", sb.lineno, "第6章", "6A/6B",
                             "6A 与 6B 都写了实内容；正向与反向只能二选一，"
                             "并存会让读者不知道以哪份为基线"))

    # S11 追溯矩阵
    if doc.find("追溯") is None:
        out.append(Issue("S11", 0, "7.1", "追溯矩阵", "没有 7.1 需求追溯矩阵"))

    # S12 反向档要有附录 E
    is_asbuilt = has_b or "as-built" in titles.lower() or "反推" in titles
    if is_asbuilt and doc.find("附录 E") is None and doc.find("问题清单") is None:
        out.append(Issue("S12", 0, "附录E", "问题清单",
                         "看起来是反向档，但没有附录 E 问题清单；反向文档没有它等于没查"))
    return out


# ---------------------------------------------------------------- R 组规则


def _similar(a: str, b: str) -> bool:
    if a == b:
        return False
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True  # 只差下划线 / 大小写
    if abs(len(na) - len(nb)) > 2:
        return False
    short, long = sorted([na, nb], key=len)
    # 少一个字母 / 多一个字母 / 替换一个字母
    if len(long) - len(short) == 1:
        for k in range(len(long)):
            if long[:k] + long[k + 1:] == short:
                return True
    return False


def check_registers(doc: Doc) -> list[Issue]:
    out: list[Issue] = []
    regs, _ = extract_registers(doc)
    segs = extract_segments(doc)

    # R12 段不重叠
    ordered = sorted(segs, key=lambda x: x[0])
    for a, b in zip(ordered, ordered[1:]):
        if b[0] <= a[1]:
            out.append(Issue("R12", b[2], "4.1", f"{a[3]} / {b[3]}",
                             f"段 [{a[0]:#x},{a[1]:#x}] 与 [{b[0]:#x},{b[1]:#x}] 重叠"))

    seen_offset: dict[int, Reg] = {}
    for r in regs:
        sec = "4.2"
        # R01
        if r.offset is None:
            out.append(Issue("R01", r.lineno, sec, r.name or "?",
                             f"offset 无法解析：{r.offset_raw!r}"))
            continue
        # R02
        if r.offset % 4:
            out.append(Issue("R02", r.lineno, sec, r.name,
                             f"offset {r.offset:#x} 未按 4 字节对齐"))
        # R03
        prev = seen_offset.get(r.offset)
        if prev is not None and norm_name(prev.name) != norm_name(r.name):
            out.append(Issue("R03", r.lineno, sec, f"{r.offset:#x}",
                             f"同一 offset 出现两个名字：{prev.name}（L{prev.lineno}）与 {r.name}"))
        else:
            seen_offset.setdefault(r.offset, r)
        # R11 段外地址
        if segs and not any(s <= r.offset <= e for s, e, _, _ in segs):
            out.append(Issue("R11", r.lineno, sec, r.name,
                             f"offset {r.offset:#x} 不在 4.1 声明的任何段内"))

        width = r.bits or 32
        occ: list[tuple[int, int, str]] = []
        for f in r.fields:
            tag = f"{r.name}.{f['name'] or '?'}"
            # R09 位宽声明一致
            if f["bits"] is not None and r.bits is not None and f["bits"] != r.bits:
                out.append(Issue("R09", f["lineno"], sec, tag,
                                 f"位置声明 {f['bits']} 位，与同寄存器的 {r.bits} 位不一致"))
            msb, lsb = f["msb"], f["lsb"]
            if msb is None or lsb is None:
                if f["name"] and f["name"].strip().lower() not in RESERVED:
                    out.append(Issue("R04", f["lineno"], sec, tag,
                                     "位域位置无法解析（msb/lsb 缺失或非数字）"))
                continue
            # R04
            if lsb > msb:
                out.append(Issue("R04", f["lineno"], sec, tag, f"lsb({lsb}) > msb({msb})"))
            # R05
            if msb > width - 1:
                out.append(Issue("R05", f["lineno"], sec, tag,
                                 f"msb {msb} 超出 {width} 位寄存器范围"))
            # R07 / R08
            if (f["name"] or "").strip().lower() not in RESERVED and f["name"]:
                if not f["attr"]:
                    out.append(Issue("R07", f["lineno"], sec, tag, "非 Reserved 位域缺 attr"))
                if not f["reset"]:
                    out.append(Issue("R08", f["lineno"], sec, tag, "非 Reserved 位域缺 reset"))
            occ.append((min(lsb, msb), max(lsb, msb), f["name"] or "?"))

        # R06 重叠
        for i in range(len(occ)):
            for j in range(i + 1, len(occ)):
                a, b = occ[i], occ[j]
                if max(a[0], b[0]) <= min(a[1], b[1]):
                    out.append(Issue("R06", r.lineno, sec, r.name,
                                     f"{a[2]}[{a[1]}:{a[0]}] 与 {b[2]}[{b[1]}:{b[0]}] 重叠"
                                     "（若为同一位域的多种视图，需在表内加注）"))

    # R10 命名近似
    names = [r for r in regs if r.name]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if _similar(names[i].name, names[j].name):
                out.append(Issue("R10", names[j].lineno, "4.2",
                                 f"{names[i].name} / {names[j].name}",
                                 f"两个寄存器名只差字母（L{names[i].lineno} 与 L{names[j].lineno}）；"
                                 "确认是不同寄存器还是少一个字母"))
    return out


# ---------------------------------------------------------------- I 组规则


def check_interfaces(doc: Doc) -> list[Issue]:
    out: list[Issue] = []
    ports: list[Table] = []
    for sec in doc.sections:
        for tbl in sec.tables:
            i_sig = tbl.col("signal", "信号")
            i_w = tbl.col("width", "位宽")
            i_clk = tbl.col("clockdomain", "时钟域", "clock", "时钟")
            if i_sig is not None and i_w is not None:
                ports.append(tbl)
                for ln, row in tbl.filled_rows:
                    sig = tbl.cell(row, i_sig)
                    if not sig:
                        continue
                    w = tbl.cell(row, i_w)
                    # I01
                    if not w or w in ("-", "—", "N", "n", "TBD"):
                        out.append(Issue("I01", ln, sec.label, sig,
                                         f"位宽写成 {w!r}；应给数值或参数名+默认值"))
                    # I02
                    if i_clk is None:
                        out.append(Issue("I02", ln, sec.label, sig, "端口表没有时钟域列"))
                    elif not tbl.cell(row, i_clk):
                        out.append(Issue("I02", ln, sec.label, sig, "该信号没写时钟域"))
                    # I06 参数化位宽要在 5.1.1 有定义
                    if w and not re.fullmatch(r"\d+", w):
                        ident = re.search(r"[A-Za-z_][A-Za-z0-9_]*", w)
                        if ident and not _param_defined(doc, ident.group(0)):
                            out.append(Issue("I06", ln, sec.label, sig,
                                             f"位宽用了 {ident.group(0)}，但 5.1.1 参数表里没有它的定义与取值"))

    # I03 复位表
    reset_tables = [t for s in doc.sections for t in s.tables if t.col("极性", "polarity") is not None]
    for tbl in reset_tables:
        i_pol = tbl.col("极性", "polarity")
        i_sync = tbl.col("同步", "sync", "异步")
        for ln, row in tbl.filled_rows:
            if not (row[i_pol] if i_pol < len(row) else "").strip():
                out.append(Issue("I03", ln, "5.3", row[0] or "?",
                                 "复位极性未写（高有效 / 低有效）"))
            if i_sync is None:
                out.append(Issue("I03", tbl.lineno, "5.3", "复位表", "没有同步/异步列"))
                break
            if not (row[i_sync] if i_sync < len(row) else "").strip():
                out.append(Issue("I03", ln, "5.3", row[0] or "?", "同步方式未写"))

    # I04 / I05 协议通道表
    protos = set()
    for tbl in ports:
        i_p = tbl.col("protocol", "协议")
        if i_p is None:
            continue
        for _, row in tbl.filled_rows:
            v = (row[i_p] if i_p < len(row) else "").strip().upper()
            for name in ("AXI", "AHB", "APB"):
                if name in v:
                    protos.add(name)
    if protos:
        ch_tables = [t for s in doc.sections for t in s.tables if t.col("通道", "channel") is not None]
        if not ch_tables:
            out.append(Issue("I04", 0, "5.1.2", "/".join(sorted(protos)),
                             "端口表声明了协议接口，但没有 5.1.2 通道表（方向/位宽/outstanding）"))
        else:
            covered = set()
            for t in ch_tables:
                i_c = t.col("通道", "channel")
                for _, row in t.filled_rows:
                    v = (row[i_c] if i_c < len(row) else "").strip().upper()
                    covered.add(re.sub(r"[^A-Z]", "", v))
            if "AXI" in protos:
                for ch in ("AW", "W", "B", "AR", "R"):
                    if ch not in covered:
                        out.append(Issue("I05", 0, "5.1.2", ch,
                                         f"AXI 缺 {ch} 通道行"))
    return out


def _param_defined(doc: Doc, ident: str) -> bool:
    for sec in doc.sections:
        for tbl in sec.tables:
            i = tbl.col("参数", "param")
            if i is None:
                continue
            for _, row in tbl.filled_rows:
                if ident in " ".join(row):
                    return True
    return False


# ---------------------------------------------------------------- T / C 组

VAGUE = ("适当的时候", "在适当的时候", "较快", "尽可能", "若干拍", "视情况",
         "一般来说", "基本上", "应该是", "大概是")
STMT = re.compile(r"\balways\s*@|\bassign\s+\w+\s*=|\d+'[bhd][0-9a-fA-F]+|\bcasez?\s*\(")
# 顺序有讲究：FP 必须排在 F 前，否则 FP-01 会被截成 F。
REF = re.compile(r"\b(FP|VP|REQ|CPL|INV|F|Q|A|D|L)-(\d{1,4})\b")
SENT = re.compile(r"[。！？]")
FAMILY = re.compile(r"\b(FP|VP|REQ|CPL|INV|F|Q|A|D|L)-")


def check_text(doc: Doc) -> list[Issue]:
    out: list[Issue] = []
    allow = ("职责", "跳转原理", "异常", "说明")

    for sec in doc.sections:
        if _is_instruction(sec):
            continue
        for ln, text, is_list in sec.paras:
            rule_line = _is_rule_line(text)
            # T01 模糊措辞（讲规矩的段落里出现是在举例，不算）
            if not rule_line:
                for w in VAGUE:
                    if w in text:
                        out.append(Issue("T01", ln, sec.label, w,
                                         f"「{w}」不是可核对的契约；改成拍数/条件/数值"))
                        break
            # T02 散文长度（讲规矩的段落与模板占位不算）
            if not is_list and not rule_line and not any(a in sec.title for a in allow):
                n = len([x for x in SENT.split(text) if x.strip()])
                if n > 3:
                    out.append(Issue("T02", ln, sec.label, f"{n} 句",
                                     "一段超过三句；通常是该拆表，或决策没定"))
            # T03 语句级（同上：规则条文里引用代码是说明，不是写了代码）
            if not rule_line:
                for m in STMT.finditer(text):
                    out.append(Issue("T03", ln, sec.label, m.group(0)[:24],
                                     "正文出现语句级内容；纵向止于决策层"))
                    break

    # T04 引用悬空（只查编号族确实建了总表的情况；没建是 S05 的事，不重复报）
    defined = _numbering_prefixes(doc)
    if defined:
        for i, line in enumerate(doc.lines, 1):
            if doc.in_instruction(i) or _is_rule_line(line):
                continue
            for m in REF.finditer(line):
                if m.group(1) not in defined:
                    out.append(Issue("T04", i, "", m.group(0),
                                     f"{m.group(0)} 的编号族「{m.group(1)}」不在 1.2.1 总表里"))
                    break
    return out


def _numbering_prefixes(doc: Doc) -> set[str]:
    """读 1.2.1 编号族总表，返回其中定义过的编号族前缀。

    总表里两种写法都有：前缀列写 `F-xx`，也有写 `Q` / `` `Q-xx` `` 的。
    所以既认"前缀-数字"，也认单独出现的前缀词（用空格或反引号包着）。
    """
    sec = doc.find("编号族")
    if sec is None:
        return set()
    cell_texts: list[str] = [t for _, t, _ in sec.paras]
    for tbl in sec.tables:
        cell_texts.extend(tbl.header)
        for _, r in tbl.rows:
            cell_texts.extend(r)
    blob = "\n".join(cell_texts)
    found = set(FAMILY.findall(blob))
    # 前缀列单独出现的前缀（如 `| Q | 问题 |`）
    for cell in cell_texts:
        for tok in re.findall(r"`?([A-Z]{1,3})`?", cell):
            if tok in {"FP", "VP", "REQ", "CPL", "INV", "F", "Q", "A", "D", "L"}:
                found.add(tok)
    return found


def check_closure(doc: Doc) -> list[Issue]:
    out: list[Issue] = []
    # C01 正文 [?Q-xx] 与附录 E 对账
    in_body = set()
    for i, line in enumerate(doc.lines, 1):
        for m in re.finditer(r"\[\?(Q-\d+)\]", line):
            in_body.add(m.group(1))
    if in_body:
        sec = doc.find("附录 E") or doc.find("问题清单")
        if sec is None:
            out.append(Issue("C01", 0, "附录E", f"{len(in_body)} 条",
                             "正文引用了问题编号，但没有附录 E 问题清单"))
        else:
            blob = " ".join(t for _, t, _ in sec.paras)
            for tbl in sec.tables:
                blob += " " + " ".join(c for _, r in tbl.rows for c in r)
            for q in sorted(in_body):
                if q not in blob:
                    out.append(Issue("C01", sec.lineno, sec.label, q,
                                     f"正文引用 {q}，附录 E 里没有这一条"))

    # C02 反向档要有证据等级
    titles = " ".join(s.title for s in doc.sections).lower()
    is_asbuilt = "6b" in titles or "as-built" in titles or "反推" in titles
    if is_asbuilt:
        whole = "\n".join(doc.lines)
        if "inferred" not in whole or "measured" not in whole:
            out.append(Issue("C02", 0, "全文", "measured/inferred",
                             "反向档没有证据等级标记；下游会把推断当实测"))

    # C03 As-Built 不能暗示契约效力（只对"地位声索"强表述报，不含"时序契约"这类术语）
    STRONG = ("具有契约效力", "具备契约效力", "作为契约", "当成契约", "需求基线",
              "强制要求", "必须遵守", "以此为准", "具约束力")
    if is_asbuilt:
        for i, line in enumerate(doc.lines, 1):
            s = line.strip()
            if s.startswith("|") or HEAD.match(s):
                continue
            if doc.in_instruction(i) or _is_rule_line(s):
                continue
            hit = next((w for w in STRONG if w in s), None)
            if hit and not re.search(r"(非|不是|不作为|无契约|防冒用|以 PRD 为准|不得)", s):
                out.append(Issue("C03", i, "", hit,
                                 f"As-Built 文档里出现「{hit}」，未见否定；反向档不能自称契约"))
                break
    return out


# ---------------------------------------------------------------- 报告

SEV_LABEL = {"error": "错误", "warn": "警告", "info": "提示"}


def looks_like_spec(doc: Doc) -> tuple[bool, str]:
    """先确认"这是不是一份 spec"，否则后面所有结论都没意义。

    这条判据比想象中难写：`spec-outline.md` 本身就是**讲八章骨架的**，八章章名全出现过，
    靠章名命中会把它判成 spec，然后对着它报 9 条"缺第 X 章"——那种噪音只会教用户
    忽略这个工具。所以先排除"讲解型文档"，再看骨架。

    ① 讲解型：标题里"为什么 / 怎么 / 规则 / 纪律 / 判据"这类词出现 ≥3 次 → 不是 spec。
    ② 是 spec：八章命中 ≥5 章，或同时有「文档控制区 + 寄存器明细表」。
    """
    heads = doc.body_sections()
    teach = ("为什么", "怎么", "规则", "纪律", "判据", "本节", "写法", "注意")
    teach_hits = sum(1 for s in heads if any(k in s.title for k in teach))
    if teach_hits >= 3:
        return False, (f"标题里有 {teach_hits} 处讲解性措辞（「为什么」「规则」「判据」这类）——"
                       "这份文件是在讲怎么写 spec，不是一份 spec 本身。")

    titles = " ".join(s.title for s in heads)
    hit = [ch for ch in REQUIRED_CHAPTERS if ch in titles]
    has_ctrl = doc.find("文档控制") is not None
    regs, _ = extract_registers(doc)
    if len(hit) >= 5 or (has_ctrl and regs):
        return True, ""
    return False, (
        f"八章里只命中 {len(hit)} 章（{('、'.join(hit)) or '无'}），"
        "也没有「文档控制区 + 寄存器明细表」这对最小组合——"
        "这份文件看起来不是一份设计规格。若确实要检查它，加 --force。"
    )


def run(path: str, only: set[str] | None = None,
        force: bool = False) -> tuple[list[Issue], Doc, list[str]]:
    doc = parse(path)
    issues: list[Issue] = []
    notes: list[str] = []
    ok, why = looks_like_spec(doc)
    if not ok and not force:
        notes.append(why)
        return issues, doc, notes
    groups = {
        "S": lambda: check_structure(doc),
        "R": lambda: check_registers(doc),
        "I": lambda: check_interfaces(doc),
        "T": lambda: check_text(doc),
        "C": lambda: check_closure(doc),
    }
    for g, fn in groups.items():
        if only and g not in only:
            continue
        issues.extend(fn())
    _, n = extract_registers(doc)
    notes.extend(n)
    issues.sort(key=lambda i: (i.line or 10**9, i.rule))
    return issues, doc, notes


def report_md(issues: list[Issue], doc: Doc, notes: list[str]) -> str:
    regs, _ = extract_registers(doc)
    n_fields = sum(len(r.fields) for r in regs)
    cert = [i for i in issues if i.certain]
    rev = [i for i in issues if not i.certain]
    cnt = {k: sum(1 for i in issues if i.sev == k) for k in ("error", "warn", "info")}

    L = [f"# spec_lint：{Path(doc.file).name}", ""]
    L.append(f"- 章节 {len(doc.body_sections())} / 表 {sum(len(s.tables) for s in doc.sections)}"
             f" / 寄存器 {len(regs)} / 位域 {n_fields}")
    L.append(f"- 错误 {cnt['error']} / 警告 {cnt['warn']} / 提示 {cnt['info']}"
             f"（其中可确证 {len(cert)} 条，待人工确认 {len(rev)} 条）")
    for n in notes:
        L.append(f"- 注：{n}")
    L.append("")

    def table(items: list[Issue]) -> None:
        L.append("| 规则 | 位置 | 对象 | 说明 |")
        L.append("|---|---|---|---|")
        for i in items:
            loc = f"L{i.line}" + (f" {i.sec}" if i.sec else "")
            L.append(f"| {i.rule} {RULES[i.rule][3]} | {loc} | {i.target} | {i.detail} |")
        L.append("")

    if cert:
        L.append(f"## 可确证（{len(cert)}）")
        L.append("")
        L.append("> 这些是脚本判定的事实，不算「观后感」。修完重跑，应降到 0。")
        L.append("")
        table(cert)
    if rev:
        L.append(f"## 待人工确认（{len(rev)}）")
        L.append("")
        L.append("> 脚本只能提示「像是」，不能定案。逐条判断后在交付说明里写结论，不要照抄本条当 finding。")
        L.append("")
        table(rev)
    if not issues:
        blocked = any("看起来不是" in n for n in notes)
        if blocked:
            L.append("**未检查**：这份文件不像设计规格，已拦下（见上方注）。")
            L.append("误判时加 `--force`；更正：这确实不是 spec，那就不该跑这个脚本。")
        else:
            L.append("没有命中任何机械项。**这不等于可交付**——清单里判断类条目仍要人过。")
        L.append("")
    return "\n".join(L)


def report_console(issues: list[Issue], doc: Doc) -> None:
    cnt = {k: sum(1 for i in issues if i.sev == k) for k in ("error", "warn", "info")}
    print(f"[spec_lint] {Path(doc.file).name}: "
          f"错误 {cnt['error']} / 警告 {cnt['warn']} / 提示 {cnt['info']}")
    for i in issues:
        if i.sev != "error":
            continue
        loc = f"L{i.line}" if i.line else "--"
        print(f"  [{i.rule}] {loc:<7} {i.sec[:24]:<24} {i.target[:20]:<20} {i.detail[:64]}")


# ---------------------------------------------------------------- 自检

_SELFTEST_SPEC = """# 1 文档信息
## 1.0 文档控制
| 项 | 值 |
|---|---|
| 编号 | X-001 |
| 密级 | 内部 |
## 1.1 修订记录
| 版本 | 日期 |
|---|---|
| v1.0 | 2026-01-01 |
## 1.2.1 编号族总表
| 前缀 | 用途 |
|---|---|
| Q | 问题 |
## 4.1 地址段分配
| 段名 | 起始 | 结束 |
|---|---|---|
| CTRL | 0x0000 | 0x00FF |
| DATA | 0x0080 | 0x01FF |
## 4.2 明细表
| offset | name | bits | field | msb | lsb | attr | reset | description |
|---|---|---|---|---|---|---|---|---|
| 0x0002 | CTRL | 32 | EN | 3 | 1 | RW | 0x0 | x |
| 0x0002 | CTRL | 32 | MODE | 5 | 2 | RW | 0x0 | 与 EN 重叠 |
| 0x0002 | CTRL | 32 | BAD | 1 | 3 | RW | 0x0 | lsb>msb |
| 0x0002 | CTRL | 32 | WIDE | 40 | 8 | RW | 0x0 | 越界 |
| 0x0004 | CTRLL | 32 | A | 3 | 0 |  |  | x |
| 0x2000 | OUT | 32 | V | 0 | 0 | RW | 0x0 | 段外 |
## 4.3.9 空节
## 5.1 对外接口
| signal | direction | width | clock domain | protocol | description |
|---|---|---|---|---|---|
| awvalid | in | N | clk | AXI4 | x |
| awlen | in | AWLEN_W |  | AXI4 | x |
| rdata | out | 32 | clk | AXI4 | x |
## 5.3 复位与时钟
| 信号 | 极性 | 同步 / 异步 |
|---|---|---|
| rstn |  |  |
## 6A 正向形态
| a | b |
|---|---|
| 1 | 2 |
| 3 | 4 |
| 5 | 6 |
## 6B 反向形态
| a | b |
|---|---|
| 1 | 2 |
| 3 | 4 |
| 5 | 6 |
## 正文
这个模块在适当的时候反压，等若干个周期后用 always @ 处理，长度 4'd7。
TBD 待补。
引用 Q-01 与 INV-03。
"""

# 第二例专门覆盖"存在性 / 二选一 / 对账"类规则——它们要么要求某个部件**缺席**，
# 要么要求两个部件**同时在场**，没法在第一例里同时构造出来。
_SELFTEST_SPEC2 = """# 1 文档信息
## 4.2 明细表
| offset | name | bits | field | msb | lsb | attr | reset | description |
|---|---|---|---|---|---|---|---|---|
| 0xX | CTRL | 32 | EN | 0 | 0 | RW | 0x0 | offset 不能解析 |
| 0x0004 | CTRLX | 32 | EN | 0 | 0 | RW | 0x0 | 同 offset 不同名 |
| 0x0004 | CTRLY | 32 | EN | 1 | 1 | RW | 0x0 | 又一名 |
| 0x0008 | CTRL | 32 | EN | 0 | 0 | RW | 0x0 | 基准 |
| 0x0008 | CTRL | 16 | MODE | 1 | 1 | RW | 0x0 | 位宽声明不一致 |
## 5.1 对外接口
| signal | direction | width | clock domain | protocol | description |
|---|---|---|---|---|---|
| awvalid | in | 1 | clk | AXI4 | x |
| awid | in | 4 | clk | AXI4 | x |
### 5.1.2 协议通道表
| 通道 | 方向 | 位宽 | outstanding 深度 |
|---|---|---|---|
| AW | S→M | 1 | 4 |
| W | S→M | 32 | 4 |
## 6A 正向形态
| a | b |
|---|---|
| 1 | 2 |
| 3 | 4 |
| 5 | 6 |
## 6B 反向形态
| a | b |
|---|---|
| 1 | 2 |
| 3 | 4 |
| 5 | 6 |
As-Built 文档具有契约效力，必须遵守。这一段有四句。用来触发散文长度。第四句在这里。
引用 [?Q-09]。
## 附录 E 问题清单
| 编号 | 问题 |
|---|---|
| Q-02 | 已有 |
"""


def selftest() -> int:
    import tempfile

    tmpdir = Path(tempfile.mkdtemp())
    ok = True
    # 每例只报覆盖进度，不要求单例全覆盖——"某部件必须缺席"与"某部件必须在场"
    # 这两类规则天然没法在同一个文件里同时成立，必须分两例。
    for name, text in (("bad_spec.md", _SELFTEST_SPEC),
                       ("bad_spec2.md", _SELFTEST_SPEC2)):
        p = tmpdir / name
        p.write_text(text, encoding="utf-8")
        issues, doc, _ = run(str(p), force=True)
        got = {i.rule for i in issues}
        print(f"[selftest] {name}: 命中 {len(got)}/{len(RULES)} 条规则")
    # 两例合起来必须覆盖全部规则
    allgot: set[str] = set()
    for name in ("bad_spec.md", "bad_spec2.md"):
        iss, _, _ = run(str(tmpdir / name), force=True)
        allgot |= {i.rule for i in iss}
    still = sorted(set(RULES) - allgot)
    if still:
        ok = False
        print(f"[selftest] 两例合起来仍缺：{still}")
    else:
        print(f"[selftest] 两例合计覆盖 {len(allgot)}/{len(RULES)} 条规则")
    # 反例：模板本身不该被报——它是规则的宿主，不是被检查的对象
    tpl = Path(__file__).resolve().parent.parent / "templates" / "spec-template.md"
    if tpl.exists():
        iss, _, _ = run(str(tpl))
        bad = [i for i in iss if i.sev == "error"]
        if bad:
            ok = False
            print(f"[selftest] 模板误报 {len(bad)} 条错误（模板是规则宿主，不该被报）：")
            for i in bad[:5]:
                print(f"  {i.rule} L{i.line} {i.target} {i.detail[:50]}")
        else:
            print(f"[selftest] 模板无错误级误报（样例目录 {tmpdir}）")
    print(f"[selftest] {'通过' if ok else '失败'}")
    return 0 if ok else 1


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="设计规格的机械项校验（review-checklist 第一节的可执行部分）")
    ap.add_argument("spec", nargs="?", help="spec 的 markdown 文件")
    ap.add_argument("--json", dest="json_path", help="机读结果写到该文件")
    ap.add_argument("--md", dest="md_path", help="md 报告写到该文件")
    ap.add_argument("--only", help="只跑指定组，逗号分隔：S,R,I,T,C")
    ap.add_argument("--quiet", action="store_true", help="只打印统计，不列明细")
    ap.add_argument("--selftest", action="store_true", help="跑内置自检，不需要输入文件")
    ap.add_argument("--force", action="store_true",
                    help="即使看起来不是 spec 也强制检查（默认会先拦一道）")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if args.selftest:
        return selftest()
    if not args.spec:
        ap.error("需要 spec 文件路径，或用 --selftest")

    only = {g.strip().upper() for g in args.only.split(",")} if args.only else None
    if only:
        bad = only - set(GROUPS)
        if bad:
            ap.error(f"未知组：{','.join(sorted(bad))}；可选 {','.join(GROUPS)}")

    issues, doc, notes = run(args.spec, only, args.force)

    if args.md_path:
        p = Path(args.md_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(report_md(issues, doc, notes), encoding="utf-8")
        print(f"-> {p}")
    if args.json_path:
        p = Path(args.json_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(
            {"file": args.spec, "issues": [i.as_dict() for i in issues]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"-> {p}")

    if args.quiet:
        cnt = {k: sum(1 for i in issues if i.sev == k) for k in ("error", "warn", "info")}
        print(f"错误 {cnt['error']} / 警告 {cnt['warn']} / 提示 {cnt['info']}")
    else:
        report_console(issues, doc)
        if not args.md_path and not args.json_path:
            print()
            print(report_md(issues, doc, notes))

    return 1 if any(i.sev == "error" for i in issues) else 0


if __name__ == "__main__":
    sys.exit(main())
