# -*- coding: utf-8 -*-
"""
main.py

命令行版入口（简易菜单）：
1. 从 Word 解析题库（生成 JSON）
2. 开始刷题（按题型随机抽题）
3. 只刷错题（从错题本中抽题）
4. 查看做题统计
0. 退出
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import config
from question_parser import parse_docx_and_save_to_json
from quiz_engine import run_normal_quiz, run_wrong_quiz
from storage import load_stats


def clear_screen():
    """清屏（简单版本）。"""
    os.system("cls" if os.name == "nt" else "clear")


def pause():
    input("\n按回车键返回主菜单...")


def print_menu():
    clear_screen()
    print("========================================")
    print(" 本地刷题系统 - 命令行版")
    print("========================================")
    print("1. 从 Word 解析题库（生成 JSON）")
    print("2. 开始刷题（按题型随机抽题）")
    print("3. 只刷错题（从错题本中抽题）")
    print("4. 查看做题统计")
    print("0. 退出")
    print("----------------------------------------")


def handle_parse_docx():
    clear_screen()
    print("=== 解析 Word 题库存为 JSON ===")
    print("提示：")
    print("1）请准备一个 .docx 题库文件，里面包含题目和“正确答案：”字段；")
    print("2）建议先把题库文件放在项目根目录，并命名为 questions.docx；")
    print("3）如果你的文件路径不一样，也可以手动输入完整路径。\n")

    default_path = config.DEFAULT_DOCX_PATH
    print(f"默认题库路径：{default_path}")
    custom = input("如果使用默认路径，直接回车；否则请输入你的 .docx 文件完整路径：\n").strip()
    docx_path = custom or default_path

    print(f"准备解析的文件：{docx_path}")

    try:
        count = parse_docx_and_save_to_json(docx_path)
        print(f"解析完成！共成功解析出 {count} 道题目。")
        # 修复点：这里使用 DEFAULT_JSON_PATH，而不是已经不存在的 QUESTION_JSON_PATH
        print(f"题库已保存为 JSON 文件：{config.DEFAULT_JSON_PATH}")
    except Exception as e:
        print("【严重错误】解析过程中出现异常。")
        print(f"错误简要信息： {e}\n")
        print("常见原因排查：")
        print("1）题库文件其实是 .doc 或其他格式，只是后缀改成了 .docx；")
        print("   解决办法：用 Word 打开原文件，选择“另存为”，保存类型选“Word 文档 (*.docx)”；")
        print("2）文件已损坏或权限问题，可以尝试另存为到别的位置再试。\n")
        print("详细错误信息（调试用）：")
        import traceback

        traceback.print_exc()
        print("\n请把上面这段错误信息完整复制给我，我来帮你排查问题。")

    pause()


def handle_start_quiz():
    clear_screen()
    print("=== 开始刷题（命令行版） ===")
    print("注意：命令行版只是简易版，完整版请使用 qt_app.py 窗口版。\n")

    print("请选择题型：")
    print("1. 全部题型")
    print("2. 单选题")
    print("3. 填空题")
    print("4. 判断题")
    print("5. 简答题")
    choice = input("请输入编号并回车：").strip()

    type_map = {
        "1": "all",
        "2": config.QTYPE_SINGLE,
        "3": config.QTYPE_BLANK,
        "4": config.QTYPE_TF,
        "5": config.QTYPE_SHORT,
    }
    q_type = type_map.get(choice, "all")

    try:
        count_str = input("请输入本轮刷题题目数量（建议 10 左右）：").strip()
        count = int(count_str or "10")
    except ValueError:
        count = 10

    print("\n现在开始刷题...\n")
    run_normal_quiz(q_type=q_type, limit=count)
    pause()


def handle_wrong_quiz():
    clear_screen()
    print("=== 只刷错题（命令行版） ===\n")
    try:
        count_str = input("请输入本轮刷题题目数量（建议 10 左右）：").strip()
        count = int(count_str or "10")
    except ValueError:
        count = 10

    print("\n现在开始刷错题...\n")
    run_wrong_quiz(limit=count)
    pause()


def handle_view_stats():
    clear_screen()
    print("=== 做题统计（来自 stats.json） ===\n")
    stats = load_stats()
    total = stats.get("total_answered", 0)
    correct = stats.get("total_correct", 0)
    if total > 0:
        rate = correct * 100.0 / total
    else:
        rate = 0.0

    print(f"总答题数：{total}")
    print(f"总正确数：{correct}")
    print(f"总体正确率：{rate:.2f}%\n")

    per_total = stats.get("per_type_total", {})
    per_correct = stats.get("per_type_correct", {})

    def fmt_type(code: str) -> str:
        if code == config.QTYPE_SINGLE:
            return "单选题"
        if code == config.QTYPE_BLANK:
            return "填空题"
        if code == config.QTYPE_TF:
            return "判断题"
        if code == config.QTYPE_SHORT:
            return "简答题"
        return code

    print("按题型分布：")
    all_types = set(per_total.keys()) | set(per_correct.keys())
    for t in all_types:
        t_total = per_total.get(t, 0)
        t_correct = per_correct.get(t, 0)
        t_rate = (t_correct * 100.0 / t_total) if t_total > 0 else 0.0
        print(f"- {fmt_type(t)}： 做题 {t_total}，正确 {t_correct}，正确率 {t_rate:.2f}%")

    pause()


def main():
    while True:
        print_menu()
        choice = input("请输入功能编号并回车：").strip()
        if choice == "1":
            handle_parse_docx()
        elif choice == "2":
            handle_start_quiz()
        elif choice == "3":
            handle_wrong_quiz()
        elif choice == "4":
            handle_view_stats()
        elif choice == "0":
            print("已退出。建议使用 qt_app.py 体验窗口版刷题系统。")
            sys.exit(0)
        else:
            print("无效的选择，请重新输入。")
            pause()


if __name__ == "__main__":
    main()
