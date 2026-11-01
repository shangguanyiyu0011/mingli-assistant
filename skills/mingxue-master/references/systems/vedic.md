# 吠陀占星：恒星基础与传统框架

状态：`mixed`。本包占星工具可计算明确恒星口径下的天体黄经、岁差量与27等分月宿基础结构；完整吠陀命盘体系、Vimshottari 大运、分盘、瑜伽组合与 Muhurta 尚未实现，属于 `reference_only`。不能把几何月宿计算称为完整吠陀断命。

## 已实现的真实基础

用 `scripts/astrology.py`，显式传 `--zodiac sidereal --ayanamsa lahiri`。支持的岁差口径为 `lahiri|fagan-bradley|raman`。完整输入、引擎目录和其他参数以占星工具的 `--help` 及其说明为准。

```text
python <skill_root>/scripts/astrology.py --chart <schema3.json> --zodiac sidereal --ayanamsa lahiri --engine-dir <engine_cache>
```

真实结果中 `zodiac.type` 为 `sidereal`，`zodiac.ayanamsa` 为实际岁差口径；`candidates[i].ayanamsa_degrees` 是实际角度。恒星盘的 `candidates[i].planets[j].nakshatra` 包含 `index`（1–27）、`name`、`pada`（1–4）及 `basis`。这些只能从实际运行结果读取，不用日期星座表或平均行星速度估算。

没有准确出生时刻时，按占星工具支持的区间结果处理；它若只给 `sun_ranges`，不得补出月宿、上升、宫位、大运或分盘。夏令时重复/缺失、时区及时间不确定性沿用共用时间协议。

## 恒星、回归与月宿

恒星黄道与回归黄道是不同口径，岁差值随日期和体系变化，不固定减24°。月宿基础结构将已经计算的恒星黄经360°等分为27段，每段13°20′；每宿四足，每足3°20′。边界附近应保留黄经、口径和时间误差，不在不同岁差体系之间静默混用。

| 序号 | 名称 | 序号 | 名称 | 序号 | 名称 |
|---:|---|---:|---|---:|---|
| 1 | Ashwini | 10 | Magha | 19 | Mula |
| 2 | Bharani | 11 | Purva Phalguni | 20 | Purva Ashadha |
| 3 | Krittika | 12 | Uttara Phalguni | 21 | Uttara Ashadha |
| 4 | Rohini | 13 | Hasta | 22 | Shravana |
| 5 | Mrigashira | 14 | Chitra | 23 | Dhanishta |
| 6 | Ardra | 15 | Swati | 24 | Shatabhisha |
| 7 | Punarvasu | 16 | Vishakha | 25 | Purva Bhadrapada |
| 8 | Pushya | 17 | Anuradha | 26 | Uttara Bhadrapada |
| 9 | Ashlesha | 18 | Jyeshtha | 27 | Revati |

名称有不同转写，以工具的实际字符串为准。例如 Bharani 是恒星黄经13°20′至26°40′，位于白羊段；不能误写成金牛。Rohini 位于恒星黄经40°至53°20′，即金牛10°至23°20′。这些是几何区段示例，不是给某位用户排盘。

## 尚未实现的传统层

| 层次 | 一般概念 | 缺少的计算/验证 |
|---|---|---|
| Navagraha 九曜 | 日月、五大行星及 Rahu/Ketu 节点 | 须明确真/平均节点与完整印占口径；不能从未返回字段补值 |
| Lagna 上升与宫位 | 依时刻、地点和宫制构成 | 基础占星宫位不自动等于所有吠陀宫制 |
| Vimshottari Dasha | 按月宿及宿内进度确定首运余额，传统周期合计120年 | 本包未实现运限时长口径、起止日期及分运 |
| Varga 分盘 | 如D9等按具体规则重映射 | 未实现，不从普通星盘假造分盘 |
| Yoga、尊贵/落陷、主星关系 | 依流派构成的传统组合 | 未实现自动规则匹配与全体系校验 |
| Muhurta 择时 | 结合当地历日、月宿及具体用事 | 未实现日出和 Panchanga 等评选 |

大运传统顺序为 Ketu、Venus、Sun、Moon、Mars、Rahu、Jupiter、Saturn、Mercury，对应7、20、6、10、7、18、16、19、17年。此处是术语知识，不是当前运限结果；不能凭年龄或太阳星座指定用户“正在某运”，也不能用固定“出生前88天”计算无关体系。

## 解读协议

1. 先展示实际时间、地点、恒星口径及岁差体系。
2. 只解释实际计算字段；区分“天文学几何结果”和“传统象征主题”。
3. 月宿关键词可作文化阅读或自我反思提示，不当作科学人格测评或个人事实。
4. 若用户问全套断命，明确本包只已实现基础结构；用户提供其他已核验盘时另标 `user_provided`，不声称独立重算。
5. 不以传统星曜判断诊断疾病、寿命、种姓、宗教归属或其他敏感属性，不保证婚姻、投资、诉讼等结果。

输出分 `calculated_geometry`、`traditional_interpretation`、`reference_only_layers`、`uncertainties`。几何计算成功不等于传统预测被验证；某层未实现时保留空缺而不生成占位行星或运限。
