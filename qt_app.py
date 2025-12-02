# -*- coding: utf-8 -*-
"""
qt_app.py

PySide6 窗口版刷题系统（改进版 3）：
- 题库导入 / 删除；
- 新窗口“题库总览”：展示所有题目，并支持实时收藏题目；
- 收藏的是“题目”，不是“题库”，收藏信息保存在 favorites.json；
- 答题卡改为下拉框（可用鼠标滚轮控制），解决题目过多时重叠问题；
- 刷新统计按钮会在右侧解析区域展示最新统计信息；
- 新增“查看收藏夹”按钮，查看所有已收藏题目。
"""

from __future__ import annotations

import os
import sys
import random
from typing import List, Dict, Optional, Set

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QPushButton,
    QGroupBox,
    QRadioButton,
    QTextEdit,
    QPlainTextEdit,
    QFrame,
    QSizePolicy,
    QFileDialog,
    QGraphicsOpacityEffect,
    QDialog,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)
from PySide6.QtCore import Qt, QPropertyAnimation
from PySide6.QtGui import QFont

import config
from storage import (
    load_questions_from_file,
    load_wrong_questions,
    save_wrong_questions,
    load_stats,
    delete_question_bank,
)
from models import Question
from quiz_engine import _check_answer, _update_stats
from question_parser import parse_docx_and_save_to_json


FAV_JSON_PATH = os.path.join(config.BASE_DIR, "favorites.json")


def qtype_label(q_type: str) -> str:
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
    if total <= 0:
        return "0.00%"
    return f"{correct * 100.0 / total:.2f}%"


