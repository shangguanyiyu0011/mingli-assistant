# 小六壬六宫递数

入口为 `scripts/traditional_casts.py`，公开API是 `calculate("xiaoliuren", params)`。实现报数和农历月日时两种六宫顺行法，输出三阶段、逐步算式和可视化六宫；不扩展为九宫或完整断法。

报数例：

```json
{"mode":"numbers","numbers":[3,5,7]}
```

对应速喜→大安→大安。每数须为1—1000000000的整数，不接受零、小数、布尔值。零另作十等处理存在其他约定，本模块没有采用。

月日时例：

```json
{"mode":"lunar","lunar_month":1,"lunar_day":1,"hour_branch":"子","leap":false}
```

采用农历月份1—12、日期1—30、子1丑2至亥12的时辰序号。正月初一子时为大安。闰月按同编号月起数，`leap_rule` 固定为 `same_numbered_month`；手工月日没有农历年，不验证具体年份的月长，不能冒称已完成公历或日本旧历换算。两种模式参数不可混用，不默认当前时辰。

规则是大安、留连、速喜、赤口、小吉、空亡循环；每阶段当前宫计1，后一个数从上一阶段所得宫重新计1：`next=(current+count-1) mod 6`，首次current=0即大安。六宫五行取木、土、火、金、水、土，明确作为选定表，保留流派差异。

共同输出含 `system/status/input/rules/limitations`。`palaces` 有六宫名称、索引、五行、文化主题和二行三列位置；`steps` 记录起点、计数、终点、完整轮数、剩余步数及最多12项路径预览。大报数不会生成巨量路径。`three_positions` 给三阶段卡片，`final_palace` 给最终落宫。

可视化读取 `visualization.kind=six_palaces`、`nodes`、`cycle_edges`、`steps` 和 `selected_index`。索引均从0开始，按规则次序连接；节点坐标只是显示布局，不作方位占断。阶段文化主题不写成现实成败保证，不从空亡等名称诊断疾病、死亡或损失。

```text
python <skill_root>/scripts/traditional_casts.py xiaoliuren --params '{"mode":"numbers","numbers":[3,5,7]}'
```

CLI仅返回stdout JSON，不自动保存用户资料。参数错误退出码2并返回结构化错误；可用 `--probe` 查看默认样例。
