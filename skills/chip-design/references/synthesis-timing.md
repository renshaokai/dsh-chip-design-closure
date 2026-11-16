# 综合与时序收敛

## 1. 顺序不能反

综合之前先确认三件事，任何一件不对，后面所有报告都是噪声：

1. **约束是否描述真实意图**（时钟、IO、例外）
2. **参数是否按目标配置 elaborate**（别用默认参数综合再拿结果对比架构预算）
3. **库与 corner 是否对**（tt/ss/ff、电压、温度；签核用 ss，早期评估可先用 tt 看趋势）

## 2. SDC 骨架

```tcl
# 时钟
create_clock -name clk_core -period 1.0 [get_ports clk_core]
create_clock -name clk_ddr  -period 2.0 [get_ports clk_ddr]
set_clock_uncertainty 0.05 [get_clocks clk_core]        ;# 早期粗估，签核按实际 jitter+skew
set_clock_groups -asynchronous -group {clk_core} -group {clk_ddr}

# IO（max 管 setup、min 管 hold，只给 max 等于放弃 IO 的 hold 检查）
set_input_delay  -clock clk_core -max 0.30 -min 0.05 [remove_from_collection [all_inputs]  [get_ports clk*]]
set_output_delay -clock clk_core -max 0.30 -min 0.05 [remove_from_collection [all_outputs] [get_ports clk*]]
set_load 0.05 [all_outputs]                              ;# 单位同库（pF 或 fF，别混），早期占位，后端给真实 cap

# 例外（每条都要编号和理由，见第 5 节）
# [EX-001] cfg_reg → ctrl：配置在 start 前写入，ctrl 有 2 拍稳定期
#          责任人：<name>  复核条件：若配置改为运行期可改，此例外失效
set_multicycle_path 2 -setup -from [get_pins cfg_reg*/Q] -to [get_pins ctrl*/D]
set_multicycle_path 1 -hold  -from [get_pins cfg_reg*/Q] -to [get_pins ctrl*/D]
# [EX-002] test_mode 只在扫描/测试模式下稳定，不进功能路径
#          责任人：<name>  复核条件：若 test_mode 参与功能逻辑，此例外失效
set_false_path -from [get_ports test_mode] -to [all_registers]
```

**三个最常见错误**：`set_clock_uncertainty` 设太小（看起来时序很好，实际收不住）；IO 延迟用 0（顶层路径假装不存在）；跨域时钟没有 `set_clock_groups -asynchronous`（工具硬算跨域路径，报一堆假违例）。

**第四个，也是危害最大的一处：多周期只设 setup 不设 hold。** 只写 `set_multicycle_path N -setup` 时，工具的 hold 检查点会跟着从第 0 拍移到第 N-1 拍，检查比真实要求**更宽松**——真实 hold 违例被放过，报告干净、硅上出错。**多周期必须成对写**：

```tcl
set_multicycle_path N     -setup -from <launch> -to <capture>   ;# setup 放松到第 N 拍
set_multicycle_path N-1   -hold  -from <launch> -to <capture>   ;# hold 拉回原边沿
```

同理，跨域用 `set_clock_groups -asynchronous` 之后不需要再逐条 `set_false_path`；两条都写，一旦后来两域改成同源，假路径还在，问题就被永久掩埋。

## 3. 报告看什么

**综合面积报告**
- 总 cell 面积 / 组合占比 / 时序单元占比 / 宏单元
- Top-N 模块面积排行（后面的 hotspot 从这里挑）
- 时序单元与组合的比例——比例异常（>60% 触发器）说明流水打得过碎或寄存器冗余
- 与上次综合的 delta：**面积忽然涨 20%，通常是有模块被展开了或参数不对**

