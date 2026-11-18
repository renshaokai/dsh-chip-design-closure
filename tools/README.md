# tools/ — 维护脚本

这里放的是**维护本 bundle 用的脚本**，不是插件内容。`package.json` 的 `files` 白名单没有列
`tools`，所以 `npm pack` 不会把它们打进包里——它们跟着 git 走，不跟着 npm 走。

## sync_upstream.py — 把 WorkBuddy 专家包同步进本仓

专家包（`chip-arch-expert`）是上游，本仓是它的 DSH 版。这条同步手工做过五轮，每轮都要盯五件事，
漏一样就出过事故：漏换行（上游 1.11.0 有一次整包 CRLF）、漏改页脚（`顾芯` 残留进下游人格）、
漏查冒烟词（客户个案信号名混进通用规则）、漏核条数（声明 26/29 条，实际 16/26 条）、
漏更新版本（包与 `package.json` 各说一套）。

所以断言写死在脚本里，跑不过就不许提交；失败时打印"修哪一步"，而不是一个 False。

```sh
python tools/sync_upstream.py --dry-run     # 只检查、只报告差异，不写文件
python tools/sync_upstream.py               # 执行同步并跑全部断言
python tools/sync_upstream.py --check-only  # 不写文件，只跑断言（检查当前状态）
```

上游默认取 `~/.workbuddy/plugins/marketplaces/my-experts/plugins/chip-arch-expert`；
换机器或换目录用 `--upstream <dir>` / `--bundle <dir>` 显式指定。

### 断言（任一失败 → 退出码 1）

| 断言 | 拦住的事故 |
|---|---|
| 上游基线文件无 CRLF | 1.11.0 整包 CRLF，diff 看着像"621 行重写" |
| 冒烟词零命中（上游） | 客户个案信号名前缀写进通用规则 |
| 声明条数 = 实际条数 | 变更说明里的 26/29 与清单实际 16/26 不符 |
| persona 往返一致 | 缩进错一格，写进 YAML 的内容静默变形 |
| persona 无上游名残留（独立检查） | **往返比对抓不住的错**：写进去的内容本身就错时，两头比对照样相等 |
| 技能文件逐字节一致（除 LF 与页脚） | 有人手改了技能文件，下次同步被静默覆盖 |
| 下游基线文件无 CRLF | `cordis.patch.yml` / `package.json` 被编辑器改成 CRLF |
| mdmodel 是否被接线（**仅报告**） | `src/spec_agent/mdmodel.py` 是零调用的孤立模块，别当成 md 链路已通 |

依赖：只用 Python 标准库（3.9+）。
