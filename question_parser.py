# -*- coding: utf-8 -*-
"""
question_parser.py

负责：从 Word 题库（.docx）中解析出题目列表，并保存为 JSON。

特点：
- 不按题号硬编码题型；
- 优先根据“大标题”识别题型（包含：单选/选择、填空、判断、简答/问答）；
- 没有标题时，会根据选项/答案内容做简单推断；
- 解析完会打印各题型数量，方便检查当前题库是否“长得正常”。
"""

from __future__ import annotations

import os
import re
from typing import List, Dict, Any

from docx import Document

import config
from models import Question
from storage import save_questions_to_file

# 匹配题目开始：例如 “1、xxx” “2. xxx”
QUESTION_START_RE = re.compile(r"^(\d+)[、\.．]\s*(.*)")
# 匹配选项：例如 “A、 xxx” “B. xxx”
OPTION_RE = re.compile(r"^([A-DＡ-Ｄ])[、,，\.．]\s*(.*)")
# 匹配大题标题：例如 “一、 单选题 （共100题）”
SECTION_RE = re.compile(r"^[一二三四五六七八九十]+[、\.．]\s*(.*)")

CN_OPTION_MAP = {
    "Ａ": "A",
    "Ｂ": "B",
    "Ｃ": "C",
    "Ｄ": "D",
}


def _detect_qtype_from_section(title_text: str) -> str | None:
    """根据标题文字判断题型。"""
    t = title_text
    if "单选" in t or "选择" in t:
        return config.QTYPE_SINGLE
    if "填空" in t:
        return config.QTYPE_BLANK
    if "判断" in t:
        return config.QTYPE_TF
    if "简答" in t or "问答" in t:
        return config.QTYPE_SHORT
    return None


def _parse_document(document: Document) -> List[Dict[str, Any]]:
    """
    低层解析：把 docx 的段落按“题目→选项→答案”拆成原始结构。
    这里会记录：题号、当前章节的题型、题干、选项、答案文本。
    """
    questions_raw: List[Dict[str, Any]] = []

    current: Dict[str, Any] | None = None
    state: str | None = None  # None / "question" / "options" / "answer"
    current_section_type: str | None = None  # 来自标题的题型

    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        # 1. 大标题（“一、 单选题 …”）
        m_sec = SECTION_RE.match(text)
        if m_sec:
            title_body = m_sec.group(1)
            qtype = _detect_qtype_from_section(title_body)
            if qtype:
                current_section_type = qtype
            continue

        # 2. 题目开始：例如 “123、xxxx”
        m_q = QUESTION_START_RE.match(text)
        if m_q:
            # 先收尾上一题
            if current is not None:
                questions_raw.append(current)

            number = int(m_q.group(1))
            body = m_q.group(2).strip()

            current = {
                "number": number,                # 题号
                "q_type": current_section_type,  # 当前章节推断的题型（可能为 None）
                "text_lines": [],                # 题干多行文本
                "options": {},                   # 选项 dict: { 'A': 'xxx', ... }
                "answer_lines": [],              # 答案多行文本
            }
            if body:
                current["text_lines"].append(body)

            state = "question"
            continue

        # 如果还没进入任何题目，后面的内容一律忽略
        if current is None:
            continue

        # 3. 正确答案开头：例如 “正确答案： A”
        if text.startswith("正确答案"):
            # 去掉“正确答案：”前缀，剩下的就是第一部分答案
            part = text.split("：", 1)
            if len(part) == 1:
                part = text.split(":", 1)
            ans = part[1].strip() if len(part) > 1 else ""
            if ans:
                current["answer_lines"].append(ans)
            state = "answer"
            continue

        # 4. 选项行：例如 “A、 队列”
        m_opt = OPTION_RE.match(text)
        if m_opt and state in ("question", "options"):
            label = m_opt.group(1)
            label = CN_OPTION_MAP.get(label, label)
            content = m_opt.group(2).strip()
            current["options"][label] = content
            state = "options"
            continue

        # 5. 其余内容：根据当前状态归类
        if state == "answer":
            # 答案可能拆成很多行（第1空 / 第2空 / 解析等），统统收进来
            current["answer_lines"].append(text)
        else:
            # 题干附加说明
            current["text_lines"].append(text)

    # 循环结束，把最后一题补上
    if current is not None:
        questions_raw.append(current)

    return questions_raw


