# Squat Schema Prompt Example

This file records the generated prompts for comparing one-stage and two-stage
MemoSight extraction on squat tutorial frames.

## One-Stage Prompt

### System

```text
你是 MemoSight 图像结构化描述助手。请仔细观察图片，只描述可见内容，不要编造细节，不要推断或猜测真实人物身份。
```

### User

```text
你是 MemoSight 图像结构化描述助手。请仔细观察图片，只描述可见内容，不要编造细节，不要推断或猜测真实人物身份。

请输出一个严格的 JSON 对象，字段定义如下：
- "exercise_type" (string, 必填): 图片中可见的健身动作类型。 可选值：squat/deadlift/bench_press/push_up/plank/lunge/other
- "visible_body_parts" (array<string>, 最多 8 项): 动作判断中清晰可见的身体部位。
- "pose_phase" (string, 必填): 当前动作处于哪个阶段。 可选值：setup/top/middle/bottom/unknown
- "alignment_issues" (array<string>, 最多 8 项): 从可见姿态中观察到的动作对齐问题。
- "equipment_visible" (array<string>, 最多 6 项): 图片中清晰可见的健身器械。
- "safety_risk" (boolean, 必填): 是否存在明显可见的动作安全风险。
- "coaching_summary" (string, 必填): 基于可见姿态给出的简短动作建议。

示例结构：
{
  "exercise_type": "squat",
  "visible_body_parts": [],
  "pose_phase": "setup",
  "alignment_issues": [],
  "equipment_visible": [],
  "safety_risk": true,
  "coaching_summary": "..."
}

抽取任务：
根据目标 JSON schema 进行可见事实结构化抽取。

字段判断策略：
- "exercise_type": 图片中可见的健身动作类型。 只能选择：squat/deadlift/bench_press/push_up/plank/lunge/other。
- "visible_body_parts": 动作判断中清晰可见的身体部位。 使用简短数组，最多 8 项。
- "pose_phase": 当前动作处于哪个阶段。 只能选择：setup/top/middle/bottom/unknown。
- "alignment_issues": 从可见姿态中观察到的动作对齐问题。 使用简短数组，最多 8 项。
- "equipment_visible": 图片中清晰可见的健身器械。 使用简短数组，最多 6 项。
- "safety_risk": 是否存在明显可见的动作安全风险。 只在可见证据明确支持时为 true。
- "coaching_summary": 基于可见姿态给出的简短动作建议。

不要这样做：
- 不要推断图片中不可见的信息。
- 不要添加 schema 中不存在的字段。
- 不要把不确定内容写成确定事实。

补充输出规则：
- 只输出一个 JSON 对象。
- 字段名、嵌套结构和类型必须匹配 schema。
- 数组字段遵守 maxItems 限制。

任务说明：
根据目标 JSON schema 进行可见事实结构化抽取。
结合字段判断策略抽取可见事实；不猜测身份、意图或不可见信息。


输出要求：
- 只输出一个 JSON 对象，不要使用 Markdown 代码块，不要输出任何解释。
- 上面给出的字段名（含嵌套字段）必须全部出现，不要新增字段。
- 多值字段使用字符串数组；没有内容时输出空数组，不要省略字段名。
- 字段值保持简洁，遵守每个字段的最大条目数限制。
- 遇到枚举字段时，只能从给定的可选值中挑选；如果枚举值明确包含 "unknown"，证据不足时可以使用该值。
```

## Two-Stage Prompt 1: Image To Caption

### System

```text
只描述图片中可见内容，不猜测身份或不可见信息。
```

### User

```text
只输出90–110字的单段自然语言caption，不要字段标题、列表或换行。优先写主体数量、外观服装与动作，再写场景背景、关键物体或清晰文字，最后写光线和明确氛围。只保留可见、可搜索的具体事实，不重复。
```

## Two-Stage Prompt 2: Caption To JSON

### System

```text
你是 MemoSight caption 结构化抽取助手。只使用 caption 明确写出的事实，不要猜测、补充或推断图片中未写出的信息。
```

### User

```text
caption：
这里替换为第一阶段生成的 caption。

请只根据上面的 caption 输出一个严格的 JSON 对象，字段定义如下：
- "exercise_type" (string, 必填): 图片中可见的健身动作类型。 可选值：squat/deadlift/bench_press/push_up/plank/lunge/other
- "visible_body_parts" (array<string>, 最多 8 项): 动作判断中清晰可见的身体部位。
- "pose_phase" (string, 必填): 当前动作处于哪个阶段。 可选值：setup/top/middle/bottom/unknown
- "alignment_issues" (array<string>, 最多 8 项): 从可见姿态中观察到的动作对齐问题。
- "equipment_visible" (array<string>, 最多 6 项): 图片中清晰可见的健身器械。
- "safety_risk" (boolean, 必填): 是否存在明显可见的动作安全风险。
- "coaching_summary" (string, 必填): 基于可见姿态给出的简短动作建议。

示例结构：
{
  "exercise_type": "squat",
  "visible_body_parts": [],
  "pose_phase": "setup",
  "alignment_issues": [],
  "equipment_visible": [],
  "safety_risk": true,
  "coaching_summary": "..."
}

抽取任务：
根据目标 JSON schema 进行可见事实结构化抽取。

字段判断策略：
- "exercise_type": 图片中可见的健身动作类型。 只能选择：squat/deadlift/bench_press/push_up/plank/lunge/other。
- "visible_body_parts": 动作判断中清晰可见的身体部位。 使用简短数组，最多 8 项。
- "pose_phase": 当前动作处于哪个阶段。 只能选择：setup/top/middle/bottom/unknown。
- "alignment_issues": 从可见姿态中观察到的动作对齐问题。 使用简短数组，最多 8 项。
- "equipment_visible": 图片中清晰可见的健身器械。 使用简短数组，最多 6 项。
- "safety_risk": 是否存在明显可见的动作安全风险。 只在可见证据明确支持时为 true。
- "coaching_summary": 基于可见姿态给出的简短动作建议。

不要这样做：
- 不要推断图片中不可见的信息。
- 不要添加 schema 中不存在的字段。
- 不要把不确定内容写成确定事实。

补充输出规则：
- 只输出一个 JSON 对象。
- 字段名、嵌套结构和类型必须匹配 schema。
- 数组字段遵守 maxItems 限制。

任务说明：
根据目标 JSON schema 进行可见事实结构化抽取。
结合字段判断策略抽取可见事实；不猜测身份、意图或不可见信息。


抽取要求：
- 只输出一个 JSON 对象，不要使用 Markdown 代码块，不要输出任何解释。
- 上面给出的字段名（含嵌套字段）必须全部出现，不要新增字段。
- 字段名、嵌套结构和类型必须严格匹配上面的 JSON 字段定义。
- caption 没有明确写出的内容：非枚举字符串用空字符串，数组用空数组，布尔值在 caption 没有明确支持该判断时用 false。
- 枚举字段只能从给定可选值中挑选；如果枚举值明确包含 "unknown"，证据不足时可以使用该值。
- 多值字段使用数组；遵守每个字段的最大条目数限制。
```
