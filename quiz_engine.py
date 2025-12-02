# -*- coding: utf-8 -*-
"""
quiz_engine.py
刷题核心逻辑：
- 从 JSON 题库加载题目
- 支持按题型随机抽题
- 命令行交互刷题，立即判对错
- 记录错题，维护错题本
- 对简答题采用“自评模式”：系统不自动判分，由你自己根据参考答案判断是否算对
- 每一轮刷题结束后，更新全局做题统计（存到 stats.json）
"""

import random
from typing import List, Tuple, Dict

import config
from models import Question
from storage import (
    load_questions_from_file,
    load_wrong_questions,
    save_wrong_questions,
    load_stats,
    save_stats,
)

# ==================== 辅助函数：类型、显示 ====================

def _get_qtype_label(q_type: str) -> str:
    """
    把内部题型代码转成中文描述。
    """
    if q_type == config.QTYPE_SINGLE:
        return "单选题"
    if q_type == config.QTYPE_BLANK:
        return "填空题"
    if q_type == config.QTYPE_TF:
        return "判断题"
    if q_type == config.QTYPE_SHORT:
        return "简答题"
    return "未知题型"


def _normalize_option_label(label: str) -> str:
    """
    选项字母标准化：全角 -> 半角，大写。
    """
    label = label.strip().upper()
    full_width = "ＡＢＣＤＥＦＧＨ"
    half_width = "ABCDEFGH"
    trans = str.maketrans(full_width, half_width)
    return label.translate(trans)


# ==================== 交互：选择题型 / 数量 ====================

def _choose_question_type_interactive() -> str | None:
    """
    让用户在命令行选择要刷的题型。

    返回值：
    - config.QTYPE_SINGLE / QTYPE_BLANK / QTYPE_TF / QTYPE_SHORT
    - "__ALL__" 表示“全部题型混合”
    - None 表示“取消”
    """
    print("\n=== 选择题型 ===")
    print("1. 单选题")
    print("2. 填空题")
    print("3. 判断题")
    print("4. 简答题")
    print("9. 全部题型混合")
    print("0. 取消返回主菜单")

    while True:
        choice = input("请输入编号并回车：").strip()
        if choice == "0":
            return None
        if choice == "1":
            return config.QTYPE_SINGLE
        if choice == "2":
            return config.QTYPE_BLANK
        if choice == "3":
            return config.QTYPE_TF
        if choice == "4":
            return config.QTYPE_SHORT
        if choice == "9":
            return "__ALL__"
        print("输入无效，请输入 0 / 1 / 2 / 3 / 4 / 9。")


def _ask_question_count(max_count: int) -> int:
    """
    让用户输入本次要刷的题目数量。
    """
    print(f"\n当前可用题目数量：{max_count} 道。")
    default_num = min(10, max_count)
    print(f"建议：一次先刷 {default_num} 道题。")

    while True:
        s = input(
            f"请输入本次要刷的题目数量 (1 ~ {max_count})，"
            f"直接回车默认 {default_num}："
        ).strip()

        # 直接回车使用默认数
        if not s:
            return default_num

        try:
            n = int(s)
        except ValueError:
            print("请输入一个整数，比如 5、10、20。")
            continue

        if 1 <= n <= max_count:
            return n
        else:
            print(f"数量必须在 1 ~ {max_count} 范围内，请重新输入。")


def _filter_questions_by_type(
    questions: List[Question],
    q_type_choice: str | None,
) -> List[Question]:
    """
    根据用户选择的题型过滤题目列表。
    """
    if q_type_choice is None:
        return []

    if q_type_choice == "__ALL__":
        # 全部类型混合
        return list(questions)

    return [q for q in questions if q.q_type == q_type_choice]


# ==================== 答案归一化与判题 ====================

def _normalize_single_correct_answer(ans: str) -> str:
    """
    单选题：把正确答案规范成选项字母组合（A/B/C...），大写。
    """
    import re
    labels = re.findall(r"[A-HＡ-Ｈ]", ans.upper())
    labels = [_normalize_option_label(ch) for ch in labels]
    labels = sorted(set(labels))
    return "".join(labels)


def _normalize_single_user_answer(raw: str) -> str:
    """
    单选题：把用户输入归一化成选项字母组合。
    """
    raw = raw.strip().upper()
    if not raw:
        return ""

    import re
    labels = re.findall(r"[A-HＡ-Ｈ]", raw)
    labels = [_normalize_option_label(ch) for ch in labels]
    labels = sorted(set(labels))
    return "".join(labels)


def _normalize_tf_correct_answer(ans: str) -> str:
    """
    判断题：把正确答案规范成 "T" 或 "F"。
    """
    s = ans.strip().replace(" ", "").replace("。", "").upper()
    if s in {"对", "正确", "T", "TRUE", "Y", "YES", "1"}:
        return "T"
    if s in {"错", "错误", "F", "FALSE", "N", "NO", "0"}:
        return "F"
    return s


