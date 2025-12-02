# -*- coding: utf-8 -*-
"""
gui_app.py
图形界面版刷题系统入口（学习通风格 + 单选框交互 + 无弹窗判题版）。

- 单选题 / 判断题：用大号单选按钮，鼠标点击选项作答；
- 填空题 / 简答题：使用文本框输入答案；
- 提交答案后不弹 messagebox，只在右侧“本题反馈”区域显示结果和参考答案；
- 错题本与统计逻辑复用原有模块。
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import random
from typing import List, Dict, Optional

import config
from question_parser import parse_docx_and_save_to_json
from storage import (
    load_questions_from_file,
    load_wrong_questions,
    save_wrong_questions,
    load_stats,
)
from models import Question
from quiz_engine import _check_answer, _update_stats


def qtype_label(q_type: str) -> str:
    """把题型代码转成中文文字。"""
    if q_type == config.QTYPE_SINGLE:
        return "单选题"
    if q_type == config.QTYPE_BLANK:
        return "填空题"
    if q_type == config.QTYPE_TF:
        return "判断题"
    if q_type == config.QTYPE_SHORT:
        return "简答题"
    return f"未知({q_type})"


def format_rate(correct: int, total: int) -> str:
    """格式化正确率。"""
    if total <= 0:
        return "0.00%"
    return f"{correct * 100.0 / total:.2f}%"


class QuizApp:
    """
    图形界面刷题应用。

    布局结构：
    - 顶部：深色标题栏；
    - 左侧：控制面板（题型、题量、功能按钮）；
    - 右侧：题干 + 选项（单选框）+ 本题反馈 + 底部操作区。
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("本地刷题系统 - 窗口版")
        self.root.geometry("1000x700")
        self.root.minsize(900, 640)
        self.root.configure(bg="#ecf0f1")

        # 当前刷题状态
        self.current_mode: Optional[str] = None  # "normal" / "wrong" / None
        self.current_questions: List[Question] = []
        self.current_index: int = -1
        self.current_question: Optional[Question] = None

        # 本轮统计
        self.per_type_total: Dict[str, int] = {}
        self.per_type_correct: Dict[str, int] = {}
        self.wrong_in_session: Dict[int, Question] = {}

        # 控件变量
        self.selected_type_var = tk.StringVar(value="全部题型")
        self.count_var = tk.IntVar(value=10)
        self.answer_var = tk.StringVar(value="")   # 文本题答案
        self.option_var = tk.StringVar(value="")   # 单选框答案
        self.is_waiting_answer: bool = False       # True：等待提交答案

        # 控件引用
        self.question_text: Optional[tk.Text] = None
        self.options_frame: Optional[ttk.Frame] = None
        self.feedback_text: Optional[tk.Text] = None
        self.answer_label: Optional[ttk.Label] = None
        self.answer_entry: Optional[ttk.Entry] = None
        self.submit_button: Optional[ttk.Button] = None
        self.result_label: Optional[ttk.Label] = None
        self.status_label: Optional[ttk.Label] = None
        self.progress_label: Optional[ttk.Label] = None

        self._build_ui()

    # ==================== UI 构建 ====================

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        base_font = ("Microsoft YaHei", 11)
        title_font = ("Microsoft YaHei", 16, "bold")
        small_font = ("Microsoft YaHei", 10)

        style.configure("TLabel", font=base_font)
        style.configure("TButton", font=base_font, padding=6)
        style.configure("Status.TLabel", font=small_font, foreground="#555555")

        # 选项单选框样式：大号字体、适合鼠标点
        style.configure(
            "Option.TRadiobutton",
            font=("Microsoft YaHei", 13),
            padding=8,
        )

        # 顶部标题栏
        header_frame = tk.Frame(self.root, bg="#2c3e50", height=56)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        header_label = tk.Label(
            header_frame,
            text="本地刷题系统 - 窗口版",
            bg="#2c3e50",
            fg="white",
            font=("Microsoft YaHei", 20, "bold"),
            anchor="w",
            padx=24,
        )
        header_label.pack(side=tk.LEFT, fill=tk.Y)

        subtitle_label = tk.Label(
            header_frame,
            text="题库解析 · 随机刷题 · 错题本 · 做题统计",
            bg="#2c3e50",
            fg="#ecf0f1",
            font=("Microsoft YaHei", 11),
            anchor="e",
            padx=24,
        )
        subtitle_label.pack(side=tk.RIGHT, fill=tk.Y)

        # 主体：左侧控制 + 右侧内容
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        main_frame.columnconfigure(0, weight=0)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        # ===== 左侧控制面板 =====
        left_frame = ttk.Frame(main_frame)
        left_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 10))

        # 题目设置
        settings_group = ttk.LabelFrame(left_frame, text="题目设置", padding=10)
        settings_group.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(settings_group, text="题型：").grid(row=0, column=0, sticky="w", pady=2)
        type_combo = ttk.Combobox(
            settings_group,
            textvariable=self.selected_type_var,
            state="readonly",
            values=["全部题型", "单选题", "填空题", "判断题", "简答题"],
            width=12,
        )
        type_combo.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(settings_group, text="题量：").grid(row=1, column=0, sticky="w", pady=6)
        count_spin = ttk.Spinbox(
            settings_group,
            from_=1,
            to=999,
            textvariable=self.count_var,
            width=8,
        )
        count_spin.grid(row=1, column=1, sticky="w", pady=6)

        btn_start = ttk.Button(settings_group, text="开始刷题", command=self.on_start_normal_quiz)
        btn_start.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 2))

        btn_wrong = ttk.Button(settings_group, text="只刷错题", command=self.on_start_wrong_quiz)
        btn_wrong.grid(row=3, column=0, columnspan=2, sticky="ew", pady=2)

        # 系统功能
        system_group = ttk.LabelFrame(left_frame, text="系统功能", padding=10)
        system_group.pack(side=tk.TOP, fill=tk.X, pady=(10, 0))

        btn_parse = ttk.Button(system_group, text="解析 Word 题库", command=self.on_parse_docx)
        btn_parse.pack(fill=tk.X, pady=2)

        btn_stats = ttk.Button(system_group, text="查看做题统计", command=self.on_show_stats)
        btn_stats.pack(fill=tk.X, pady=2)

        btn_exit = ttk.Button(system_group, text="退出程序", command=self.root.quit)
        btn_exit.pack(fill=tk.X, pady=(8, 0))

        # ===== 右侧内容区 =====
        right_frame = ttk.Frame(main_frame)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.rowconfigure(1, weight=2)  # 题干区
        right_frame.rowconfigure(2, weight=2)  # 选项区
        right_frame.rowconfigure(3, weight=1)  # 反馈区

        # 顶部进度条
        top_right = ttk.Frame(right_frame)
        top_right.grid(row=0, column=0, sticky="ew")

        self.progress_label = ttk.Label(
            top_right,
            text="当前未在刷题。",
            style="Status.TLabel",
        )
        self.progress_label.pack(side=tk.LEFT, anchor="w")

        # 题干区域
        stem_frame = ttk.LabelFrame(right_frame, text="题目", padding=8)
        stem_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 4))
        stem_frame.rowconfigure(0, weight=1)
        stem_frame.columnconfigure(0, weight=1)

        self.question_text = tk.Text(
            stem_frame,
            height=6,
            wrap=tk.WORD,
            state="disabled",
            font=("Microsoft YaHei", 13),
            bg="#ffffff",
            relief="flat",
        )
        self.question_text.grid(row=0, column=0, sticky="nsew")

        q_scrollbar = ttk.Scrollbar(
            stem_frame,
            orient="vertical",
            command=self.question_text.yview,
        )
        q_scrollbar.grid(row=0, column=1, sticky="ns")
        self.question_text.configure(yscrollcommand=q_scrollbar.set)

        # 选项区域
        options_outer = ttk.LabelFrame(right_frame, text="选项", padding=8)
        options_outer.grid(row=2, column=0, sticky="nsew", pady=(0, 4))
        options_outer.columnconfigure(0, weight=1)

        self.options_frame = ttk.Frame(options_outer)
        self.options_frame.grid(row=0, column=0, sticky="nsew")
        self.options_frame.columnconfigure(0, weight=1)

        # 本题反馈区域
        feedback_frame = ttk.LabelFrame(right_frame, text="本题反馈", padding=8)
        feedback_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 4))
        feedback_frame.rowconfigure(0, weight=1)
        feedback_frame.columnconfigure(0, weight=1)

        self.feedback_text = tk.Text(
            feedback_frame,
            height=5,
            wrap=tk.WORD,
            state="disabled",
            font=("Microsoft YaHei", 11),
            bg="#f9fbff",
            relief="flat",
        )
        self.feedback_text.grid(row=0, column=0, sticky="nsew")

        fb_scroll = ttk.Scrollbar(
            feedback_frame,
            orient="vertical",
            command=self.feedback_text.yview,
        )
        fb_scroll.grid(row=0, column=1, sticky="ns")
        self.feedback_text.configure(yscrollcommand=fb_scroll.set)

        # 底部作答区域
        bottom_frame = ttk.Frame(right_frame, padding=(0, 4))
        bottom_frame.grid(row=4, column=0, sticky="ew")

        self.answer_label = ttk.Label(bottom_frame, text="你的答案：")
        self.answer_label.grid(row=0, column=0, sticky="w")

        self.answer_entry = ttk.Entry(
            bottom_frame,
            textvariable=self.answer_var,
            width=28,
            font=("Microsoft YaHei", 11),
        )
        self.answer_entry.grid(row=0, column=1, sticky="w", padx=(4, 10))

        self.submit_button = ttk.Button(
            bottom_frame,
            text="提交答案",
            command=self.on_submit_or_next,
        )
        self.submit_button.grid(row=0, column=2, sticky="w", padx=(0, 10))

        self.result_label = ttk.Label(
            bottom_frame,
            text="",
            foreground="blue",
        )
        self.result_label.grid(row=0, column=3, sticky="w")

        # 底部状态栏
        status_frame = ttk.Frame(self.root, padding=(10, 4))
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_label = ttk.Label(
            status_frame,
            text="提示：先解析 Word 题库，再开始刷题。",
            style="Status.TLabel",
        )
        self.status_label.pack(side=tk.LEFT, anchor="w")

    # ==================== 小工具 ====================

    def _clear_options(self):
        """清空当前题目的单选框选项。"""
        for child in self.options_frame.winfo_children():
            child.destroy()
        self.option_var.set("")

    def _show_answer_entry(self, show: bool):
        """
        控制“你的答案”输入框是否显示：
        - 单选题 / 判断题：只用单选框，这个输入框隐藏；
        - 填空题 / 简答题：显示输入框。
        """
        if show:
            self.answer_label.grid(row=0, column=0, sticky="w")
            self.answer_entry.grid(row=0, column=1, sticky="w", padx=(4, 10))
            self.answer_entry.config(state="normal")
        else:
            self.answer_label.grid_remove()
            self.answer_entry.grid_remove()
            self.answer_var.set("")

    def _set_question_text(self, text: str):
        """设置题干文本框。"""
        self.question_text.config(state="normal")
        self.question_text.delete("1.0", tk.END)
        if text:
            self.question_text.insert(tk.END, text)
        self.question_text.config(state="disabled")

    def _set_feedback_text(self, text: str):
        """设置“本题反馈”文本框。"""
        self.feedback_text.config(state="normal")
        self.feedback_text.delete("1.0", tk.END)
        if text:
            self.feedback_text.insert(tk.END, text)
        self.feedback_text.config(state="disabled")

    # ==================== 顶部按钮：解析 / 开始 / 错题 / 统计 ====================

    def on_parse_docx(self):
        """解析 Word 题库。（这里还保留提示框，属于系统级操作）"""
        if messagebox.askyesno(
            "解析题库",
            f"是否使用默认题库文件？\n\n{config.DEFAULT_DOCX_PATH}\n\n"
            f"选择“是”则直接解析该文件；选择“否”则手动选择 .docx 文件。",
        ):
            docx_path = config.DEFAULT_DOCX_PATH
        else:
            path = filedialog.askopenfilename(
                title="请选择题库 Word 文件 (.docx)",
                filetypes=[("Word 文档", "*.docx"), ("所有文件", "*.*")],
            )
            if not path:
                return
            docx_path = path

        try:
            count = parse_docx_and_save_to_json(docx_path)
            messagebox.showinfo(
                "解析成功",
                f"已成功解析 {count} 道题目。\n"
                f"题库 JSON 已保存到：\n{config.QUESTION_JSON_PATH}",
            )
            self.status_label.config(text="解析成功，可以开始刷题了。")
        except FileNotFoundError:
            messagebox.showerror("错误", f"找不到指定的文件：\n{docx_path}")
            self.status_label.config(text="解析失败：找不到文件。")
        except Exception as e:
            messagebox.showerror(
                "解析失败",
                f"解析过程中发生错误：\n{e}\n\n"
                f"建议先用命令行查看详细报错。",
            )
            self.status_label.config(text="解析失败，请查看错误信息。")

    def on_start_normal_quiz(self):
        """开始普通刷题。"""
        all_questions = load_questions_from_file()
        if not all_questions:
            messagebox.showinfo(
                "提示",
                "当前题库为空。\n请先解析 Word 题库（左侧“解析 Word 题库”按钮）。",
            )
            self.status_label.config(text="题库为空，请先解析 Word 文件。")
            return

        qtype_choice = self.selected_type_var.get()
        if qtype_choice == "全部题型":
            pool = list(all_questions)
        else:
            type_map = {
                "单选题": config.QTYPE_SINGLE,
                "填空题": config.QTYPE_BLANK,
                "判断题": config.QTYPE_TF,
                "简答题": config.QTYPE_SHORT,
            }
            t = type_map.get(qtype_choice)
            pool = [q for q in all_questions if q.q_type == t]

        if not pool:
            messagebox.showinfo("提示", f"当前题库中没有“{qtype_choice}”。")
            self.status_label.config(text=f"题库中没有 {qtype_choice}。")
            return

        try:
            n = int(self.count_var.get())
        except ValueError:
            messagebox.showerror("错误", "题目数量请输入整数。")
            self.status_label.config(text="题目数量必须是整数。")
            return
        if n <= 0:
            messagebox.showerror("错误", "题目数量必须大于 0。")
            self.status_label.config(text="题目数量必须大于 0。")
            return
        if n > len(pool):
            n = len(pool)

        questions = random.sample(pool, k=n)
        self.begin_quiz(questions, mode="normal")

    def on_start_wrong_quiz(self):
        """开始“只刷错题”模式。"""
        wrong_all = load_wrong_questions()
        if not wrong_all:
            messagebox.showinfo(
                "提示",
                "当前错题本为空。\n先在“开始刷题”里做几道题，做错的会自动进入错题本。",
            )
            self.status_label.config(text="错题本为空，请先做题。")
            return

        try:
            n = int(self.count_var.get())
        except ValueError:
            messagebox.showerror("错误", "题目数量请输入整数。")
            self.status_label.config(text="题目数量必须是整数。")
            return
        if n <= 0:
            messagebox.showerror("错误", "题目数量必须大于 0。")
            self.status_label.config(text="题目数量必须大于 0。")
            return
        if n > len(wrong_all):
            n = len(wrong_all)

        questions = random.sample(wrong_all, k=n)
        self.begin_quiz(questions, mode="wrong")

    def on_show_stats(self):
        """查看做题统计。（依然弹一次框，属于整体信息）"""
        stats = load_stats()
        total_answered = stats.get("total_answered", 0)
        total_correct = stats.get("total_correct", 0)
        per_type_answered: Dict[str, int] = stats.get("per_type_answered", {}) or {}
        per_type_correct: Dict[str, int] = stats.get("per_type_correct", {}) or {}

        lines = []
        lines.append(f"总答题数：{total_answered}")
        lines.append(f"总正确数：{total_correct}")
        lines.append(f"总体正确率：{format_rate(total_correct, total_answered)}")
        lines.append("")

        if not per_type_answered:
            lines.append("各题型统计：目前还没有数据。")
            messagebox.showinfo("做题统计", "\n".join(lines))
            self.status_label.config(text="尚无统计数据，请先刷题。")
            return

        lines.append("各题型统计：")
        for q_type, total in per_type_answered.items():
            correct = per_type_correct.get(q_type, 0)
            lines.append(
                f" - {qtype_label(q_type)}："
                f"答题数 {total}，正确数 {correct}，"
                f"正确率 {format_rate(correct, total)}"
            )

        messagebox.showinfo("做题统计", "\n".join(lines))
        self.status_label.config(text="已显示做题统计。")

    # ==================== 刷题主流程 ====================

    def begin_quiz(self, questions: List[Question], mode: str):
        """开始一轮刷题。"""
        if not questions:
            return

        self.current_mode = mode
        self.current_questions = list(questions)
        random.shuffle(self.current_questions)
        self.current_index = 0
        self.current_question = self.current_questions[self.current_index]

        self.per_type_total = {}
        self.per_type_correct = {}
        self.wrong_in_session = {}

        self.is_waiting_answer = True
        self.submit_button.config(text="提交答案")
        self.status_label.config(text="已开始刷题，选中选项或输入答案后点击“提交答案”。")
        self._set_feedback_text("这里会显示本题对错、参考答案以及说明。")

        self._show_current_question()

    def _show_current_question(self):
        """根据当前题目刷新界面。"""
        if self.current_question is None:
            self.progress_label.config(text="当前未在刷题。")
            self._set_question_text("")
            self._clear_options()
            self._show_answer_entry(False)
            self._set_feedback_text("")
            return

        q = self.current_question
        total = len(self.current_questions)
        idx = self.current_index + 1

        self.progress_label.config(
            text=f"第 {idx} / {total} 题  [{qtype_label(q.q_type)}]  (题号: {q.id})"
        )

        # 题干：只放题目文字
        stem = q.question.strip()
        self._set_question_text(stem)

        # 清空选项区
        self._clear_options()

        # 根据题型决定交互方式
        if q.q_type == config.QTYPE_SINGLE:
            # 单选题：一行一个大号单选项
            self._show_answer_entry(False)
            self.option_var.set("")
            if q.options:
                row = 0
                for label in sorted(q.options.keys()):
                    opt_text = q.options[label]
                    text = f"{label}.  {opt_text}"
                    rb = ttk.Radiobutton(
                        self.options_frame,
                        text=text,
                        value=label,
                        variable=self.option_var,
                        style="Option.TRadiobutton",
                    )
                    rb.grid(row=row, column=0, sticky="w", pady=4, padx=4)
                    row += 1
            else:
                # 没选项数据就退回文本输入
                self._show_answer_entry(True)

        elif q.q_type == config.QTYPE_TF:
            # 判断题：两个单选项
            self._show_answer_entry(False)
            self.option_var.set("")

            items = []
            if q.options and len(q.options) >= 2:
                for label in sorted(q.options.keys()):
                    items.append(q.options[label])
            else:
                items = ["正确", "错误"]

            for i, txt in enumerate(items):
                rb = ttk.Radiobutton(
                    self.options_frame,
                    text=txt,
                    value=txt,
                    variable=self.option_var,
                    style="Option.TRadiobutton",
                )
                rb.grid(row=i, column=0, sticky="w", pady=4, padx=4)

        else:
            # 填空题 / 简答题：文本输入
            self._show_answer_entry(True)
            self.option_var.set("")
            self.answer_var.set("")

        self.result_label.config(text="", foreground="blue")
        if self.answer_entry.winfo_ismapped():
            self.answer_entry.focus_set()

    def on_submit_or_next(self):
        """提交答案 / 下一题 按钮。"""
        if self.current_question is None or not self.current_questions:
            messagebox.showinfo("提示", "请先点击“开始刷题”或“只刷错题”。")
            return

        if self.is_waiting_answer:
            self._handle_submit_answer()
        else:
            self._goto_next_question()

    def _handle_submit_answer(self):
        """采集答案 -> 判题 -> 更新统计和错题本 -> 在右侧反馈区域显示结果。"""
        q = self.current_question
        if q is None:
            return

        # 单选 / 判断：取单选框的值；其余取文本框
        if q.q_type in (config.QTYPE_SINGLE, config.QTYPE_TF):
            user_raw = self.option_var.get().strip()
            if not user_raw:
                self.status_label.config(text="请先选择一个选项，再点击“提交答案”。")
                return
        else:
            user_raw = self.answer_var.get().strip()
            # 填空 / 简答题允许空答案，这里不弹窗，只记录空
            if not user_raw:
                self.status_label.config(text="当前答案为空，已按空答案提交。")

        is_correct, user_norm, correct_norm = _check_answer(q, user_raw)

        answer_text = q.answer if q.answer.strip() else "(题库中未设置答案)"

        # 在反馈区域展示整合信息
        lines = []

        # 顶部一行：对/错提示
        if is_correct or q.q_type == config.QTYPE_SHORT:
            # 简答题不自动判分，这里根据自评再改 is_correct
            pass

        if q.q_type == config.QTYPE_SHORT:
            # 简答题：不自动判分，显示参考答案，用户自己判断
            lines.append("📌 本题为简答题，请对照参考答案自行判断是否作对。")
            lines.append("")
            if user_raw:
                lines.append(f"你的答案：{user_raw}")
                lines.append("")
            lines.append("参考答案：")
            lines.append(answer_text)
            # 简答题结果：用对话框询问会打断节奏，这里改为按钮下方提示 + 自己心里有数
            self.result_label.config(
                text="简答题已显示参考答案，请自行判断对错。",
                foreground="#8e44ad",
            )
            is_correct = False  # 简答题默认不计入“答对”，你如果想算对可以后面改逻辑
        else:
            # 客观题：直接给出对错 + 参考答案
            if is_correct:
                lines.append("✅ 回答正确！")
                self.result_label.config(text="✅ 回答正确！", foreground="green")
            else:
                lines.append("❌ 回答错误！")
                self.result_label.config(text="❌ 回答错误！", foreground="red")

            lines.append("")
            if user_raw:
                lines.append(f"你的原始答案：{user_raw}")
            else:
                lines.append("你的原始答案： (空)")
            lines.append("")

            lines.append("参考答案（题库原文）：")
            lines.append(answer_text)

            if q.q_type in (config.QTYPE_SINGLE, config.QTYPE_TF):
                lines.append("")
                lines.append("规范化对比：")
                lines.append(f" - 你的规范化答案：{user_norm or '(空)'}")
                lines.append(f" - 标准规范答案：{correct_norm or '(未知)'}")

        self._set_feedback_text("\n".join(lines))

        # 本轮统计
        t = q.q_type
        self.per_type_total[t] = self.per_type_total.get(t, 0) + 1
        if is_correct:
            self.per_type_correct[t] = self.per_type_correct.get(t, 0) + 1
        else:
            self.wrong_in_session[q.id] = q

        self.is_waiting_answer = False
        self.submit_button.config(text="下一题")
        self.status_label.config(text="查看右侧反馈，然后点击“下一题”继续。")

    def _goto_next_question(self):
        """跳到下一题，或结束本轮。"""
        self.current_index += 1
        if self.current_index < len(self.current_questions):
            self.current_question = self.current_questions[self.current_index]
            self.is_waiting_answer = True
            self.submit_button.config(text="提交答案")
            self._show_current_question()
            self.status_label.config(text="填写答案或选择选项后点击“提交答案”。")
            return

        self._finish_session()

    def _finish_session(self):
        """本轮刷题结束：更新统计 + 错题本 + 在反馈区展示结果。"""
        total = sum(self.per_type_total.values())
        correct = sum(self.per_type_correct.values())

        _update_stats(self.per_type_total, self.per_type_correct)

        if self.current_mode == "normal":
            if self.wrong_in_session:
                existing = load_wrong_questions()
                by_id = {q.id: q for q in existing}
                for q in self.wrong_in_session.values():
                    by_id[q.id] = q
                new_list = list(by_id.values())
                save_wrong_questions(new_list)
                wrong_book_msg = f"本轮新增错题 {len(self.wrong_in_session)} 道，错题本总数：{len(new_list)}。"
            else:
                wrong_book_msg = "本轮没有新增错题，错题本保持不变。"
        elif self.current_mode == "wrong":
            wrong_ids_this_round = set(self.wrong_in_session.keys())
            original_ids = set(q.id for q in self.current_questions)
            correct_ids_this_round = original_ids - wrong_ids_this_round

            wrong_all = load_wrong_questions()
            by_id = {q.id: q for q in wrong_all}

            for qid in correct_ids_this_round:
                by_id.pop(qid, None)
            for qid, q in self.wrong_in_session.items():
                by_id[qid] = q

            new_list = list(by_id.values())
            save_wrong_questions(new_list)
            wrong_book_msg = f"本轮练习后，错题本剩余 {len(new_list)} 道题。"
        else:
            wrong_book_msg = ""

        # 在反馈区展示整轮结果
        lines = [
            "📊 本轮刷题结束！",
            "",
            f"总题数：{total}",
            f"答对数：{correct}",
            f"答错数：{total - correct}",
            f"正确率：{format_rate(correct, total)}",
        ]
        if wrong_book_msg:
            lines.append("")
            lines.append(wrong_book_msg)

        self._set_feedback_text("\n".join(lines))

        # 状态复位，但保留反馈结果
        self.current_mode = None
        self.current_questions = []
        self.current_index = -1
        self.current_question = None
        self.is_waiting_answer = False
        self.submit_button.config(text="提交答案")
        self.progress_label.config(text="当前未在刷题。")
        self._set_question_text("")
        self._clear_options()
        self.answer_var.set("")
        self.option_var.set("")
        self.result_label.config(text="", foreground="blue")
        self.status_label.config(text="本轮已结束，可以重新配置题型和数量再来一轮。")


def main():
    root = tk.Tk()
    app = QuizApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
