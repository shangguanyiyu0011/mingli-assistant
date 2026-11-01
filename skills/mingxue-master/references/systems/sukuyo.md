# 宿曜二十七宿月日表

入口为 `calculate("sukuyo", params)`，位于 `scripts/traditional_casts.py`。采用独立的农历月日宿表，计算本命宿、显式指定日期的值日宿及三九有向关系。此为**中国农历换算版**，不是月球黄经排宿，也不把其他体系的27宿更名复用。

默认样例：

```json
{"birth":{"calendar":"lunar","month":2,"day":17},"target":{"calendar":"lunar","month":2,"day":15},"leap_rule":"same_numbered_month"}
```

本命为氐宿，值日为角宿。`birth` 必需；`target` 和 `partner` 可选，分别表示待查日期与另一人的月日。没有target不默认今天。

日期对象有两种形式：

- 农历：`{"calendar":"lunar","month":2,"day":5}`，可附 `year` 与布尔 `leap`。月1—12、日1—30；提供年份时按已有离线历法核实际月长与闰月，未提供年份时只作月日表计算。
- 公历：`{"calendar":"solar","date":"2024-02-10"}`，限1583—9998年；按固定UTC+08中国农历日换算。中国农历与日本旧历可能存在日界或置闰差异，不能把此结果宣称为日本历法的唯一标准。

本算法使用不含牛宿的27宿环：角、亢、氐、房、心、尾、箕、斗、女、虚、危、室、壁、奎、娄、胃、昴、毕、觜、参、井、鬼、柳、星、张、翼、轸。

按十二个月十五日望宿定位，日期早于十五则逆数，晚于十五则顺数：`index=(望宿索引+农历日-15) mod 27`。

| 农历月 | 初一宿 | 十五望宿 |
|---|---|---|
| 1 | 室 | 翼 |
| 2 | 奎 | 角 |
| 3 | 胃 | 氐 |
| 4 | 毕 | 心 |
| 5 | 参 | 箕 |
| 6 | 鬼 | 女 |
| 7 | 张 | 室 |
| 8 | 角 | 娄 |
| 9 | 氐 | 昴 |
| 10 | 心 | 觜 |
| 11 | 斗 | 鬼 |
| 12 | 虚 | 星 |

这是每月重新定位的表法，月末与下月初可能同宿，不能强行改成不间断的逐日天文序列。闰月采用 `same_numbered_month`，即同编号月宿表；这是模块明确采用的约定，不称为原经明定闰法。

三九关系以本命宿为起点：第一组依次命、荣、衰、安、危、成、坏、友、亲；第二组首位为业，第三组首位为胎，其余位置同序。`daily_relation` 和 `partner_relation` 均分别给出顺向步数、反向步数、正反向名称、命/业胎/荣亲/友衰/安坏/危成关系组及简明说明。关系必须保留方向，不将“坏”“危”等名称解释成实际伤害、关系结局或相处概率。

可视化读取 `visualization.kind=mansion_wheel` 与27个 `nodes`，每个节点有零基索引、标签、相对本命的关系和 `is_birth/is_daily/is_partner` 标志，标志可以重叠。卡片读取 `birth_mansion/daily_mansion/partner_mansion`；`steps` 含望宿锚点与算式；`month_table` 供展开核对。

```text
python <skill_root>/scripts/traditional_casts.py sukuyo --params '{"birth":{"month":2,"day":17},"target":{"month":2,"day":15}}'
```

CLI仅输出JSON，不保存个人资料。月日表计算与传统关系分类不构成科学预测，也不用于医疗、死亡、投资或婚姻保证。
