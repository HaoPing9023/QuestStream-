# -*- coding: utf-8 -*-
"""
config.py

全局配置：
- 各种默认文件路径（Word 题库 / JSON 题库 / 错题本 / 统计信息）
- 题型常量
"""

import os

# 项目根目录（当前 config.py 所在目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 默认 Word 题库路径（可以通过 GUI "导入题库" 覆盖）
DEFAULT_DOCX_PATH = os.path.join(BASE_DIR, "questions.docx")

# 默认 JSON 题库路径（所有解析结果统一存这里）
DEFAULT_JSON_PATH = os.path.join(BASE_DIR, "questions.json")

# 错题本 JSON 路径
WRONG_JSON_PATH = os.path.join(BASE_DIR, "wrong_questions.json")

# 做题统计 JSON 路径
STATS_JSON_PATH = os.path.join(BASE_DIR, "stats.json")

# ===== 题型常量 =====
# 单选题
QTYPE_SINGLE = "single"
# 填空题
QTYPE_BLANK = "blank"
# 判断题
QTYPE_TF = "tf"
# 简答 / 问答题
QTYPE_SHORT = "short"
