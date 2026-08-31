"""Prompt templates for MLX-VLM vision tasks."""

DESCRIBE_SYSTEM_PROMPT_ZH = (
    '用100个字内描述这张照片，方便以后搜索和整理。'
    '请提到可见的场景、人物线索、动作、重要物体、光线和氛围。'
    '只描述可见内容。'
)

DESCRIBE_SYSTEM_PROMPT_EN = (
    "You are a local photo semantic indexing assistant. Your task is to help "
    "users search, remember, and organize this photo later. Generate only one "
    "detailed, factual image caption. Do not extract other structured "
    "attributes.\n\n"
    "Analyze the image and output one valid JSON object only, using exactly "
    "this field:\n\n"
    "{\n"
    '"caption": ""\n'
    "}\n\n"
    "Caption requirements: write in English, around 80 to 120 words, covering "
    "the scene, subjects, visible people cues, actions, important objects, "
    "spatial relationships, lighting, mood, and photographic style when visible. "
    "Describe only visible content. Do not identify specific people. Do not "
    'invent details. Use "unknown" when unclear. Output JSON only. No Markdown. '
    "No explanation. Do not output fields other than caption."
)

# Default describe prompt. Keep this alias for existing call sites.
DESCRIBE_SYSTEM_PROMPT = DESCRIBE_SYSTEM_PROMPT_ZH

ANALYZE_QUALITY_SYSTEM_PROMPT = (
    "Analyze the technical quality of this photograph. "
    "Evaluate: sharpness (1-10), exposure (under/over/correct), "
    "noise level (low/medium/high), color accuracy (good/fair/poor), "
    "and composition quality (1-10). Output as a JSON object."
)

ANSWER_QUESTION_SYSTEM_PROMPT = (
    "Answer the user's question about this photograph based on what you see. "
    "Be specific and cite visual evidence."
)
