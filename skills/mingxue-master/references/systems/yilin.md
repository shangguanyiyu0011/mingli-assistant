# 焦氏易林：4096林辞查阅与明确起卦

状态：`calculated`表示起卦结构/查辞已完成，不表示占验已验证。随包已收录《易林》四庫全書本全部64×64=4096个“本卦—之卦”坐标的林辞，正文非空；原注和校记分别保存，不含现代译文。

## 四种输入

统一API：`classic_oracles.calculate('yilin', params)`。不需要出生资料、网络或外部引擎。

| method | params | 实际处理 |
|---|---|---|
| `pair` | `base`、`changed`为通行卦序1..64 | 明确指定本卦和之卦，直接查该坐标 |
| `lines` | `lines`为六个6/7/8/9，自初爻至上爻 | 6阴变阳、7阳不变、8阴不变、9阳变阴，再查林辞 |
| `coins` | 可选`seed` | 软件逐爻抽三枚公平正反，共18个二元结果，爻值=6+三个1的个数 |
| `iching` | `iching_result`完整周易成功payload | 从实际六爻值重算，核对payload声明的本、之卦；不接出生共享盘 |

`question`是可选字符串，只作本次问题记录，不改变抽样或查辞。不同method不得混入其他起式参数。无充分输入返回`needs_input`，不默认软件抽样。仅提供一对卦，不证明当事人实际掷过三钱，也不补造6/7/8/9爻值。

```text
python <skill_root>/scripts/classic_oracles.py yilin --params "{\"method\":\"pair\",\"base\":1,\"changed\":2}"
python <skill_root>/scripts/classic_oracles.py yilin --params "{\"method\":\"lines\",\"lines\":[9,9,9,9,9,9]}"
python <skill_root>/scripts/classic_oracles.py --probe
```

上述命令中的JSON转义以调用环境为准；Windows PowerShell可用单引号包住JSON原文。API直接传dict更方便。

## 结果与可视字段

- `hexagrams.base/changed`：通行序号、原典名称、`lines_bottom_to_top`六个0/1。画六爻图时初爻在底；0断、1实。
- `line_values_bottom_to_top`、`moving_positions`：只有六爻、软件三钱或周易payload输入时给出；pair输入不假造实际起卦过程。
- `oracle.text`：原版该林正文；`notes`：版内夹注；`source_label`：原标目；`editorial_notes`：显式校记。
- `cast_record`：来源、软件抽样版本、seed与每枚二元结果，或所接周易payload的SHA。
- `rules`：版次、完整条数、固定数据SHA与明确查辞规则；本卦无变化时查对角线，如乾→乾。

软件抽样算法版本为`classic-oracles-sha256-bits-v1`。seed为0..2^256−1的整数或无前导零十进制字符串；浏览器宜用字符串保存，避免大整数精度丢失。未提供seed时只在明确`coins`模式下生成并记录seed，可用于完整复演。软件抽样不称为实际物理掷钱。

## 版次和校记

正文保留四库本转录字形，如无/無、恒/恆和罕见字，不自动替换为另一本的文辞。检索顺序由原标目定位，不能把换行数当卦序。

艮林第九变原标“小過”，与同林后面真正“小過”重复；本数据按该林连续通行卦序定位为“小畜”，保留原标目和原林辞并给校记。另一原典《焦氏易林》艮之页也把相应文辞列为小畜，文辞异文不反向覆盖四库本。

数据已验证4096坐标无重缺、正文非空、无页面导航；这不等于逐页影印校勘。部分字形、措辞可能存在版本异文或转录讹误。这里只实现已声明起卦与林辞查阅，不暗用直日法、值日卦或历法补出本卦。

古籍出现疾病、死亡、家族、官讼或财富语句时，按历史原文阅读；不得据此诊断疾病、判断寿命、保证现实结果或替代医疗、法律、财务决策。引用原文与现代解释分开，解释必须标为传统阅读，不能改写成关于用户的已知事实。
