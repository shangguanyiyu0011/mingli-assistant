# 姓名学、字形字音字义与候选比较

用于姓名文字分析、取名候选比较、五格或三才核算。普通姓名查询无需出生资料；公司、品牌名不套用个人姓、名虚数。

汉字姓名采用下面的查字与五格合同。国际姓名采用[多语言合同](../multilingual.md)的 `mode:"international"` 分支，保留本人原名和本人提供的拉丁写法，复用现有姓名表达数，不自动音译，不返回五格或三才。国际姓名不需要下载汉字字库；日文、韩文姓名也不能仅因包含汉字而自动拆作中文姓、名。

## 三种实际模式

~~~powershell
# 旧接口：明确逐字笔画，不需要字库
python -X utf8 -B scripts/name_analysis.py --surname 欧阳 --given 修 --strokes 15,17,10 --stroke-standard "用户指定口径"

# 查精确字形、现代笔画、字音候选、英文字义和异体关系
python -X utf8 -B scripts/name_analysis.py --lookup 陈陳单單

# 字库核算：现代 IRG 口径，显式选择多音字
python -X utf8 -B scripts/name_analysis.py --surname 单 --given 明 --surname-reading shàn --given-reading míng

python -X utf8 -B scripts/name_analysis.py --compare-file "C:\absolute\candidates.json"
python -X utf8 -B scripts/name_analysis.py --probe
~~~

成功、待补输入、错误和帮助均为 JSON stdout。姓、名各支持 1 或 2 个汉字，不猜分界；字形保持原样，不自动繁简转换。

## 外置固定字库

