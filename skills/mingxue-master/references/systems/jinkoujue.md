# 六壬金口诀四位起课

入口为 `calculate("jinkoujue", params)`，位于 `scripts/traditional_casts.py`。实现人元、贵神、将神、地分四位及两套十二支排布，展示选定的月将、昼夜、贵神起点和顺逆过程。它不是完整大六壬四课三传，也不生成综合吉凶或应期。

手工样例：

```json
{"mode":"manual","day_pillar":"丁卯","hour_branch":"未","earth_branch":"午","month_general_branch":"卯","day_night_rule":"si_xu_day"}
```

结果依次为人元丙、贵神白虎申、将神功曹寅、地分午。地分必须由用户明确选定，不从问题文本或出生信息推测；手工日时与月将仅核合法结构，不宣称已校到某个公历日。`month_general_rule` 若显式提供，只能为 `explicit`。

时间样例：

```json
{"mode":"datetime","date":"2015-10-18","time":"14:32:00","timezone":"Asia/Shanghai","earth_branch":"午","month_general_rule":"month_branch_he"}
```

时间模式须明确公历日期、钟点与离线IANA时区，复用统一历法；不取当前时间，也不借用出生盘。`sect` 默认2即00:00换日，1为23:00换日；另一换日约定另存 `convention_alternatives`。`fold` 可选0或1，省略时保留夏令时重复钟点；缺失钟点拒绝。不能用手工日柱、时支或月将覆盖时间模式的计算值。

月将有两个明确选项：

| `month_general_rule` | 取法 |
|---|---|
| `solar_qi`（时间模式默认） | 中气换将：冬至丑、大寒子、雨水亥、春分戌、谷雨酉、小满申、夏至未、大暑午、处暑巳、秋分辰、霜降卯、小雪寅；按真实瞬间转固定UTC+08对照交气秒界 |
| `month_branch_he` | 取节界月建地支的六合支为月将，不与中气法混用 |

上述时间样例在节月六合法得卯月将，在中气法得辰月将，差异须保留。2025-06-21 10:42整分钟跨中气边界时，会保存申、未两个月将候选，不取一个代表秒充当全分钟。

将神按月将加占时，沿地盘十二支顺转至地分：`将支=(月将索引+地分索引-时支索引) mod 12`。

贵神采用以下昼/夜起点：甲戊庚丑/未，乙己子/申，丙丁亥/酉，壬癸巳/卯，辛午/寅。`day_night_rule` 默认 `si_xu_day`，巳至戌为昼；可改为 `mao_shen_day`，卯至申为昼。`day_night` 默认 `auto`，可显式指定 `day` 或 `night`。这些是支时分界，不是天文日出日落，界面须显示所选规则。

贵人起点落亥子丑寅卯辰时顺行，落巳午未申酉戌时逆行；并非所有昼占都顺行。依贵人、螣蛇、朱雀、六合、勾陈、青龙、天空、白虎、太常、玄武、太阴、天后排到地分。

人元按五子元遁，从子位顺排到地分。贵神与将神另有 `dun_stem`，同样按当日日干遁至该神将本支；遁干与神将本体称谓分开。五行关系仅作方向标记，不宣称作用已成立，不据此推断现实成败。

`candidates[]` 每项包含 `four_positions`、`general_plate`、`noble_plate`、`relations`、`steps` 和 `month_general_source`。`four_positions` 数组按自上而下顺序显示；两套plate均有12个地分位置及选中标记。单一当前候选时，顶层另提供 `four_positions` 和 `visualization.kind=four_positions`；多候选时必须显示候选选择器，读取各项的可视结构，不能悄悄取第一项。

```text
python <skill_root>/scripts/traditional_casts.py jinkoujue --params '{"mode":"manual","day_pillar":"丁卯","hour_branch":"未","earth_branch":"午","month_general_branch":"卯"}'
```

CLI只返回JSON。四位起法、月将与贵神有流派差异，输出保留本次选择；不把结构排盘冒充完整断法、疾病诊断、投资或婚姻保证。