def _guess_qtype_for_raw(raw: Dict[str, Any]) -> str:
    """
    为没有标题信息的题目做“兜底题型猜测”：
    - 有选项：单选题
    - 答案只有“对/错/正确/错误”等：判断题
    - 答案比较短：填空题
    - 否则：简答题
    """
    if raw.get("q_type"):
        return raw["q_type"]

    options = raw.get("options") or {}
    if options:
        return config.QTYPE_SINGLE

    ans_join = "".join(raw.get("answer_lines") or []).strip()
    ans_norm = ans_join.replace(" ", "").upper()

    tf_set = {"对", "錯", "错", "正确", "错误", "√", "×", "T", "F", "TRUE", "FALSE"}
    if ans_norm in tf_set:
        return config.QTYPE_TF

    # 比较短且单行的当作填空题，长的当作简答题
    if len(ans_norm) <= 20 and ("\n" not in ans_join):
        return config.QTYPE_BLANK

    return config.QTYPE_SHORT


def _build_questions(raw_list: List[Dict[str, Any]]) -> List[Question]:
    """
    把原始结构转成 Question 对象列表。
    注意：这里不再传 extra 参数，兼容你当前的 Question 定义。
    """
    questions: List[Question] = []

    for raw in raw_list:
        number: int = raw["number"]
        qtype = _guess_qtype_for_raw(raw)

        # 题干
        question_text = "\n".join(raw["text_lines"]).strip()

        # 选项
        options = raw["options"] or {}

        # 答案文本
        if qtype in (config.QTYPE_SINGLE, config.QTYPE_TF):
            answer_text = "".join(raw["answer_lines"]).strip()
        else:
            answer_text = "\n".join(raw["answer_lines"]).strip()

        # 这里只传当前 Question 支持的字段：id / q_type / question / options / answer
        q = Question(
            id=number,
            q_type=qtype,
            question=question_text,
            options=options,
            answer=answer_text,
        )
        questions.append(q)

    # 按题号排序，保证 1~N 依次排列
    questions.sort(key=lambda x: x.id)
    return questions


def parse_docx_to_questions(docx_path: str | None = None) -> List[Question]:
    """
    对外函数：从 .docx 解析为 Question 列表。
    """
    if docx_path is None:
        docx_path = config.DEFAULT_DOCX_PATH

    if not os.path.exists(docx_path):
        raise FileNotFoundError(f"找不到题库文件：{docx_path}")

    document = Document(docx_path)
    raw_list = _parse_document(document)
    questions = _build_questions(raw_list)
    return questions


def parse_docx_and_save_to_json(
    docx_path: str | None = None,
    json_path: str | None = None,
) -> int:
    """
    从 .docx 解析题目并保存为 JSON 文件。
    返回解析出的题目数量。
    """
    if docx_path is None:
        docx_path = config.DEFAULT_DOCX_PATH
    if json_path is None:
        json_path = config.DEFAULT_JSON_PATH

    questions = parse_docx_to_questions(docx_path)
    save_questions_to_file(questions, json_path)

    # 打印一下各题型数量，方便你在终端确认是否“识别正常”
    count_single = sum(1 for q in questions if q.q_type == config.QTYPE_SINGLE)
    count_blank = sum(1 for q in questions if q.q_type == config.QTYPE_BLANK)
    count_tf = sum(1 for q in questions if q.q_type == config.QTYPE_TF)
    count_short = sum(1 for q in questions if q.q_type == config.QTYPE_SHORT)

    print("===== 题库解析完成 =====")
    print(f"总题目数：{len(questions)}")
    print(
        f"单选题：{count_single}  填空题：{count_blank}  "
        f"判断题：{count_tf}  简答题：{count_short}"
    )
    print("=======================")

    return len(questions)
