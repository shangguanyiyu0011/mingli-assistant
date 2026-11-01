# 灵棋经：125棋形全量查辞与十二棋起式

状态：`calculated`表示棋形/查辞已完成，不表示传统预测已经验证。随包收录《靈棋經》四庫全書本卷上、卷下的124个编号卦断及另列纯阴镘，共125种计数棋形。上、中、下各有四枚棋，分别计有字面朝上的数量，三层均允许0..4，完整覆盖5³=125坐标。

## 三种输入

统一API：`classic_oracles.calculate('lingqijing', params)`。不需要出生资料、网络或外部引擎。

| method | params | 实际处理 |
|---|---|---|
| `counts` | `counts:[上数,中数,下数]`，各为0..4整数 | 查已经明确给出的计数棋形 |
| `pieces` | `pieces:{upper:[四面],middle:[四面],lower:[四面]}` | 每面为整数0或1；1有字朝上，0无字朝上；逐层求和 |
| `toss` | 可选`seed` | 软件生成十二枚独立公平正反，再逐层计数；不均匀抽125个编号 |

`question`只保存问题，不改变起式。不同method不得混入其他起式参数。空参数返回`needs_input`，不默认抽棋。`counts`只能说明每层数量，无法证明四枚的实际位置；可视化使用规范计数排布，并标`display_is_count_layout=true`。

```text
python <skill_root>/scripts/classic_oracles.py lingqijing --params '{"method":"counts","counts":[1,1,1]}'
python <skill_root>/scripts/classic_oracles.py lingqijing --params '{"method":"counts","counts":[0,0,0]}'
python <skill_root>/scripts/classic_oracles.py lingqijing --params '{"method":"toss","seed":"2026"}'
```

## 十二棋的概率口径

软件`toss`模式记录12个二元结果、seed、抽样算法版本与分层顺序。每层四棋；在独立公平正反模型下，0/1/2/3/4面的数量并非等概率，重数分别为1/4/6/4/1。某三层计数的重数是三个组合数C(4,n)的乘积，全部微观结果合计2¹²=4096。

例如[2,2,2]有216种微观结果，[0,0,0]仅1种。工具不会直接从125课里等概率抽一个，更不会遇全空就自动重掷。该数学模型不证明真实棋具公平，也不是占验准确概率。

算法版本为`classic-oracles-sha256-bits-v1`。seed为0..2^256−1整数或无前导零十进制字符串；浏览器宜保存字符串。未提供seed时，仅在明确`toss`模式生成并记录seed，后续可复演；记录为软件抽样，不冒称实物棋被观察过。

## 结果与可视字段

- `figure.number/name/counts/image`：查询号、原版名称、上中下计数及原象名。
- `figure.rows`：自上而下三行，每行label、marked、blank及四个faces，适于画三排四枚棋。
- `figure.display_is_count_layout`：true为规范数量示意，false为用户明确录入或软件生成的十二面顺序。
- `oracle.text`：该课“象曰”本经文；`traditional_commentary`为古代注释单列，不与正文混合；`commentary_notes`保留原注夹记。
- `oracle.editorial_notes`：校记；`cast_record`：输入/软件抽样来源及可复演记录。
- `rules`：版次、完整数据SHA、条数和计数规则。全部原文可离线查询，导航和现代译文未收录。

## 特殊编号与文本限制

十二棋皆覆对应[0,0,0]纯阴镘。原书另列在124编号卦之外，本数据以125作为查询号，并明确这是一种技术索引，不改称原书有“第一百二十五”标题。

卷下“發陽”原标“第十七”，按卷内连续卦序及棋形记录为117；原标号保留并给校记。目录页有错排、错标，数据以卷上/卷下实际卦断正文和棋形为准。正文125条均非空；个别古注有“缺”等原缺字标记，不能宣称所有古注也无缺。文本保持原字转录，未逐页核影印，存在版本异文与转录讹字的可能。

古籍的疾病、生死、诉讼、财富等词句是历史引文，不能用来诊断疾病、推寿命、保证现实结果或代替医疗、法律、财务决策。棋名里的“死象”“鬼灾”等也不等于用户将发生相应事件；现代解释与原文严格分列。