def _normalize_tf_user_answer(raw: str) -> str:
    """
    判断题：把用户输入归一化成 "T" 或 "F"。
    """
    s = raw.strip().replace(" ", "").replace("。", "").upper()
    if s in {"对", "正确", "T", "TRUE", "Y", "YES", "1"}:
        return "T"
    if s in {"错", "错误", "F", "FALSE", "N", "NO", "0"}:
        return "F"
    return s


def _normalize_text_answer(ans: str) -> str:
    """
    填空题 / 简答题：简单归一化处理（压缩空白）。
    """
    ans = ans.strip()
    import re
    ans = re.sub(r"\s+", " ", ans)
    return ans


def _check_answer(question: Question, user_raw: str) -> Tuple[bool, str, str]:
    """
    判定用户答案是否正确（自动判分部分）。

    返回：(是否正确, 规范化后的用户答案, 规范化后的正确答案)

    注意：
    - 对于简答题（QTYPE_SHORT），这里的“是否正确”一律返回 False，
      只提供规范化后的文本，真正的判分交给用户自评。
    """
    q_type = question.q_type

    # 单选题
    if q_type == config.QTYPE_SINGLE:
        correct_norm = _normalize_single_correct_answer(question.answer)
        user_norm = _normalize_single_user_answer(user_raw)
        return user_norm == correct_norm and correct_norm != "", user_norm, correct_norm

    # 判断题
    if q_type == config.QTYPE_TF:
        correct_norm = _normalize_tf_correct_answer(question.answer)
        user_norm = _normalize_tf_user_answer(user_raw)
        return user_norm == correct_norm and correct_norm in {"T", "F"}, user_norm, correct_norm

    # 填空题：严格字符串比较（可以后续再改宽松）
    if q_type == config.QTYPE_BLANK:
        correct_norm = _normalize_text_answer(question.answer)
        user_norm = _normalize_text_answer(user_raw)
        return user_norm == correct_norm and correct_norm != "", user_norm, correct_norm

    # 简答题：不自动判分，只做规范化，返回 False
    if q_type == config.QTYPE_SHORT:
        correct_norm = _normalize_text_answer(question.answer)
        user_norm = _normalize_text_answer(user_raw)
        return False, user_norm, correct_norm

    # 理论上不会走到这里
    correct_norm = _normalize_text_answer(question.answer)
    user_norm = _normalize_text_answer(user_raw)
    return False, user_norm, correct_norm


# ==================== 统计更新 ====================

def _update_stats(per_type_total: Dict[str, int], per_type_correct: Dict[str, int]) -> None:
    """
    把本轮刷题的统计，累加到全局 stats.json 里。
    """
    if not per_type_total:
        return

    stats = load_stats()

    # 总量
    total_answered_round = sum(per_type_total.values())
    total_correct_round = sum(per_type_correct.values())

    stats["total_answered"] = stats.get("total_answered", 0) + total_answered_round
    stats["total_correct"] = stats.get("total_correct", 0) + total_correct_round

    # 各题型
    pa = stats.setdefault("per_type_answered", {})
    pc = stats.setdefault("per_type_correct", {})

    for q_type, n in per_type_total.items():
        pa[q_type] = pa.get(q_type, 0) + n
    for q_type, n in per_type_correct.items():
        pc[q_type] = pc.get(q_type, 0) + n

    save_stats(stats)


# ==================== 核心：出题 + 做题 ====================

def _print_question(q: Question, index: int, total: int) -> None:
    """
    在命令行打印一道题目。
    """
    print("\n" + "=" * 40)
    print(f"第 {index} / {total} 题  [{_get_qtype_label(q.q_type)}]  (题号: {q.id})")
    print("-" * 40)
    print(q.question)
    print()

    # 如果有选项，按字母顺序打印
    if q.options:
        for label in sorted(q.options.keys()):
            print(f"{label}. {q.options[label]}")
        print()


def _ask_self_judge_for_short() -> bool:
    """
    简答题自评：询问用户“你觉得自己是否答对”。

    返回：
    - True 表示算对
    - False 表示算错
    """
    while True:
        s = input("【自评】你觉得自己是否答对？(y=算对 / n=算错，直接回车视为 n)：").strip().lower()
        if s in ("y", "yes"):
            return True
        if s in ("n", "no", ""):
            return False
        print("请输入 y 或 n。")


