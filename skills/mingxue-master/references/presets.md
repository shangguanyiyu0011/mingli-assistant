# 明确规则预设与结果对比

预设是本包已经实现的计算参数组合。名称只用于选择这些具体参数，不代表完整门派、传承认证或预测效力。注册表是本目录的 `presets.json`，读取与对比工具是 `scripts/presets.py`；它们不会计算、安装引擎或联网。

## 八个预设

| ID | 相对baseline的变化 | 范围与限制 |
|---|---|---|
| `baseline` | 无 | 八字sect=2、非真太阳时；紫微default/normal/forward/调闰；回归黄道P宫制 |
| `bazi-23h` | 八字sect=1 | 只改变23:00日界；不改变紫微晚子安星规则 |
| `late-zi-current` | 紫微day_divide=current | 晚子按当日规则安星；八字仍sect=2 |
| `ziwei-zhongzhou` | 紫微algorithm=zhongzhou | 仅引擎中州安星选项，非全部中州派实践 |
| `ziwei-lichun` | 紫微year_divide=exact | 仅引擎立春年界；不另改八字年界 |
| `ziwei-leap-unchanged` | 紫微fix_leap=false | 不采用半月调闰；不宣称覆盖所有闰月流派 |
| `astrology-whole-sign` | 占星house_system=W | 整宫制，仍需已知时刻和有效坐标才有宫位 |
| `astrology-lahiri` | 占星sidereal+lahiri | 真实恒星黄经基础，非完整吠陀大运、分盘与断命 |

每个条目都显式包含三体系设置和自己的限制，未更改的体系沿用基准。选择某个预设，不表示应运行全部体系，也不会自动补性别、经纬度、出生时刻或流运目标。

## Python接口

`load_profiles()` 返回新的 **list**，每项是 `{id,label,settings,limits}`；调用方可按id查找，修改返回值不会污染注册表。

`resolve_profile(name, overrides=None)` 返回同样四个键的对象。name必须是精确ID；未知ID报 `PresetError`，不会回退baseline。overrides必须按体系嵌套，局部覆写后再次校验完整组合。返回标签和limits会标明显式覆写。

```python
profile = resolve_profile("bazi-23h")
bazi_options = profile["settings"]["bazi"]
# 由调用方将这些设置交给真实chart.build_chart；本函数不排盘。

modified = resolve_profile("baseline", {
    "ziwei": {"day_divide": "current"},
    "astrology": {"house_system": "W"}
})
```

### 接受的覆写键

| 体系 | 参数 | 精确类型与可选值 |
|---|---|---|
| bazi | sect | 整数1或2，布尔值不当作整数接受 |
| bazi | true_solar | JSON布尔值；实际计算仍要求有效经度 |
| bazi | yun_sect | 整数1或2，仅真实起运算法选项 |
| ziwei | algorithm | `default` / `zhongzhou` |
| ziwei | year_divide | `normal` / `exact` |
| ziwei | day_divide | `forward` / `current` |
| ziwei | fix_leap | JSON布尔值 |
| ziwei | horoscope_divide | `normal` / `exact`，仅流运历法口径 |
| astrology | zodiac | `tropical` / `sidereal` |
| astrology | house_system | `P K O R C E W`之一 |
| astrology | ayanamsa | `lahiri` / `fagan-bradley` / `raman`；回归黄道只能省略或null |

恒星黄道必须显式指定岁差体系。把恒星预设改成回归黄道时，应同时将ayanamsa设为null。出生日期、时区、坐标、性别、scope和target等是实际输入，不是门派设置，不能放入overrides。任何未知体系、参数、错误类型、重复JSON键或非法参数组合都拒绝，不加载额外门派表。

## 比较已有真实结果

`compare_results(left, right)`接受两个完整JSON结果对象：共享八字schema=3，或紫微/占星schema=1。碎片、预设对象、错误信封、没有真实计算数据的引擎不可用结果、跨体系结果均拒绝。

调用方应对同一原始出生输入独立运行各预设，再比较输出；本函数不重算、不补盘、不根据预设名称预测“应该有”的差异。

身份与时期检查：

- 共享八字和占星要求可检查的出生事实完全一致，只允许input中的sect、true_solar、yun_sect这三个规则开关变化。日期、原钟点、历法、时区、坐标、性别、fold等发生变化，不能混称规则差异。
- 紫微要求采用的出生输入一致；有共享盘来源时，双方source_chart必须一致。hash不同或一边缺来源时，当前结果无法证明同一原始出生输入，比较拒绝。真太阳时前后造成采用日期变化的紫微盘，也不在当前自动比较范围。
- 紫微scope、完整target必须相同；流年、流月、流日还核对horoscope内scope、target和实际layers。不同目标日期、时辰或不同scope不能当门派差异。
- 结果里有subject_id、person_id或case_id时，任一不同均拒绝。这些检查只能证明记录一致，不能证明现实身份相同。

返回结构：

| 字段 | 含义 |
|---|---|
| system / identity_check | 体系与本次同输入核对方式 |
| convention_changes | 日界、算法、年界、晚子、宫制、黄道等实际规则字段差异 |
| chart_changes | 实际四柱/细项、候选、十二宫/四化/流运、天体/宫位等差异 |
| metadata_changes | 引擎版本、状态说明、来源摘要、其他未归入前两类的字段差异 |
| equal_chart | 实际盘面结构是否相同，不代表规则或元数据完全相同 |
| equal_result | 除明确忽略的路径噪声外是否无差异 |
| counts / omitted_counts | 各类全部差异数量及因展示上限省略的数量 |
| truncated | 是否有超出每类100条的差异；总数量仍完整保留 |
| ignored_path_changes | 明确文件路径字段的噪声数量与少量路径位置示例 |

每条差异含JSON Pointer路径、added/removed/changed类型和左右值。数值不设容差、不四舍五入；数组保留顺序。长值超过512字符时，展示预览、长度与SHA-256；原始完整结果仍是核对依据。每个输入最多2MiB、60000节点、48层；超限拒绝。不要把差异数量当作优劣分数或准确概率。

只忽略已知engine路径字段、顶层输出文件路径字段中真正的绝对路径变化，不忽略引擎版本、哈希、坐标、盘面值或普通字符串。对比不投票，不合并成“多数门派结论”。

## CLI

```text
python <skill_root>/scripts/presets.py --list
python <skill_root>/scripts/presets.py resolve baseline
python <skill_root>/scripts/presets.py resolve baseline --overrides <ABS_OVERRIDES_JSON>
python <skill_root>/scripts/presets.py compare --left <ABS_LEFT_JSON> --right <ABS_RIGHT_JSON>
```

输入文件路径必须为绝对路径。结果写stdout的单个JSON；错误为 `{ok:false,error:{code,message}}`，退出码2。工具不自动创建报告文件，也不保存出生资料。上层工作流若收到比较拒绝，应报告comparison_unavailable及原因，保留各自真实结果，不能跳过检查继续声称同输入门派比较。