**时序报告**
- 先看 WNS / TNS / 违例端点数量，再看路径
- 只抓最差 10 条路径的 full path，找公共段（同一级组合逻辑、同一个 mux、同一条总线扇出）
- 起点/终点要能说清是哪个模块的哪一级——说不清说明层次有问题
- 看路径里的逻辑级数（levels of logic）：>20 级基本要靠改结构，不是靠工具

**Warning 分类**（综合 warning 不要一条条读）
| 类别 | 处理 |
|---|---|
| 位宽截断 / 隐式转换 | 必查，多数是真缺陷 |
| 未连接端口 / 悬空 | 必查 |
| 常量传播后逻辑被优化掉 | 看是否预期 |
| 组合环 | 必查，一般是真的 |
| 库单元替换、drive 不足 | 交后端 |
| 不可达分支 | 看是否漏了 case |

## 4. 时序违例五分类与修法

| 类型 | 判据 | 修法 |
|---|---|---|
| **真违例** | 同同步域、逻辑级数深、路径真实存在 | 加流水 / 重定时 / 拆逻辑 / 改编码 |
| **约束错** | 时钟周期、uncertainty、IO 延迟与实际不符 | 改约束，别改 RTL |
| **假路径未声明** | 配置寄存器到数据通路、测试模式、跨异步域 | 补 `set_false_path` / `set_clock_groups`，写理由 |
| **跨域路径被当同步查** | 起点终点不同时钟域 | 先确认 CDC 方案，再设 clock groups |
| **不可容忍路径** | 异步接口的建立/保持本不该约束 | 同假路径处理，但要在 CDC 报告里登记 |

**修法的代价排序（从小到大）**
1. 补/改约束 —— 零面积代价，但改错会藏问题
2. 局部改编码（把优先级链改成一热、把大 mux 拆成两级）—— 面积略变
3. 加一级流水 —— 加触发器，加一拍延迟（**要回头改 spec 的时序契约**）
4. 重定时（retiming）—— 工具自动搬寄存器，行为和延迟都变，需要仿真确认
5. 换综合策略 / 提高 effort —— 只榨几个百分点，别指望
6. 降频 —— 最后手段，等于改需求

## 5. 例外路径的纪律

每条 `set_false_path` / `set_multicycle_path` / `set_clock_groups` 必须在约束文件里带注释：

```tcl
# [EX-003] cfg_reg → datapath：配置寄存器在 start 前写入，运行期不变
# 责任人：<name>  复核条件：若支持运行期改配置，此例外失效
set_false_path -from [get_pins u_cfg/*/Q] -to [get_pins u_dp/*/D]
```

没有编号和理由的例外，三个月后没人敢动，也没人敢删——这是时序收敛最大的技术债。

## 6. 收敛判据（给自己和评审会的口径）

- [ ] WNS ≥ 0，TNS = 0（或 TNS 在约定容差内且全部有解释）
- [ ] 每条剩余违例都有分类和处置记录
- [ ] 约束里每条例外都有编号、理由、责任人
- [ ] 面积与功耗在预算内，超出的部分有决策记录
- [ ] 综合用的参数配置与 spec 目标配置一致
- [ ] RTL 与综合网表做过形式等价（Formality / LEC）或至少有回归保护

## 7. 开源工具链能跑到哪一步

| 工具 | 能替代什么 | 差距 |
|---|---|---|
| `verilator --lint-only` | 语法/位宽/未使用信号类检查 | 不覆盖功耗与 DFT 规则 |
| `slang` / `verible-verilog-lint` | 编码规范、可综合性提示 | 规则集与商业 lint 不同 |
| `yosys synth` | 初步面积与逻辑级数趋势 | 无商用库映射，绝对面积不可比 |
| `yosys` + `sta`（OpenSTA） | 简单时序检查 | 无寄生参数，只能看逻辑级数趋势 |

结论：开源链适合**早期自查和 CI 拦截**，不能作为签核依据。用它做趋势对比（这版比上版多 8% 面积）是可靠的，用它说"面积 0.42 mm²"是不可靠的。