def load_favorite_ids() -> Set[int]:
    if not os.path.exists(FAV_JSON_PATH):
        return set()
    try:
        import json
        with open(FAV_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(int(x) for x in data)
    except Exception:
        return set()
    return set()


def save_favorite_ids(ids: Set[int]):
    import json
    with open(FAV_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(list(ids)), f, ensure_ascii=False, indent=2)


class QuestionOverviewDialog(QDialog):
    """题库总览窗口：展示所有题目，并支持收藏 / 取消收藏。"""

    def __init__(self, parent: QMainWindow, questions: List[Question], favorite_ids: Set[int]):
        super().__init__(parent)
        self.questions = questions
        self.favorite_ids = favorite_ids
        self.setWindowTitle("题库总览 · 收藏题目")
        self.resize(960, 600)

        layout = QVBoxLayout(self)

        info_label = QLabel("提示：点击每一行右侧的“收藏 / 取消收藏”按钮，可以实时收藏该题目。")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.table = QTableWidget(len(self.questions), 4, self)
        self.table.setHorizontalHeaderLabels(["题号", "题型", "题干预览", "收藏"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)

        layout.addWidget(self.table)

        self._populate_table()

        # 提升可读性的局部样式
        self.setStyleSheet("""
        QDialog {
            background-color: #f4f6fb;
        }
        QTableWidget {
            background-color: #ffffff;
            color: #111827;
            gridline-color: #d1d5db;
            font-size: 13px;
        }
        QHeaderView::section {
            background-color: #e5edff;
            color: #111827;
            font-weight: 600;
        }
        QPushButton {
            padding: 4px 10px;
            border-radius: 4px;
            border: 1px solid #cbd5e1;
            background-color: #ffffff;
        }
        QPushButton:hover {
            background-color: #eff6ff;
        }
        """)

    def _populate_table(self):
        from functools import partial

        for row, q in enumerate(self.questions):
            item_id = QTableWidgetItem(str(q.id))
            item_type = QTableWidgetItem(qtype_label(q.q_type))
            text = q.question.replace("\n", " ")
            if len(text) > 40:
                text = text[:40] + "..."
            item_q = QTableWidgetItem(text)

            self.table.setItem(row, 0, item_id)
            self.table.setItem(row, 1, item_type)
            self.table.setItem(row, 2, item_q)

            btn = QPushButton(self)
            self._update_fav_button_text(btn, q.id)
            btn.clicked.connect(partial(self._toggle_favorite, q.id, btn))
            self.table.setCellWidget(row, 3, btn)

    def _update_fav_button_text(self, btn: QPushButton, qid: int):
        if qid in self.favorite_ids:
            btn.setText("取消收藏")
        else:
            btn.setText("收藏")

    def _toggle_favorite(self, qid: int, btn: QPushButton):
        if qid in self.favorite_ids:
            self.favorite_ids.remove(qid)
        else:
            self.favorite_ids.add(qid)
        save_favorite_ids(self.favorite_ids)
        self._update_fav_button_text(btn, qid)


class QuizWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("本地刷题系统 - Qt 窗口版")
        self.resize(1180, 720)
        self.setMinimumSize(1000, 650)

        # 状态
        self.mode: Optional[str] = None
        self.current_questions: List[Question] = []
        self.current_index: int = -1
        self.current_question: Optional[Question] = None
        self.waiting_answer: bool = False

        self.per_type_total: Dict[str, int] = {}
        self.per_type_correct: Dict[str, int] = {}
        self.wrong_in_session: Dict[int, Question] = {}

        self.index_status: List[str] = []
        self.user_answers: List[str] = []

        self.current_bank_docx: Optional[str] = None

        self.favorite_ids: Set[int] = load_favorite_ids()

        # 控件占位
        self.qtype_combo: QComboBox
        self.count_spin: QSpinBox
        self.btn_start_normal: QPushButton
        self.btn_start_wrong: QPushButton

        self.answer_summary_label: QLabel

        self.label_stat_total: QLabel
        self.label_stat_correct: QLabel
        self.label_stat_rate: QLabel
        self.btn_refresh_stats: QPushButton

        self.progress_label: QLabel

        self.btn_star_favorite: QPushButton

        self.question_edit: QTextEdit
        self.options_box: QGroupBox
        self.options_layout: QVBoxLayout
        self.short_answer_edit: QPlainTextEdit

        self.feedback_edit: QPlainTextEdit
        self.status_label: QLabel

        self.btn_prev: QPushButton
        self.btn_next: QPushButton
        self.btn_submit: QPushButton

        self.option_buttons: List[QRadioButton] = []
        self.current_option_value: str = ""

        # 答题卡控件：下拉框 + 跳转按钮
        self.card_combo: QComboBox
        self.btn_card_jump: QPushButton

        self.feedback_effect: Optional[QGraphicsOpacityEffect] = None
        self.feedback_anim: Optional[QPropertyAnimation] = None

        self._build_ui()
        self._apply_style()
        self._init_feedback_animation()
        self.refresh_global_stats()

    # ---------- UI ----------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 顶部标题
        header = QFrame()
        header.setObjectName("header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 10, 20, 10)

        title_label = QLabel("本地刷题系统 · Qt 窗口版")
        title_label.setObjectName("headerTitle")
        subtitle_label = QLabel("题库解析 · 随机刷题 · 错题本 · 做题统计 · 收藏题目")
        subtitle_label.setObjectName("headerSubtitle")

        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        root_layout.addWidget(header)

        # 中间主体区域
        body_frame = QFrame()
        body_layout = QHBoxLayout(body_frame)
        body_layout.setContentsMargins(12, 8, 12, 8)
        body_layout.setSpacing(12)

        # ===== 左侧：题库管理 + 答题卡 + 配置 + 统计 =====
        left_panel = QVBoxLayout()
        left_panel.setSpacing(10)

        # 题库管理
        bank_group = QGroupBox("题库管理")
        bank_layout = QVBoxLayout(bank_group)
        self.btn_import_bank = QPushButton("导入题库（Word）")
        self.btn_delete_bank = QPushButton("删除当前题库")
        self.btn_overview_bank = QPushButton("题库总览 / 收藏题目")
        self.btn_favorite_current = QPushButton("收藏当前题目")
        self.btn_view_favorites = QPushButton("查看收藏夹")
        bank_layout.addWidget(self.btn_import_bank)
        bank_layout.addWidget(self.btn_delete_bank)
        bank_layout.addWidget(self.btn_overview_bank)
        bank_layout.addWidget(self.btn_favorite_current)
        bank_layout.addWidget(self.btn_view_favorites)
        left_panel.addWidget(bank_group)

        # 答题卡
        nav_group = QGroupBox("答题卡 / 题目导航")
        nav_layout = QVBoxLayout(nav_group)
        nav_layout.setSpacing(6)

        self.answer_summary_label = QLabel("做对 0 · 做错 0")
        self.answer_summary_label.setObjectName("answerSummary")
        nav_layout.addWidget(self.answer_summary_label)

        self.card_combo = QComboBox()
        self.card_combo.setPlaceholderText("当前没有题目")
        nav_layout.addWidget(self.card_combo)

        self.btn_card_jump = QPushButton("跳转到所选题目")
        nav_layout.addWidget(self.btn_card_jump)

        left_panel.addWidget(nav_group)

        # 刷题配置
        settings_group = QGroupBox("刷题配置")
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setSpacing(8)

        row1 = QHBoxLayout()
        lbl_type = QLabel("题型：")
        self.qtype_combo = QComboBox()
        self.qtype_combo.addItem("全部题型", "all")
        self.qtype_combo.addItem("单选题", config.QTYPE_SINGLE)
        self.qtype_combo.addItem("填空题", config.QTYPE_BLANK)
        self.qtype_combo.addItem("判断题", config.QTYPE_TF)
        self.qtype_combo.addItem("简答题", config.QTYPE_SHORT)
        row1.addWidget(lbl_type)
        row1.addWidget(self.qtype_combo)
        settings_layout.addLayout(row1)

        row2 = QHBoxLayout()
        lbl_count = QLabel("题量：")
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 999)
        self.count_spin.setValue(10)
        row2.addWidget(lbl_count)
        row2.addWidget(self.count_spin)
        settings_layout.addLayout(row2)

        self.btn_start_normal = QPushButton("开始刷题")
        settings_layout.addWidget(self.btn_start_normal)
        self.btn_start_wrong = QPushButton("只刷错题")
        settings_layout.addWidget(self.btn_start_wrong)

        left_panel.addWidget(settings_group)

        # 总体统计
        stats_group = QGroupBox("总体统计")
        stats_layout = QVBoxLayout(stats_group)
        self.label_stat_total = QLabel("总答题数：0")
        self.label_stat_correct = QLabel("总正确数：0")
        self.label_stat_rate = QLabel("总体正确率：0.00%")
        for w in (self.label_stat_total, self.label_stat_correct, self.label_stat_rate):
            stats_layout.addWidget(w)
        self.btn_refresh_stats = QPushButton("刷新统计")
        stats_layout.addWidget(self.btn_refresh_stats)
        left_panel.addWidget(stats_group)

        spacer = QFrame()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_panel.addWidget(spacer)

        body_layout.addLayout(left_panel, 0)

        # ===== 中间：题目 + 作答区域 =====
        center_panel = QVBoxLayout()
        center_panel.setSpacing(8)

        progress_frame = QFrame()
        progress_frame.setObjectName("progressFrame")
        progress_layout = QHBoxLayout(progress_frame)
        progress_layout.setContentsMargins(10, 4, 10, 4)
        self.progress_label = QLabel("当前未在刷题。")
        progress_layout.addWidget(self.progress_label)
        progress_layout.addStretch()
        self.btn_star_favorite = QPushButton("☆ 收藏")
        self.btn_star_favorite.setCheckable(True)
        self.btn_star_favorite.setFlat(True)
        progress_layout.addWidget(self.btn_star_favorite)
        center_panel.addWidget(progress_frame)

        question_group = QGroupBox("题目")
        q_layout = QVBoxLayout(question_group)
        self.question_edit = QTextEdit()
        self.question_edit.setObjectName("questionEdit")
        self.question_edit.setReadOnly(True)
        self.question_edit.setAcceptRichText(False)
        self.question_edit.setMinimumHeight(160)
        q_layout.addWidget(self.question_edit)
        center_panel.addWidget(question_group, 3)

        options_group = QGroupBox("作答区域")
        options_layout_outer = QVBoxLayout(options_group)
        options_layout_outer.setSpacing(4)
        options_layout_outer.setContentsMargins(12, 8, 12, 8)

        self.options_box = QGroupBox("选择一个选项")
        self.options_layout = QVBoxLayout(self.options_box)
        self.options_layout.setSpacing(4)
        options_layout_outer.addWidget(self.options_box)

        self.short_answer_edit = QPlainTextEdit()
        self.short_answer_edit.setObjectName("shortAnswerEdit")
        self.short_answer_edit.setPlaceholderText("填空题 / 简答题：在这里输入你的答案。")
        self.short_answer_edit.setMinimumHeight(80)
        options_layout_outer.addWidget(self.short_answer_edit)

        button_frame = QFrame()
        btn_layout = QHBoxLayout(button_frame)
        btn_layout.setContentsMargins(0, 6, 0, 0)
        btn_layout.setSpacing(12)

        self.btn_prev = QPushButton("上一题")
        self.btn_prev.setObjectName("navButton")
        self.btn_next = QPushButton("下一题")
        self.btn_next.setObjectName("navButton")
        self.btn_submit = QPushButton("提交答案")
        self.btn_submit.setObjectName("primaryButton")

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_prev)
        btn_layout.addWidget(self.btn_submit)
        btn_layout.addWidget(self.btn_next)
        btn_layout.addStretch()

        options_layout_outer.addWidget(button_frame)

        center_panel.addWidget(options_group, 2)

        body_layout.addLayout(center_panel, 2)

        # ===== 右侧：反馈 =====
        right_panel = QVBoxLayout()
        right_panel.setSpacing(8)

        feedback_group = QGroupBox("本题反馈 / 答案解析 / 统计摘要")
        fb_layout = QVBoxLayout(feedback_group)
        self.feedback_edit = QPlainTextEdit()
        self.feedback_edit.setObjectName("feedbackEdit")
        self.feedback_edit.setReadOnly(True)
        self.feedback_edit.setMinimumHeight(220)
        self.feedback_edit.setMaximumHeight(280)
        fb_layout.addWidget(self.feedback_edit)
        right_panel.addWidget(feedback_group)

        r_spacer = QFrame()
        r_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_panel.addWidget(r_spacer)

        body_layout.addLayout(right_panel, 1)

        root_layout.addWidget(body_frame, 1)

        # 底部状态栏
        bottom_frame = QFrame()
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(12, 4, 12, 8)
        self.status_label = QLabel("先导入题库或使用默认题库，然后选择题型和题量开始刷题。")
        bottom_layout.addWidget(self.status_label, 1)
        root_layout.addWidget(bottom_frame)

        # 信号连接
        self.btn_import_bank.clicked.connect(self.on_import_bank)
        self.btn_delete_bank.clicked.connect(self.on_delete_bank)
        self.btn_overview_bank.clicked.connect(self.on_overview_bank)
        self.btn_favorite_current.clicked.connect(self.on_favorite_current_question)
        self.btn_view_favorites.clicked.connect(self.on_view_favorites)

        self.btn_start_normal.clicked.connect(self.on_start_normal)
        self.btn_start_wrong.clicked.connect(self.on_start_wrong)

        self.btn_submit.clicked.connect(self.on_submit_or_next)
        self.btn_prev.clicked.connect(self._goto_prev_question)
        self.btn_next.clicked.connect(self._goto_next_question)

        self.btn_refresh_stats.clicked.connect(self.on_refresh_stats)
        self.btn_star_favorite.clicked.connect(self.on_toggle_star_favorite)

        self.card_combo.currentIndexChanged.connect(self._on_card_combo_changed)
        self.btn_card_jump.clicked.connect(self._on_card_jump_clicked)

        # 初始化显示
        self.set_question_text("请选择题型和题量，然后点击左侧“开始刷题”。")
        self.set_feedback_text("这里会显示你本题是否答对，以及参考答案、统计等信息。")
        self.show_short_answer(False)
        self.clear_options()
        self._clear_answer_card()
        self.btn_submit.setEnabled(False)
        self._refresh_favorite_star()

    def _apply_style(self):
        self.setStyleSheet("""
        * {
            color: #1f2933;
            font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
        }
        QMainWindow {
            background-color: #f4f6fb;
        }
        #header {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                       stop:0 #34495e, stop:1 #2c3e50);
        }
        #header QLabel {
            color: #ecf0f1;
        }
        #headerTitle {
            font-size: 20px;
            font-weight: 700;
        }
        #headerSubtitle {
            font-size: 12px;
        }

        QGroupBox {
            background-color: #ffffff;
            border: 1px solid #d0d7e2;
            border-radius: 8px;
            margin-top: 10px;
            font-size: 13px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
        }

        QLabel {
            font-size: 13px;
        }
        #answerSummary {
            font-size: 13px;
            font-weight: 500;
        }

        QComboBox, QSpinBox {
            background-color: #ffffff;
            color: #111827;
            border: 1px solid #d0d7e2;
            border-radius: 4px;
            padding: 2px 4px;
            font-size: 13px;
        }
        QComboBox QAbstractItemView {
            background-color: #ffffff;
            color: #111827;
            font-size: 13px;
        }

        QPushButton {
            padding: 6px 14px;
            border-radius: 6px;
            border: 1px solid #d0d7e2;
            background-color: #ffffff;
            font-size: 13px;
        }
        QPushButton:hover {
            background-color: #eff4ff;
            border-color: #3b82f6;
        }
        QPushButton#navButton {
            font-size: 14px;
            padding: 6px 18px;
        }
        QPushButton#primaryButton {
            background-color: #3b82f6;
            color: white;
            border-color: #3b82f6;
            font-weight: 500;
            font-size: 14px;
            padding: 6px 18px;
        }
        QPushButton#primaryButton:hover {
            background-color: #2563eb;
        }

        QTextEdit, QPlainTextEdit {
            border-radius: 6px;
            border: 1px solid #d0d7e2;
            background-color: #ffffff;
            font-size: 14px;
        }
        #questionEdit {
            font-size: 16px;
            line-height: 1.6;
        }
        #shortAnswerEdit {
            font-size: 14px;
        }
        #feedbackEdit {
            background-color: #f9fbff;
            font-size: 14px;
        }

        #progressFrame {
            background-color: #e5edff;
            border-radius: 8px;
        }

        QRadioButton {
            font-size: 15px;
            padding: 4px 2px;
        }
        QRadioButton::indicator {
            width: 16px;
            height: 16px;
        }
        QRadioButton::indicator:checked {
            background-color: #3b82f6;
            border: 1px solid #1d4ed8;
            border-radius: 8px;
        }
        """)

    def _init_feedback_animation(self):
        self.feedback_effect = QGraphicsOpacityEffect(self.feedback_edit)
        self.feedback_edit.setGraphicsEffect(self.feedback_effect)
        self.feedback_anim = QPropertyAnimation(self.feedback_effect, b"opacity")
        self.feedback_anim.setDuration(260)
        self.feedback_anim.setStartValue(0.0)
        self.feedback_anim.setEndValue(1.0)

    def animate_feedback(self):
        if not self.feedback_anim or not self.feedback_effect:
            return
        self.feedback_anim.stop()
        self.feedback_effect.setOpacity(0.0)
        self.feedback_anim.start()

    # ---------- 工具函数 ----------

    def set_question_text(self, text: str):
        self.question_edit.setPlainText(text or "")

    def set_feedback_text(self, text: str):
        self.feedback_edit.setPlainText(text or "")

    def set_status(self, text: str):
        self.status_label.setText(text or "")

    def set_progress(self, text: str):
        self.progress_label.setText(text or "")

    def _refresh_favorite_star(self):
        if not hasattr(self, "btn_star_favorite"):
            return
        if not self.current_question:
            self.btn_star_favorite.setEnabled(False)
            self._set_star_style(False)
            return
        self.btn_star_favorite.setEnabled(True)
        self._set_star_style(self.current_question.id in self.favorite_ids)

    def _set_star_style(self, is_fav: bool):
        if is_fav:
            self.btn_star_favorite.setChecked(True)
            self.btn_star_favorite.setText("★ 已收藏")
            self.btn_star_favorite.setStyleSheet(
                "color: #f59e0b; font-weight: 700; border: none;"
                " background: transparent;"
            )
        else:
            self.btn_star_favorite.setChecked(False)
            self.btn_star_favorite.setText("☆ 收藏")
            self.btn_star_favorite.setStyleSheet(
                "color: #9ca3af; border: none; background: transparent;"
            )

    def show_short_answer(self, show: bool):
        self.short_answer_edit.setVisible(show)
        if show:
            self.short_answer_edit.clear()

    def clear_options(self):
        for btn in self.option_buttons:
            btn.setParent(None)
        self.option_buttons.clear()
        self.current_option_value = ""
        while self.options_layout.count():
            item = self.options_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def refresh_global_stats(self):
        stats = load_stats()
        total_answered = stats.get("total_answered", 0)
        total_correct = stats.get("total_correct", 0)
        rate = format_rate(total_correct, total_answered)
        self.label_stat_total.setText(f"总答题数：{total_answered}")
        self.label_stat_correct.setText(f"总正确数：{total_correct}")
        self.label_stat_rate.setText(f"总体正确率：{rate}")

    def _update_answer_summary(self):
        correct = sum(1 for s in self.index_status if s == "correct")
        wrong = sum(1 for s in self.index_status if s == "wrong")
        self.answer_summary_label.setText(f"做对 {correct} · 做错 {wrong}")

    # ---------- 答题卡（下拉框版） ----------

    def _clear_answer_card(self):
        self.card_combo.blockSignals(True)
        self.card_combo.clear()
        self.card_combo.blockSignals(False)

    def _setup_navigation(self, count: int):
        self.index_status = ["unanswered"] * count
        self.user_answers = [""] * count

        self._clear_answer_card()
        if count <= 0:
            self._update_answer_summary()
            return

        self.card_combo.blockSignals(True)
        for i in range(count):
            label = f"第 {i + 1} 题 · 未作答"
            self.card_combo.addItem(label, i)
        self.card_combo.blockSignals(False)
        self.card_combo.setCurrentIndex(0)
        self._update_answer_summary()

    def _refresh_answer_card(self):
        self.card_combo.blockSignals(True)
        for i in range(self.card_combo.count()):
            idx = self.card_combo.itemData(i)
            if idx is None:
                continue
            idx = int(idx)
            status = "unanswered"
            if 0 <= idx < len(self.index_status):
                status = self.index_status[idx]
            prefix = ""
            if status == "correct":
                prefix = "✓ "
            elif status == "wrong":
                prefix = "✗ "
            text = f"{prefix}第 {idx + 1} 题"
            self.card_combo.setItemText(i, text)
        if 0 <= self.current_index < self.card_combo.count():
            self.card_combo.setCurrentIndex(self.current_index)
        self.card_combo.blockSignals(False)

    def _on_card_combo_changed(self, combo_index: int):
        if not self.current_questions:
            return
        if combo_index < 0:
            return
        idx = self.card_combo.itemData(combo_index)
        if idx is None:
            return
        self._goto_question_idx(int(idx))

    def _on_card_jump_clicked(self):
        idx = self.card_combo.currentIndex()
        if idx < 0:
            return
        real = self.card_combo.itemData(idx)
        if real is None:
            return
        self._goto_question_idx(int(real))

    # ---------- 题库管理 & 收藏 ----------

    def on_import_bank(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择题库 Word 文件",
            "",
            "Word 文件 (*.docx)",
        )
        if not file_path:
            return

        try:
            count = parse_docx_and_save_to_json(file_path)
            self.current_bank_docx = file_path

            qs = load_questions_from_file()
            c_total = len(qs)
            c_single = sum(1 for q in qs if q.q_type == config.QTYPE_SINGLE)
            c_blank = sum(1 for q in qs if q.q_type == config.QTYPE_BLANK)
            c_tf = sum(1 for q in qs if q.q_type == config.QTYPE_TF)
            c_short = sum(1 for q in qs if q.q_type == config.QTYPE_SHORT)

            overview_lines = [
                "📚 题库导入成功！",
                "",
                f"源文件：{os.path.basename(file_path)}",
                "",
                f"总题数：{c_total}",
                f"单选题：{c_single}  填空题：{c_blank}",
                f"判断题：{c_tf}  简答题：{c_short}",
                "",
                "可以使用左侧“题库总览 / 收藏题目”查看全部题目并收藏。",
            ]
            self.set_feedback_text("\n".join(overview_lines))
            self.animate_feedback()

            self.set_status(f"题库导入成功，共 {c_total} 题。可以选择题型和题量开始刷题。")
            self.set_progress("题库已导入。")
        except Exception as e:
            self.set_status(f"题库导入失败：{e}")
            self.set_feedback_text("导入失败，请检查题库格式是否为标准 .docx。")
            self.animate_feedback()

    def on_delete_bank(self):
        delete_question_bank()
        self.current_bank_docx = None

        self.mode = None
        self.current_questions = []
        self.current_index = -1
        self.current_question = None
        self.waiting_answer = False
        self.index_status = []
        self.user_answers = []

        self._clear_answer_card()
        self.clear_options()
        self.show_short_answer(False)
        self.set_question_text("题库已删除，请先导入新的 Word 题库。")
        self.set_feedback_text("这里会显示新题库的答题反馈。")
        self.set_progress("当前未在刷题。")
        self.set_status("当前题库已删除，统计已重置。")

        self.btn_submit.setEnabled(False)

        self._update_answer_summary()
        self.refresh_global_stats()
        self.animate_feedback()
        self._refresh_favorite_star()

    def on_overview_bank(self):
        qs = load_questions_from_file()
        if not qs:
            self.set_status("当前题库为空，请先导入 Word 题库。")
            self.set_feedback_text("题库总览：当前没有可用题目。")
            self.animate_feedback()
            return

        dlg = QuestionOverviewDialog(self, qs, self.favorite_ids)
        dlg.exec()
        self.set_status("题库总览窗口已关闭，可以继续刷题。")

    def _toggle_favorite_state(self, qid: int) -> bool:
        if qid in self.favorite_ids:
            self.favorite_ids.remove(qid)
            is_fav = False
        else:
            self.favorite_ids.add(qid)
            is_fav = True
        save_favorite_ids(self.favorite_ids)
        self._set_star_style(is_fav)
        return is_fav

    def on_favorite_current_question(self):
        q = self.current_question
        if not q:
            self.set_status("当前没有题目可收藏，请先开始刷题或在题库总览中收藏题目。")
            self.set_feedback_text("收藏失败：当前没有正在浏览的题目。")
            self.animate_feedback()
            return

        qid = q.id
        is_fav = self._toggle_favorite_state(qid)
        msg = (
            f"已收藏题目（题号 {qid}）。" if is_fav else f"已取消收藏题目（题号 {qid}）。"
        )
        self.set_status(msg)
        self.set_feedback_text(msg)
        self.animate_feedback()

    def on_toggle_star_favorite(self):
        q = self.current_question
        if not q:
            self.set_status("当前没有题目可收藏，请先开始刷题。")
            self.set_feedback_text("收藏失败：当前没有正在浏览的题目。")
            self.animate_feedback()
            self._set_star_style(False)
            return

        is_fav = self._toggle_favorite_state(q.id)
        msg = (
            f"已收藏题目（题号 {q.id}）。" if is_fav else f"已取消收藏题目（题号 {q.id}）。"
        )
        self.set_status(msg)
        self.set_feedback_text(msg)
        self.animate_feedback()

    def on_view_favorites(self):
        qs = load_questions_from_file()
        if not qs:
            self.set_status("当前题库为空，无法查看收藏题目。")
            self.set_feedback_text("收藏夹为空或题库未加载。")
            self.animate_feedback()
            return

        fav_questions = [q for q in qs if q.id in self.favorite_ids]
        if not fav_questions:
            self.set_status("收藏夹中目前没有题目。")
            self.set_feedback_text("收藏夹为空：你可以在刷题时或在题库总览中收藏题目。")
            self.animate_feedback()
            return

        dlg = QuestionOverviewDialog(self, fav_questions, self.favorite_ids)
        dlg.setWindowTitle("收藏夹 · 已收藏的题目")
        dlg.exec()
        self.set_status("收藏夹窗口已关闭，可以继续刷题。")

    def on_refresh_stats(self):
        # 左边“总体统计”区域
        self.refresh_global_stats()

        # 右侧反馈区展示更详细的刷新结果
        stats = load_stats()
        total_answered = stats.get("total_answered", 0)
        total_correct = stats.get("total_correct", 0)
        rate = format_rate(total_correct, total_answered)

        per_type_total = stats.get("per_type_total") or stats.get("per_type_answered", {})
        per_type_correct = stats.get("per_type_correct", {})

        lines = [
            "📊 当前总体统计",
            "",
            f"总答题数：{total_answered}",
            f"总正确数：{total_correct}",
            f"总体正确率：{rate}",
        ]
        if per_type_total:
            lines.append("")
            lines.append("各题型表现：")
            for qtype, tot in per_type_total.items():
                corr = per_type_correct.get(qtype, 0)
                lines.append(f"- {qtype_label(qtype)}：{corr}/{tot}，正确率 {format_rate(corr, tot)}")

        self.set_feedback_text("\n".join(lines))
        self.set_status("已刷新总体统计。")
        self.animate_feedback()

    # ---------- 开始刷题 ----------

    def on_start_normal(self):
        all_questions = load_questions_from_file()
        if not all_questions:
            self.set_status("题库为空：请先导入 Word 题库并解析。")
            self.set_progress("当前未在刷题。")
            self.set_question_text("题库为空，请先导入 Word 题库。")
            self.animate_feedback()
            return

        qtype_data = self.qtype_combo.currentData()
        if qtype_data == "all":
            pool = list(all_questions)
        else:
            pool = [q for q in all_questions if q.q_type == qtype_data]

        if not pool:
            self.set_status("当前题库中没有该题型，可以换一个题型试试。")
            self.set_progress("当前未在刷题。")
            self.set_question_text("当前题库中没有这种题型。")
            self.animate_feedback()
            return

        n = int(self.count_spin.value())
        if n > len(pool):
            n = len(pool)

        questions = random.sample(pool, k=n)
        self._begin_quiz(questions, mode="normal")

    def on_start_wrong(self):
        wrong_all = load_wrong_questions()
        if not wrong_all:
            self.set_status("错题本为空：先在“开始刷题”中刷几题，错题会自动加入。")
            self.set_progress("当前未在刷题。")
            self.set_question_text("当前错题本为空。先去做几道题吧。")
            self.animate_feedback()
            return

        n = int(self.count_spin.value())
        if n > len(wrong_all):
            n = len(wrong_all)
        questions = random.sample(wrong_all, k=n)
        self._begin_quiz(questions, mode="wrong")

    def _begin_quiz(self, questions: List[Question], mode: str):
        self.mode = mode
        self.current_questions = list(questions)
        random.shuffle(self.current_questions)
        self.current_index = 0 if self.current_questions else -1
        self.current_question = (
            self.current_questions[0] if self.current_questions else None
        )

        self.per_type_total.clear()
        self.per_type_correct.clear()
        self.wrong_in_session.clear()
        self.waiting_answer = True

        self._setup_navigation(len(self.current_questions))

        self.btn_submit.setText("提交答案")
        self.btn_submit.setEnabled(True)
        self.set_status("已开始刷题，选择选项或输入答案后点击“提交答案”。")
        self.set_feedback_text("这里会显示你本题是否答对，以及参考答案。")
        self.animate_feedback()
        self._show_current_question()

    # ---------- 显示当前题目 ----------

    def _show_current_question(self):
        if not self.current_question:
            self.set_progress("当前未在刷题。")
            self.set_question_text("")
            self.clear_options()
            self.show_short_answer(False)
            self.btn_submit.setEnabled(False)
            self._refresh_favorite_star()
            self._refresh_answer_card()
            return

        q = self.current_question
        total = len(self.current_questions)
        idx = self.current_index + 1

        self.set_progress(f"第 {idx} / {total} 题  [{qtype_label(q.q_type)}]  (题号: {q.id})")
        self.set_question_text(q.question.strip())

        self.clear_options()
        self.show_short_answer(False)
        self.set_feedback_text("这里会显示你本题是否答对，以及参考答案。")

        if q.q_type == config.QTYPE_SINGLE:
            if q.options:
                self.options_box.setTitle("选择一个选项")
                for label in sorted(q.options.keys()):
                    text = q.options.get(label, "")
                    btn = QRadioButton(f"{label}.  {text}")
                    btn.setStyleSheet("font-size: 15px; padding: 4px;")
                    btn.toggled.connect(self._make_option_handler(label))
                    self.options_layout.addWidget(btn)
                    self.option_buttons.append(btn)
                saved = (
                    self.user_answers[self.current_index]
                    if self.current_index < len(self.user_answers)
                    else ""
                )
                if saved:
                    for b in self.option_buttons:
                        if b.text().startswith(f"{saved}."):
                            b.setChecked(True)
                            break
            else:
                self.options_box.setTitle("本题未解析出选项，请在下方输入答案")
                self.show_short_answer(True)

        elif q.q_type == config.QTYPE_TF:
            texts = ["正确", "错误"]
            self.options_box.setTitle("选择“正确”或“错误”")
            for txt in texts:
                btn = QRadioButton(txt)
                btn.setStyleSheet("font-size: 15px; padding: 4px;")
                btn.toggled.connect(self._make_option_handler(txt))
                self.options_layout.addWidget(btn)
                self.option_buttons.append(btn)
            saved = (
                self.user_answers[self.current_index]
                if self.current_index < len(self.user_answers)
                else ""
            )
            if saved:
                for b in self.option_buttons:
                    if b.text() == saved:
                        b.setChecked(True)
                        break
        else:
            self.options_box.setTitle("本题没有选项，在下方输入你的答案")
            self.show_short_answer(True)
            saved = (
                self.user_answers[self.current_index]
                if self.current_index < len(self.user_answers)
                else ""
            )
            if saved:
                self.short_answer_edit.setPlainText(saved)

        self._update_answer_summary()
        self._refresh_answer_card()
        self._refresh_favorite_star()

    def _make_option_handler(self, value: str):
        def handler(checked: bool):
            if checked:
                self.current_option_value = value
        return handler

    # ---------- 提交 / 上一题 / 下一题 ----------

    def on_submit_or_next(self):
        if not self.current_questions:
            self.set_status("请先点击左侧“开始刷题”或“只刷错题”。")
            self.set_feedback_text("当前没有进行中的刷题，会话为空。")
            self.animate_feedback()
            return

        if self.waiting_answer:
            self._handle_submit_answer()
        else:
            self._goto_next_question()

    def _handle_submit_answer(self):
        q = self.current_question
        if q is None:
            return

        if q.q_type in (config.QTYPE_SINGLE, config.QTYPE_TF):
            user_raw = (self.current_option_value or "").strip()
            if not user_raw:
                self.set_status("请先选择一个选项，再点击“提交答案”。")
                self.set_feedback_text("提示：你还没有选择任何选项。")
                self.animate_feedback()
                return
        else:
            user_raw = self.short_answer_edit.toPlainText().strip()
            if not user_raw:
                self.set_status("当前答案为空，已按空答案提交。")

        is_correct, _, _ = _check_answer(q, user_raw)
        answer_text = q.answer.strip() if q.answer else ""

        lines = [
            "✅ 回答正确！" if is_correct else "❌ 回答错误！",
            "",
            f"你的答案：{user_raw or '(空)'}",
            f"参考答案：{answer_text or '(题库中未设置答案)'}",
        ]
        self.set_feedback_text("\n".join(lines))
        self.set_status("本题已判分，查看反馈后可点击“下一题”，或用左侧答题卡快速跳题。")
        self.animate_feedback()

        t = q.q_type
        self.per_type_total[t] = self.per_type_total.get(t, 0) + 1
        if is_correct:
            self.per_type_correct[t] = self.per_type_correct.get(t, 0) + 1
        else:
            self.wrong_in_session[q.id] = q

        idx = self.current_index
        if 0 <= idx < len(self.index_status):
            self.index_status[idx] = "correct" if is_correct else "wrong"
        if 0 <= idx < len(self.user_answers):
            self.user_answers[idx] = user_raw

        self._update_answer_summary()

        per_total_once = {t: 1}
        per_correct_once = {t: 1 if is_correct else 0}
        _update_stats(per_total_once, per_correct_once)
        self.refresh_global_stats()

        self._refresh_answer_card()

        self.waiting_answer = False
        self.btn_submit.setEnabled(False)
        self.btn_submit.setText("提交答案")

    def _goto_next_question(self):
        if not self.current_questions:
            return

        next_index = self.current_index + 1
        if next_index >= len(self.current_questions):
            self._finish_session()
            return

        self.current_index = next_index
        self.current_question = self.current_questions[self.current_index]
        self._show_current_question()

        status = self.index_status[self.current_index]
        if status == "unanswered":
            self.waiting_answer = True
            self.btn_submit.setText("提交答案")
            self.btn_submit.setEnabled(True)
            self.set_feedback_text("这里会显示你本题是否答对，以及参考答案。")
            self.animate_feedback()
        else:
            self.waiting_answer = False
            self.btn_submit.setText("提交答案")
            self.btn_submit.setEnabled(False)
            self._show_existing_feedback()

        self._refresh_answer_card()

    def _goto_prev_question(self):
        if not self.current_questions:
            return
        if self.current_index <= 0:
            return

        self.current_index -= 1
        self.current_question = self.current_questions[self.current_index]
        self._show_current_question()

        status = self.index_status[self.current_index]
        if status == "unanswered":
            self.waiting_answer = True
            self.btn_submit.setText("提交答案")
            self.btn_submit.setEnabled(True)
            self.set_feedback_text("这里会显示你本题是否答对，以及参考答案。")
            self.animate_feedback()
        else:
            self.waiting_answer = False
            self.btn_submit.setText("提交答案")
            self.btn_submit.setEnabled(False)
            self._show_existing_feedback()

        self._refresh_answer_card()

    def _goto_question_idx(self, idx: int):
        if not self.current_questions:
            return
        if idx < 0 or idx >= len(self.current_questions):
            return

        self.current_index = idx
        self.current_question = self.current_questions[self.current_index]
        self._show_current_question()

        status = self.index_status[self.current_index]
        if status == "unanswered":
            self.waiting_answer = True
            self.btn_submit.setText("提交答案")
            self.btn_submit.setEnabled(True)
            self.set_feedback_text("这里会显示你本题是否答对，以及参考答案。")
            self.animate_feedback()
        else:
            self.waiting_answer = False
            self.btn_submit.setText("提交答案")
            self.btn_submit.setEnabled(False)
            self._show_existing_feedback()

        self._refresh_answer_card()

    def _show_existing_feedback(self):
        if not self.current_questions:
            return
        idx = self.current_index
        if idx < 0 or idx >= len(self.current_questions):
            return
        q = self.current_questions[idx]
        user_raw = self.user_answers[idx] if idx < len(self.user_answers) else ""
        if not user_raw:
            self.set_feedback_text("本题尚未作答。")
            self.animate_feedback()
            return
        is_correct, _, _ = _check_answer(q, user_raw)
        answer_text = q.answer.strip() if q.answer else ""
        lines = [
            "✅ 回答正确！" if is_correct else "❌ 回答错误！",
            "",
            f"你的答案：{user_raw or '(空)'}",
            f"参考答案：{answer_text or '(题库中未设置答案)'}",
        ]
        self.set_feedback_text("\n".join(lines))
        self.animate_feedback()

    # ---------- 结束一轮 ----------

    def _finish_session(self):
        if not self.current_questions:
            return

        total = sum(self.per_type_total.values())
        correct = sum(self.per_type_correct.values())
        wrong = total - correct

        if self.mode == "normal":
            if self.wrong_in_session:
                existing = load_wrong_questions()
                by_id = {q.id: q for q in existing}
                for q in self.wrong_in_session.values():
                    by_id[q.id] = q
                new_list = list(by_id.values())
                save_wrong_questions(new_list)
                wrong_msg = f"本轮新增错题 {len(self.wrong_in_session)} 道，错题本总数：{len(new_list)}。"
            else:
                wrong_msg = "本轮没有新增错题，错题本保持不变。"
        elif self.mode == "wrong":
            wrong_ids = set(self.wrong_in_session.keys())
            origin_ids = set(q.id for q in self.current_questions)
            correct_ids = origin_ids - wrong_ids

            wrong_all = load_wrong_questions()
            by_id = {q.id: q for q in wrong_all}
            for qid in correct_ids:
                by_id.pop(qid, None)
            for q in self.wrong_in_session.values():
                by_id[q.id] = q
            new_list = list(by_id.values())
            save_wrong_questions(new_list)
            wrong_msg = f"本轮练习结束后，错题本剩余 {len(new_list)} 道题。"
        else:
            wrong_msg = ""

        lines = [
            "📊 本轮刷题结束！",
            "",
            f"总题数：{total}",
            f"答对数：{correct}",
            f"答错数：{wrong}",
            f"本轮正确率：{format_rate(correct, total)}",
        ]
        if wrong_msg:
            lines.append("")
            lines.append(wrong_msg)

        self.set_feedback_text("\n".join(lines))
        self.set_status("本轮已结束，可以重新配置题型和题量再来一轮。")
        self.set_progress("当前未在刷题。")
        self.set_question_text("本轮结果已在右侧显示，你可以看一眼整体情况。")
        self.animate_feedback()

        self.mode = None
        self.current_questions = []
        self.current_index = -1
        self.current_question = None
        self.waiting_answer = False
        self.btn_submit.setText("提交答案")
        self.btn_submit.setEnabled(False)

        self._update_answer_summary()
        self.refresh_global_stats()
        self._refresh_answer_card()
        self._refresh_favorite_star()


def main():
    app = QApplication(sys.argv)
    base_font = QFont("Microsoft YaHei", 11)
    app.setFont(base_font)

    win = QuizWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