查字使用 [Unihan 17.0.0 官方固定数据](https://www.unicode.org/Public/17.0.0/ucd/Unihan.zip)，字段解释以 [该版本规范](https://www.unicode.org/reports/tr38/tr38-39.html) 为准。索引覆盖 102998 个有选定字段的字符，但不表示每字都有读音或释义。

字库、完整原始资料和随附条款均留在技能外，不进入技能包。默认目录由 engine_directory('name-data', 'unihan-17.0.0-v1') 确定；MINGXUE_ENGINE_HOME 可改总缓存根，MINGXUE_NAME_DICTIONARY 或 --dictionary-dir 可改姓名字库目录。参数优先于姓名字库环境变量，后者优先于默认引擎目录。

只有用户明确要求准备字库时调用：

~~~powershell
python -X utf8 -B scripts/prepare_name_dictionary.py --download
python -X utf8 -B scripts/prepare_name_dictionary.py --probe
~~~

完全离线导入可同时提供 --archive 与 --terms 两个绝对路径。准备器核对原始压缩包、随附条款、派生索引的固定 SHA-256，保留全部原始资料，拒绝覆盖非空且未经核验的目录；无需全局安装依赖。版本或校验不同则停止，不擅自改源、降级或更新。

查字、计算、比较和 probe 均不联网、不自动下载。缺字库返回 needs_dictionary 或带原因的 needs_input；校验失败明确报错，不能靠改写本地 manifest 绕过索引校验。probe 的 dictionary 提供状态、版本、绝对目录及校验值。

## 笔画口径与五格

有 strokes / --strokes 时始终使用用户逐字输入，按姓、名的每次字符出现顺序给逗号分隔整数，每字 1–100。范围只是防错边界；重复字笔画须一致。旧 analyze_name(surname,given,strokes,...) 保持不依赖字库，返回 source=user_supplied、dictionary_verified=false；“康熙”标签不等于字典核验。

无显式笔画时默认 stroke_scheme='unihan-irG'：使用原写法的 kTotalStrokes，明确标为现代 IRG 总笔画约定，返回版本、字段和校验值。不能称为康熙笔画、现代汉语官方笔顺认证或姓名学部首折算。该版本 kTotalStrokes 是单一整数；地区差异资料可见 kAlternateTotalStrokes，仅列原值，不擅自选换。kRSUnicode 只作部首余画检索，不转换成康熙或姓名学总笔画。

--stroke-scheme kangxi 没有逐字笔画时返回待补输入；无笔画而另给自定义 stroke_standard / stroke_reference 也不会偷偷使用现代数据。须按用户所选字形、字典版本与部首规则核对后明确输入数值。

本版官方字段中，陈、陳的 IRG 总笔画为 7、10，不自动换字，不把 10 称作姓名学折算。单明在显式读音 shàn míng 下，以现代口径 8、8 算出天/人/地/外/总为 9/16/9/2/16。

| 项目 | 确定公式 |
|---|---|
| 天格 | 姓笔画和；单姓加虚数 1 |
| 人格 | 姓末字 + 名首字 |
| 地格 | 名笔画和；单名加虚数 1 |
| 外格 | 天格 + 地格 − 人格 |
| 总格 | 全部实际笔画和，不含虚数 |

三才按天、人、地顺序取各格原始数个位：1/2 木、3/4 火、5/6 土、7/8 金、9/0 水；奇阳偶阴。关系字段明确方向。超过 81 仍保留原数，不套未经指定版本的循环、81 断语、吉凶分数或命运排名。

## 字形、读音、字义与歧义

形：返回实际字符、Unicode 码位、部首余画检索字段、繁简/语义/兼容等异体关系。关系不保证可在姓名中直接替换；码位信息不代表验证了屏幕字体的具体字形、笔顺或历史字形。

音：保留各拼音字段来源，不替用户选多音姓。多个候选时，以 --surname-reading / --given-reading 逐字显式选择：一字一个字库带声调拼音，空格分隔，复姓同样按字对应。未知、缺失、数量不符时列待补事项，不猜拼音。一般字音候选不能证明某家姓氏专用读音，家族实际用音由用户确认。较少见或旧字典读音也保留为候选，不静默删掉。

义：kDefinition 为英文简释，原样标 language=en。没有数据就返回缺失，不编造中文词源、寓意、诗词出处或姓名专义。中文转述须标为基于已有英文释义的解释。旧 pronunciation、meaning_note 仅记录用户说明，不解除结构化读音歧义，不改变字库事实来源。

字库查询最多 128 个 Unicode 字符；姓名的姓、名仍各限 1–2 个汉字。缺字、缺字段、多音未选时有 pending_inputs；可完成的算术保留，并由 calculation_status 区分是否已算。

## 候选比较与谐音提醒

--compare-file 为绝对 JSON 路径，最多 2 MiB、50 个候选：

~~~json
{
  "surname": "王",
  "surname_reading": "wáng",
  "stroke_scheme": "unihan-irG",
  "candidates": [
    {"given": "明", "given_reading": "míng"},
    {"given": "铭", "given_reading": "míng"}
  ],
  "homophone_watchlist": [
    {"text": "用户明确关注的词", "reading": "wáng míng"}
  ]
}
~~~

候选还可含 strokes、stroke_standard、stroke_reference、meaning_note。按输入顺序比较字、音、义和数理；批次共用一个已核验字库快照。混用口径会列 stroke_conventions，same_declared_stroke_convention=false，不制造吉凶排名。

只有完全选定的读音才做匹配：候选间同拼音、去声调同拼音，以及与用户显式关注词的读音匹配。保留 ü/u 与 ê/e 区别。提醒不是负面寓意定论，不承诺覆盖方言、所有词语或网络用语；关注词拼音也须按音节以空格分隔。

~~~python
analyze_name(surname, given, strokes=None, *, stroke_standard="unspecified",
             stroke_reference=None, pronunciation=None, meaning_note=None,
             dictionary_dir=None, stroke_scheme="unihan-irG",
             surname_reading=None, given_reading=None)
compare_names(surname, candidates, *, dictionary_dir=None,
              stroke_scheme="unihan-irG", surname_reading=None,
              homophone_watchlist=None)
~~~

仅用户要求存档才加 --output：必须是技能、runtime、资源、引擎/字库缓存外的新绝对路径，拒绝覆盖已有文件。不从姓名推断身份、族裔、性格、健康、婚姻或现实命运；与其他系统交叉时分别列口径与证据。
