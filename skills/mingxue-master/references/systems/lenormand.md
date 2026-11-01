# 雷诺曼：36 牌与可视牌阵

用于用户明确要求雷诺曼、双牌/三牌组合、九宫格或大桌阵的场景。它与塔罗是不同系统；本版雷诺曼固定 36 张，无逆位，不套用塔罗牌号、大小阿卡纳或逆位规则。

## 实际入口

~~~python
from oracles import calculate
result = calculate("lenormand", {"spread": "nine", "seed": 42})
~~~

~~~powershell
python -X utf8 -B scripts/oracles.py lenormand --params '{"spread":"pair","cards":[1,27]}'
python -X utf8 -B scripts/oracles.py lenormand --params '{"spread":"grand","layout":"8x4+4","seed":42,"significator":28}'
python -X utf8 -B scripts/oracles.py --probe
~~~

成功、参数错误、帮助与 probe 均输出 JSON。只用标准库，执行和 probe 均不联网、不自动写文件。主接口为 calculate(system, params)。

## 参数与规则

| 参数 | 取值 |
|---|---|
| spread | pair 双牌、three 三牌（默认）、nine 九宫格、grand 大桌阵 |
| layout | 双牌/三牌为 line，九宫格为 3x3；大桌阵可选 9x4（默认）或 8x4+4 |
| cards | 用户手工给定牌号列表，分别恰好 2/3/9/36 张，1–36 整数且不能重复 |
| seed | 与手工 cards 互斥；0 至 2²⁵⁶−1，可用十进制字符串避免前端丢失大整数精度 |
| significator | 用户自选焦点牌号 1–36，不根据身份或性别自动决定 |
| question | 最多 2000 字的提问记录，不影响同一 seed 的抽样 |

未手工给牌时实际执行无放回虚拟抽样；未指定 seed 时调用系统随机源生成 128 位 seed，并记录在 randomness。算法为版本化 SHA-256 计数流与拒绝采样，牌序为 1–36。同版本、牌阵与 seed 可复现。手工给牌标 user_supplied_cards，seed/algorithm 为 null，不假称已发生随机抽牌或实体洗牌。

牌表包含编号、中文名、简洁关键词与文本符号。图像为本地文字、符号和简单矢量框线，没有复制第三方牌画；不将符号的印刷朝向当作额外判读数据。

## 位置与可视结果

所有阵都按从上到下、从左到右的发牌顺序给出 index。双牌明确左、右；三牌明确第 1–3 位，不自动承诺过去/现在/未来。九宫格返回每行、每列、两条对角线和中心第 5 位的索引分组。

9x4 大桌阵为四行九列。8x4+4 为前四行各八张，第五行四张居中在第 3–6 列。大桌阵的 house_number/house_name 是固定牌位 1–36 的主题，不是当前抽到牌的牌号。焦点牌若在小阵里未出现，返回 not_in_spread，不重抽或偷偷塞入；出现时返回位置与相邻牌位索引。

visual.type 为 lenormand_grid，visual.svg 为独立 SVG，visual.cells 含每牌像素坐标和尺寸。card_id 对应实际牌，position_id 对应牌位；number/name/keywords 与位置字段同时提供，便于点击展开说明。UI 缩放应保持 viewBox 比例，36 牌可滚动查看。

解读先陈述实际牌序与位置，再把相邻符号作为文化联想和反思问题；不从人物牌、蛇、狐狸、棺材等直接断言身份、背叛、疾病或死亡。资源相关牌也不保证投资收益。未实现所有流派的骑士跳步、朝向法或固定组合辞典时，不冒称这些功能已经计算。

仅用户明确要求存档时使用 --output，必须为安装代码、资源和引擎缓存外的新绝对 JSON 文件路径；不覆盖原文件。
