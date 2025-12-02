# -*- coding: utf-8 -*-
"""
storage.py

统一管理本地存储：
- 题库：questions.json
- 错题本：wrong_questions.json
- 统计信息：stats.json

提供：
- save_questions_to_file / load_questions_from_file
- save_wrong_questions / load_wrong_questions
- load_stats / save_stats / reset_stats
- delete_question_bank：删除题库 + 错题本，并重置统计
"""

from __future__ import annotations

import json
import os
from typing import List, Dict, Any

import config
from models import Question

# 路径兜底（防止老版本 config 没定义时崩溃）
BASE_DIR = getattr(config, "BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
DEFAULT_JSON_PATH = getattr(
    config, "DEFAULT_JSON_PATH", os.path.join(BASE_DIR, "questions.json")
)
WRONG_JSON_PATH = getattr(
    config, "WRONG_JSON_PATH", os.path.join(BASE_DIR, "wrong_questions.json")
)
STATS_JSON_PATH = getattr(
    config, "STATS_JSON_PATH", os.path.join(BASE_DIR, "stats.json")
)


# ========== 通用 JSON 读写 ==========

def _read_json(path: str, default: Any):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # 文件坏了就返回默认值
        return default


def _write_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ========== 题库 ==========

def save_questions_to_file(
    questions: List[Question], json_path: str | None = None
) -> None:
    if json_path is None:
        json_path = DEFAULT_JSON_PATH
    data = [q.to_dict() for q in questions]
    _write_json(json_path, data)


def load_questions_from_file(json_path: str | None = None) -> List[Question]:
    if json_path is None:
        json_path = DEFAULT_JSON_PATH
    data = _read_json(json_path, default=[])
    questions: List[Question] = []
    for item in data:
        try:
            questions.append(Question.from_dict(item))
        except Exception:
            # 有问题的题目直接忽略
            continue
    return questions


# ========== 错题本 ==========

def save_wrong_questions(
    questions: List[Question], json_path: str | None = None
) -> None:
    if json_path is None:
        json_path = WRONG_JSON_PATH
    data = [q.to_dict() for q in questions]
    _write_json(json_path, data)


def load_wrong_questions(json_path: str | None = None) -> List[Question]:
    if json_path is None:
        json_path = WRONG_JSON_PATH
    data = _read_json(json_path, default=[])
    questions: List[Question] = []
    for item in data:
        try:
            questions.append(Question.from_dict(item))
        except Exception:
            continue
    return questions


# ========== 统计信息 ==========

def _default_stats() -> Dict[str, Any]:
    return {
        "total_answered": 0,
        "total_correct": 0,
        "per_type_total": {},    # { "single": 10, "blank": 5, ... }
        "per_type_correct": {},  # { "single": 8,  "blank": 3, ... }
    }


def load_stats(path: str | None = None) -> Dict[str, Any]:
    if path is None:
        path = STATS_JSON_PATH
    stats = _read_json(path, default=None)
    if not isinstance(stats, dict):
        stats = _default_stats()
        _write_json(path, stats)
        return stats

    # 保证关键字段存在
    base = _default_stats()
    base.update(stats)
    return base


def save_stats(stats: Dict[str, Any], path: str | None = None) -> None:
    if path is None:
        path = STATS_JSON_PATH
    _write_json(path, stats)


def reset_stats(path: str | None = None) -> Dict[str, Any]:
    """清零统计信息并写入文件。"""
    if path is None:
        path = STATS_JSON_PATH
    stats = _default_stats()
    _write_json(path, stats)
    return stats


# ========== 删除题库 ==========

def delete_question_bank() -> None:
    """
    删除当前题库 + 错题本，同时把统计信息重置为 0。
    """
    for p in (DEFAULT_JSON_PATH, WRONG_JSON_PATH):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

    reset_stats()
