# Agent 更正与重新规划

`scripts/agent_updates.py` 对一次已有的个人／双人任务作更正。它读取原生收集请求重新规划，不把旧工作流中派生的本人日期继续合入新出生资料。

```python
from agent_updates import update_job

# patch 只合入 A 的原生 people[0]，不改 B。
result = update_job(job_dir, {"birth": {"date": "1991-06-15"}}, person="A")

# 时辰更正为未知，不用中午或原钟点代替。
result = update_job(job_dir, {"birth": {"time": None}}, person="A")

# person 省略时更正整个原生请求。
result = update_job(job_dir, {"preferences": {"question": "新的独立问题", "answers": {"当前关注": ["学习", "沟通"]}}})
```

输入任务须由 `intake_flow.submit` 创建，目录名为 32 位小写十六进制，使用外置绝对路径，包含原始 `submitted-input.json` 及已有 `project-a`、可选 `project-b`。任务及私有请求拒绝符号链接／目录联接，路径不能进入插件、引擎、资源或 Python 目录。

优先读取 `current-request.json`，不存在时使用 `submitted-input.json`。指定 `person="A"/"B"` 时，patch 只允许 `person/birth/location/name`，合入对应人物。`person=None` 时合入整个原生请求；`people` 数组是完整替换，不逐项合并，也不猜测哪项属于哪人。更正保持原任务 `single/pair` 人数，改变人数应创建新任务。

原生更正采用 `project_store.merge_patch` 的规则：对象递归合并、数组替换，`null` 保留以表达原生协议允许的未知值，例如 `birth.time:null` 或 `preferences.cast:null`。非 nullable 的原生参数不接受 null，不能把它当成任意参数的删除命令。非法的 null、未知参数、出生日期或人物资料仍会在写个人新版本前拒绝；原生 schema 见 [基础表协议](intake.md)。

## 更正如何生效

1. 对完整新原生请求运行 `normalize_request` 与 `plan_request`，分别重算数秘的公历生日、宿曜的本人日期、七政的本人日期时空等派生输入，重新评估所有待补条件。
2. 读取每人的当前提交，目标配置只来自新计划，并原样附入当前 `readings`。旧结果 SHA 或问题／人物上下文已变时，由工作流自然标记旧文字为 `stale`。
3. 完整新目标经 `workflow.normalize_input` 校验后，以 `run_project(project, target)` 提交。已有项目仍按当前缓存规则复用实际结果并保存历史；完整目标会移除已不适用的嵌套参数和旧 deferred，保留真实的未知时辰 null。诊断 diff 仅用于判断是否无需新版本。
4. 无变化的人物跳过新版本。例如只改 B 的生日时，A 的 HEAD 和实际结果均不推进。独立起卦时空、实际牌、显式 seed 不从生日改写；只更正问题或问答时沿用未变方法的现有结果。
5. 手面相的可见观察改变时写新的私有文件，再由工作流快照。已有提交中的观察文件从不覆写；未变化的观察复用旧快照路径。
6. 所有人物处理完成后才原子保存完整原生 `current-request.json`。原始 `submitted-input.json` 永久保留。每次更正使用任务级锁，重复并发更正会被拒绝。

## 返回与失败边界

```json
{
  "status": "updated",
  "request_committed": true,
  "job_id": "32位任务标识",
  "job_dir": "ABS",
  "revisions": {"A": {"revision": "v000003", "status": "ready", "changed": true, "recomputed": ["numerology"], "reused": ["tarot"]}},
  "questions": [],
  "warnings": []
}
```

若完整请求已保存但仍有待补方法，返回 `partial/request_committed:true`，补问保持独立、可跳过。非法 patch 抛出校验异常，不新增个人版本。若某个人物执行途中失败，返回 `partial/request_committed:false` 及已完成的版本记录，不写入新的 current-request，也不谎称双方已完成。

双人更新不是跨目录数据库事务：前一人已提交而后一人失败时会保留前一人的真实版本。此时必须拒绝混合快照作为完整报告；可修复依赖后用同一更正重试，已达到目标的人物会跳过，随后补齐并保存原生请求。不要手改 HEAD 或覆盖旧版本。

本 helper 不重写最初任务顶层的草稿 HTML，也不修改已导出的最终 HTML。更正完成后应通过 Agent 的当前快照、解读绑定与最终导出步骤生成新的报告成品。更正不证明传统解释有效，也不把用户问答当作预测验证。

## 实际验收

`python -X utf8 -B -m unittest discover -s tests -p test_agent_updates.py -v` 稳定重跑 9 项通过，无跳过，62.136 秒。实际验证了：1990→1991 的数秘、七政本人日期重派生及旧解读失效；农历数秘／宿曜重规划；补时辰移除旧 deferred；生日、问题与问答更正沿用独立牌面和起卦时空；撤回 cast 后真正移除旧工作流起卦参数；只改 B 不推进 A；旧原件及观察快照不覆写；非法更正和锁冲突不新增版本；双人中断返回 partial/false 后以同一更正恢复。路径保护包含外置绝对目录与模拟链接逃逸，不依赖 Windows 创建符号链接权限。