def _do_quiz_session(questions: List[Question]) -> Tuple[int, int, List[Question]]:
    """
    进行一轮刷题，会逐题提问、判分，并返回结果。

    :param questions: 本轮要做的题目列表（已经按题型、数量筛好）
    :return: (正确数, 总题数, 错题列表)
    """
    if not questions:
        print("当前没有题目可做。")
        return 0, 0, []

    # 打乱题目顺序
    questions = list(questions)
    random.shuffle(questions)

    total = len(questions)
    correct_count = 0
    wrong_questions: List[Question] = []

    # 本轮统计：按题型统计总答题数 / 正确数
    per_type_total: Dict[str, int] = {}
    per_type_correct: Dict[str, int] = {}

    print(f"\n本轮共 {total} 道题，开始刷题！")
    print("提示：当前版本不支持中途优雅退出统计，若要强制退出可以 Ctrl + C。")

    for idx, q in enumerate(questions, start=1):
        _print_question(q, idx, total)

        user_raw = input("请输入你的答案：").strip()

        # 自动判分（简答题这里一定是 False）
        is_correct, user_norm, correct_norm = _check_answer(q, user_raw)

        # 展示参考答案（原文）
        print("\n你的原始答案：", user_raw if user_raw else "(空)")
        print("参考答案（题库原文）：")
        print(q.answer if q.answer.strip() else "(题库中未设置答案)")
        print()

        # 简答题：不自动判分，交给你自己决定
        if q.q_type == config.QTYPE_SHORT:
            print("【提示】简答题不自动判分，请自己对照参考答案。")
            is_correct = _ask_self_judge_for_short()
        else:
            # 对于单选 / 判断 / 填空题，使用自动判分结果
            if is_correct:
                print("✅ 回答正确！")
            else:
                print("❌ 回答错误！")

        # 单选 / 判断题：展示规范化答案对比
        if q.q_type in (config.QTYPE_SINGLE, config.QTYPE_TF):
            print(f"【规范化对比】你的答案：{user_norm or '(空)'}，标准答案：{correct_norm or '(未知)'}")

        # 统计：按题型累加
        t = q.q_type
        per_type_total[t] = per_type_total.get(t, 0) + 1
        if is_correct:
            per_type_correct[t] = per_type_correct.get(t, 0) + 1
            correct_count += 1
        else:
            wrong_questions.append(q)

        print("-" * 40)
        input("按回车键继续做下一题...")

    print("\n本轮刷题结束！")
    print(f"总题数：{total}，答对：{correct_count}，答错：{total - correct_count}")
    if total > 0:
        rate = correct_count * 100.0 / total
        print(f"正确率：{rate:.2f}%")

    # 把本轮统计写入全局 stats.json
    _update_stats(per_type_total, per_type_correct)

    return correct_count, total, wrong_questions


# ==================== 封装：普通刷题 / 错题本刷题 ====================

def run_normal_quiz():
    """
    普通模式刷题。
    """
    all_questions = load_questions_from_file()
    if not all_questions:
        print("\n【提示】当前题库为空。")
        print("请先在主菜单中选择：1. 从 Word 解析题库（生成 JSON）。")
        return

    q_type_choice = _choose_question_type_interactive()
    if q_type_choice is None:
        print("已取消，返回主菜单。")
        return

    selected_pool = _filter_questions_by_type(all_questions, q_type_choice)
    if not selected_pool:
        print("\n【提示】当前题库中没有该类型的题目。")
        return

    num = _ask_question_count(len(selected_pool))
    questions = random.sample(selected_pool, k=num)

    _, _, wrong_list = _do_quiz_session(questions)

    if wrong_list:
        existing_wrong = load_wrong_questions()
        by_id = {q.id: q for q in existing_wrong}
        for w in wrong_list:
            by_id[w.id] = w
        new_wrong_list = list(by_id.values())
        save_wrong_questions(new_wrong_list)
        print(f"\n本轮新增错题 {len(wrong_list)} 道，错题本总数：{len(new_wrong_list)} 道。")
    else:
        print("\n本轮没有新增错题，错题本保持不变。")


def run_wrong_quiz():
    """
    错题本模式刷题。
    """
    wrong_all = load_wrong_questions()
    if not wrong_all:
        print("\n【提示】当前错题本为空。")
        print("可以先用“开始刷题”做一轮题，系统会自动记录做错的题目。")
        return

    print(f"\n当前错题本中共有 {len(wrong_all)} 道题。")

    num = _ask_question_count(len(wrong_all))
    questions = random.sample(wrong_all, k=num)

    _, _, wrong_list = _do_quiz_session(questions)

    wrong_ids_this_round = {q.id for q in wrong_list}
    by_id = {q.id: q for q in wrong_all}

    for q in questions:
        if q.id in wrong_ids_this_round:
            by_id[q.id] = q
        else:
            by_id.pop(q.id, None)

    new_wrong_list = list(by_id.values())
    save_wrong_questions(new_wrong_list)

    print(f"\n本轮练习结束后，错题本剩余题目数量：{len(new_wrong_list)} 道。")
    if len(new_wrong_list) == 0:
        print("恭喜，当前错题本已经清空！")
