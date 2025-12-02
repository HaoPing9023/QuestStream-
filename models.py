# -*- coding: utf-8 -*-
"""
models.py
定义题目等数据结构。
"""

from dataclasses import dataclass, asdict
from typing import Dict, Any


@dataclass
class Question:
    """
    题目结构体：
    - id: 题号（与你 Word 里的编号对应，比如 1~210）
    - q_type: 题型（single / blank / tf / short）
    - question: 题干文本
    - options: 选项字典（单选题用），例如 {"A": "xxx", "B": "yyy"}
    - answer: 正确答案（原文）
    - source: 来源信息（例如 "questions.docx#Q15"）
    - explanation: 解析（目前没用，先留空）
    """
    id: int
    q_type: str
    question: str
    options: Dict[str, str]
    answer: str
    source: str = ""
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """
        把 Question 对象转成普通字典，方便写入 JSON。
        dataclasses.asdict 会递归展开 dataclass。
        """
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Question":
        """
        从 JSON 里读出的 dict 恢复成 Question 对象。

        做了一点“容错”：
        - 如果某个字段缺失，就给一个默认值；
        - 这样老版本保存的 JSON 也能被新的代码读取，不会因为字段不同直接崩。
        """
        return Question(
            id=data.get("id", 0),
            q_type=data.get("q_type", ""),
            question=data.get("question", ""),
            options=data.get("options", {}) or {},
            answer=data.get("answer", ""),
            source=data.get("source", ""),
            explanation=data.get("explanation", ""),
        )
