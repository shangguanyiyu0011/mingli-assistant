# 西方土占：四母、盾盘与十二宫盘

用于用户明确要求西方 geomancy、点线土占、盾盘、四母生成或对应宫盘的场景。本版是四行单双点系统，不与中国六爻、六十四卦或地理风水混称。

## 实际入口与输入

~~~python
from oracles import calculate
result = calculate("geomancy", {
    "mothers": ["1112", "1211", "2122", "2211"],
    "shield_size": 16, "house_mode": "sequential"
})
~~~

~~~powershell
python -X utf8 -B scripts/oracles.py geomancy --params '{"seed":42,"shield_size":15,"house_mode":"agrippa"}'
python -X utf8 -B scripts/oracles.py --probe
~~~

三类初始输入互斥：

- mothers：恰好四个四位字符串，如 1112；每位只能是 1 或 2。
- point_counts：四母各四行原始点数的 4x4 整数矩阵，每个数 1–1000000，奇数归 1、偶数归 2；保留实际输入，不伪造抽样。
- seed：0 至 2²⁵⁶−1 的整数或十进制字符串，实际生成 16 条等概率单/双点线。都未给时生成并记录随机 seed。

每母内部从上到下固定为火、风、水、土。1 为奇数/单点，2 为偶数/双点。字符串顺序是上行到下行，不按二进制位从低到高倒置。question 只记录提问，不影响同 seed 生成。probe 不调用随机源或网络。

## 确定的生成法

四母记 M1–M4。第 j 女 Dj，依次取 M1、M2、M3、M4 的第 j 行，属于矩阵转置。两图逐行相加时，奇数和归 1、偶数和归 2；等价于同点数得 2、不同点数得 1，不把偶数显示成 0。

| 图 | 来源 |
|---|---|
| N1、N2 | M1+M2、M3+M4 |
| N3、N4 | D1+D2、D3+D4 |
| 右证人 WR | N1+N2 |
| 左证人 WL | N3+N4 |
| 法官 J | WR+WL |
| 调和图 R | M1+J，仅 16 图版存在 |

shield_size 可选 15 或 16（默认）。15 图版明确无调和图，不将它画为零点或空白第 16 图。完整 16 种点形均有拉丁传统名、中文标签、简短关键词、四行点数和 UI 点阵。法官总点数应为偶数，checks 提供结构校验；“大吉/小吉”等为传统图名，不保证现实成功。

盾盘顶部视觉上从左到右是 D4、D3、D2、D1、M4、M3、M2、M1；数学 ID 和母图输入顺序保持不变。每个节点有 derivation 来源与 edges 连线，女图还列 source_line，便于点击查看过程。

## 宫盘映射口径

house_mode 为 sequential（默认）时，第 1–12 宫依次放 M1、M2、M3、M4、D1、D2、D3、D4、N1、N2、N3、N4。

house_mode 为 agrippa 时，第 1–12 宫依次放 M1、D1、N1、M4、D4、N4、M3、D3、N3、M2、D2、N2。结果 rules.house_mapping 总是完整列出这张表，不依赖 UI 猜顺序。两种方式只改变十二宫对应，不改变已生成的盾盘。

宫盘图从左侧第 1 宫向左下第 2 宫编号，第 4 宫在下、第 7 宫在右、第 10 宫在上。它是固定图位排布，不是根据出生时间计算的黄道宫头，也不声称计算了行星、星座或所有流派的成全法。

## 可视与复现

顶层 shield 提供 15/16 节点及生成边，house_chart 提供 12 宫与 source_figure。visual.type 为 geomancy；visual.shield.svg 与 visual.house.svg 是独立矢量图，适合做“盾盘/宫盘”两视图。盾盘节点 x 是水平中心、y 是框顶；宽高和所有点行均在 JSON 中。宫盘节点 x/y 是各图中心。

input 保留用户实际提供的母图/点数或生成 seed，initial_mothers 列最终用于推演的四母。相同版本下可将 result.input 重新传给 calculate 复现；seed 来源标签可能从 generated 变为 caller_supplied，但图形不变。

虚拟生成明确标 virtual_draw，手工母图/点数分别标 user_supplied_mothers/user_supplied_point_counts；不假称用户已经划沙或发生超自然事件。解读限定为文化象征与反思，不用图形确证第三方秘密、疾病、死亡或财务结果。

只依赖标准库，计算、probe 不联网、不默认写文件。可选 --output 仅允许安装代码、资源和引擎缓存外的新绝对 JSON 路径，不覆盖已有文件。
