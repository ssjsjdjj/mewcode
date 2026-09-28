"""上下文管理的全部硬编码阈值常量（ch08）。

所有长度度量一律按 UTF-8 字节（len(s.encode("utf-8"))），与 token 估算换算
系数 ESTIMATE_CHARS_PER_TOKEN 配套使用。
"""

from __future__ import annotations

# 单条工具结果超过该字节数必须落盘替换为预览体。
SINGLE_RESULT_LIMIT = 50000

# 单条 tool 消息内所有工具结果聚合字节数上限，超出部分按字节倒序落盘。
MESSAGE_AGGREGATE_LIMIT = 200000

# 触发第 2 层压缩时，为摘要+恢复内容预留的 token 余量。
SUMMARY_RESERVE = 20000

# 自动压缩路径的安全余量：threshold = context_window - 该值。
AUTO_SAFETY_MARGIN = 13000

# 手动/紧急压缩路径的安全余量（更激进）。
MANUAL_SAFETY_MARGIN = 3000

# 恢复附件中最多携带的最近读文件数。
RECOVERY_FILE_LIMIT = 5

# 每个读文件条目在恢复附件中允许的 token 预算。
RECOVERY_TOKENS_PER_FILE = 5000

# 第 2 层压缩后保留的近期原文 token 下界。
RECENT_KEEP_TOKENS = 10000

# 第 2 层压缩后保留的近期原文消息条数下界。
RECENT_KEEP_MESSAGES = 5

# 自动压缩连续失败达到该次数后熔断（跳过自动第 2 层）。
MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES = 3

# 摘要请求遭遇 PromptTooLongError 时逐组丢弃的前置重试次数。
PTL_RETRY_LIMIT = 3

# 前置重试用尽后，每轮丢弃的剩余组比例（至少 1 组）。
PTL_DROP_PERCENTAGE = 0.2

# token 估算换算系数：每 token 约等于的字符数。
ESTIMATE_CHARS_PER_TOKEN = 3.5

# 预览体头部预览的最大字节数。
PREVIEW_HEAD_BYTES = 2048

# 预览体头部预览的最大行数。
PREVIEW_HEAD_LINES = 20
