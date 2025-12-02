# -*- coding: utf-8 -*-
"""
stats_view.py
负责展示刷题统计信息（从 stats.json 读取）。
"""

from typing import Dict

import config
from storage import load_stats


def _qtype_label(q_type: str) -> str:
    """把题型代码转换成中文描述。"""
    if q_type == config.QTYPE_SINGLE:
        return "单选题"
    if q_type == config.QTYPE_BLANK:
        return "填空题"
    if q_type == config.QTYPE_TF:
        return "判断题"
    if q_type == config.QTYPE_SHORT:
        return "简答题"
    return f"未知类型({q_type})"


def _format_rate(correct: int, total: int) -> str:
    """格式化百分比。"""
    if total <= 0:
        return "0.00%"
    return f"{correct * 100.0 / total:.2f}%"


def show_stats():
    """
    从 stats.json 读取统计数据，并在命令行友好展示。
    """
    stats: Dict = load_stats()

    total_answered = stats.get("total_answered", 0)
    total_correct = stats.get("total_correct", 0)
    per_type_answered = stats.get("per_type_answered", {}) or {}
    per_type_correct = stats.get("per_type_correct", {}) or {}

    print("\n====== 做题统计概览 ======\n")

    print(f"总答题数：{total_answered}")
    print(f"总正确数：{total_correct}")
    print(f"总体正确率：{_format_rate(total_correct, total_answered)}")
    print()

    if not per_type_answered:
        print("当前还没有任何刷题记录。")
        print("提示：先去“开始刷题”完成一轮练习，这里就会有数据了。")
        return

    print("各题型统计：")
    print("-" * 40)
    for q_type, total in per_type_answered.items():
        correct = per_type_correct.get(q_type, 0)
        print(
            f"{_qtype_label(q_type):<10} "
            f"答题数：{total:<4} "
            f"正确数：{correct:<4} "
            f"正确率：{_format_rate(correct, total)}"
        )
    print("-" * 40)
    print("说明：统计数据是累积的，每次刷题都会叠加。")
