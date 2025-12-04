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
from typing import List, Dict, Optional, Set, Callable

import html

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
    QMessageBox,
    QAbstractItemView,
)
from PySide6.QtCore import QEasingCurve, QEvent, Qt, QParallelAnimationGroup, QPropertyAnimation
from PySide6.QtGui import QFont, QIcon, QLinearGradient, QPainter, QPixmap, QColor, QBrush

import config
from storage import (
    load_questions_from_file,
    load_wrong_questions,
    save_wrong_questions,
    load_stats,
    reset_stats,
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


def build_app_icon() -> QIcon:
    """生成一个简洁的应用图标，用于窗口标题和提示弹窗。"""

    pix = QPixmap(96, 96)
    pix.fill(Qt.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    gradient = QLinearGradient(0, 0, 96, 96)
    gradient.setColorAt(0, QColor("#2563eb"))
    gradient.setColorAt(1, QColor("#0f172a"))
    painter.setBrush(QBrush(gradient))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(0, 0, 96, 96, 22, 22)

    painter.setPen(QColor("#e2e8f0"))
    painter.setFont(QFont("Microsoft YaHei", 40, QFont.ExtraBold))
    painter.drawText(pix.rect(), Qt.AlignCenter, "HP")
    painter.end()

    return QIcon(pix)


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


def build_preview_html(q: Question, include_wrong: bool = False) -> str:
    """将题目内容渲染为统一且易读的 HTML。"""

    def _wrap_paragraphs(text: str) -> str:
        lines = [html.escape(line.strip()) for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        return "".join(f"<p style='margin:4px 0'>{line}</p>" for line in lines)

    title_html = (
        "<div style='font-size:15px; font-weight:700; color:#111827'>"
        f"题号 {q.id} · {qtype_label(q.q_type)}"
        "</div>"
    )
    body_html = _wrap_paragraphs(q.question.strip())

    option_lines = []
    if q.options:
        for label, text in sorted(q.options.items()):
            opt_text = html.escape(text)
            option_lines.append(
                f"<li style='margin:6px 0'><b style='margin-right:6px'>{label}.</b>{opt_text}</li>"
            )
    options_html = (
        "<div style='margin-top:8px'><div style='color:#475569; font-weight:700; margin-bottom:4px'>选项</div>"
        "<ul style='margin:0; padding-left:18px'>" + "".join(option_lines) + "</ul></div>"
        if option_lines
        else ""
    )

    answer_html = ""
    if q.answer:
        answer_html = (
            "<div style='margin-top:12px; padding:10px; border-radius:8px; background:#f8fafc;"
            " border:1px solid #e2e8f0;'>"
            "<span style='color:#0f172a; font-weight:700'>参考答案：</span>"
            f"<span style='color:#111827'>{html.escape(q.answer.strip())}</span>"
            "</div>"
        )

    wrong_html = ""
    if include_wrong:
        wrong_times = getattr(q, "wrong_count", 0)
        if wrong_times:
            wrong_html = (
                "<div style='margin-top:10px; color:#b91c1c; font-weight:700'>"
                f"错题次数：{wrong_times}"
                "</div>"
            )

    return "".join(
        [
            "<div style='line-height:1.7; font-size:15px; color:#0f172a'>",
            title_html,
            f"<div style='margin-top:8px; font-size:16px'>{body_html}</div>",
            options_html,
            answer_html,
            wrong_html,
            "</div>",
        ]
    )


class QuestionOverviewDialog(QDialog):
    """题库总览窗口：展示所有题目，并支持收藏 / 取消收藏。"""

    def __init__(
        self,
        parent: QMainWindow,
        questions: List[Question],
        favorite_ids: Set[int],
        app_icon: Optional[QIcon] = None,
    ):
        super().__init__(parent)
        self.questions = questions
        self.favorite_ids = favorite_ids
        self._current_row = -1
        self._selection_guard = False
        self.setWindowTitle("题库总览 · 收藏题目")
        if app_icon:
            self.setWindowIcon(app_icon)
        self.resize(960, 600)

        layout = QVBoxLayout(self)

        info_label = QLabel("提示：点击每一行右侧的“收藏 / 取消收藏”按钮，可以实时收藏该题目。")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.table = QTableWidget(len(self.questions), 4, self)
        self.table.setHorizontalHeaderLabels(["题号", "题型", "题干预览", "收藏"])
        self.table.verticalHeader().setVisible(False)
        # 留出适中的行高，让收藏按钮居中但整体更紧凑
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setAutoScroll(False)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setMinimumSectionSize(82)

        layout.addWidget(self.table)

        # 选中题目的预览区，增加交互感
        preview_group = QGroupBox("完整题目 / 参考答案")
        preview_layout = QVBoxLayout(preview_group)
        self.preview = QTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(320)
        self.preview.setPlaceholderText("点击表格中的题目行，可以在这里预览题干和答案。")
        self.preview.setFont(QFont("Microsoft YaHei", 12))
        self.preview.setLineWrapMode(QTextEdit.WidgetWidth)
        self.preview.document().setDocumentMargin(8)
        preview_layout.addWidget(self.preview)
        layout.addWidget(preview_group)

        self._init_preview_animation()
        self.table.clicked.connect(self._on_row_clicked)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        self._populate_table()

        if self.questions:
            self._set_current_row(0, trigger_preview=True)

        # 提升可读性的局部样式
        self.setStyleSheet("""
        QDialog {
            background-color: #f4f6fb;
        }
        QTableWidget {
            background-color: #ffffff;
            color: #0f172a;
            gridline-color: #d1d5db;
            font-size: 13px;
            selection-background-color: #e0f2fe;
            selection-color: #0f172a;
        }
        QTableWidget::item {
            padding: 1px 3px;
        }
        QTableWidget::item:selected {
            background-color: #e0f2fe;
            color: #0f172a;
            font-weight: 700;
            outline: none;
            border: none;
        }
        QTableWidget::item:focus {
            outline: none;
            border: none;
        }
        QTableWidget::item:selected:hover {
            background-color: #e0f2fe;
            color: #0f172a;
        }
        QTableWidget::item:hover {
            background-color: #f1f5f9;
        }
        QHeaderView::section {
            background-color: #e5edff;
            color: #111827;
            font-weight: 600;
        }
        QPushButton#favoriteBtn {
            padding: 2px 8px;
            border-radius: 9px;
            border: 1px solid #cbd5e1;
            background-color: #f8fafc;
            color: #0f172a;
            font-weight: 700;
            font-size: 12px;
            min-height: 22px;
            min-width: 104px;
            transition: all 120ms ease;
        }
        QPushButton#favoriteBtn:hover {
            background-color: #e2e8f0;
            border-color: #cbd5e1;
        }
        QPushButton#favoriteBtn:pressed {
            background: #cbd5e1;
            border-color: #94a3b8;
            color: #0f172a;
        }
        QPushButton#favoriteBtn:focus {
            outline: none;
        }
        QGroupBox {
            border: 1px solid #d0d7e2;
            border-radius: 6px;
            margin-top: 8px;
            font-size: 13px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
        }
        QTextEdit#overviewPreview {
            background-color: #ffffff;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            padding: 10px;
            font-size: 14px;
            outline: none;
            line-height: 1.6;
        }
        QPushButton {
            padding: 2px 4px;
            border-radius: 6px;
            border: 1px solid #c7d2fe;
            background-color: #e0e7ff;
            color: #0f172a;
            font-weight: 600;
            min-width: 60px;
            min-height: 20px;
        }
        QPushButton:hover {
            background-color: #c7d2fe;
            border-color: #a5b4fc;
        }
        """)

    def _init_preview_animation(self):
        self.preview.setObjectName("overviewPreview")
        self.preview_effect = QGraphicsOpacityEffect(self.preview)
        self.preview.setGraphicsEffect(self.preview_effect)
        self.preview_anim = QPropertyAnimation(self.preview_effect, b"opacity")
        self.preview_anim.setDuration(240)
        self.preview_anim.setStartValue(0.0)
        self.preview_anim.setEndValue(1.0)

    def _animate_preview(self):
        if not self.preview_anim or not self.preview_effect:
            return
        self.preview_anim.stop()
        self.preview_effect.setOpacity(0.0)
        self.preview_anim.start()

    def _animate_button_pulse(self, btn: QPushButton):
        effect = getattr(btn, "_pulse_effect", None)
        if not effect:
            effect = QGraphicsOpacityEffect(btn)
            btn.setGraphicsEffect(effect)
            btn._pulse_effect = effect
        anim = QPropertyAnimation(effect, b"opacity", btn)
        anim.setDuration(200)
        anim.setStartValue(0.6)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def _populate_table(self):
        from functools import partial

        button_font = QFont("Microsoft YaHei", 10, QFont.DemiBold)

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
            btn.setObjectName("favoriteBtn")
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setFont(button_font)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setMinimumWidth(108)
            btn.setMinimumHeight(22)
            self._update_fav_button_text(btn, q.id)
            btn.clicked.connect(partial(self._on_fav_button_clicked, row, q.id, btn))

            container = QWidget(self)
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(2, 0, 2, 0)
            container_layout.setSpacing(0)
            container_layout.setAlignment(Qt.AlignCenter)
            container_layout.addWidget(btn)
            container_layout.setAlignment(btn, Qt.AlignCenter)
            self.table.setCellWidget(row, 3, container)

        # 确保“收藏 / 取消收藏”按钮列足够展示完整文本且不显得过宽
        self.table.setColumnWidth(3, max(self.table.columnWidth(3), 132))
        # 让“题型”列有更宽的空间避免文字被省略
        self.table.setColumnWidth(1, max(self.table.columnWidth(1), 92))

    def _update_fav_button_text(self, btn: QPushButton, qid: int):
        if qid in self.favorite_ids:
            btn.setText("★ 取消收藏")
            btn.setStyleSheet(
                "background-color: #fff7d6; border: 1px solid #f4b740;"
                " color: #92400e;"
                " box-shadow: 0 2px 10px rgba(245, 158, 11, 0.35);"
            )
        else:
            btn.setText("☆ 收藏")
            btn.setStyleSheet(
                "background-color: #f8fafc; border: 1px solid #cbd5e1;"
                " color: #0f172a; box-shadow: none;"
            )

    def _on_row_clicked(self, model_index):
        row = model_index.row() if hasattr(model_index, "row") else self.table.currentRow()
        self._set_current_row(row, trigger_preview=True)

    def _set_current_row(self, row: int, trigger_preview: bool = False):
        # 保持只有明确点击行时才切换预览，避免鼠标悬停误切换。
        if row < 0 or row >= len(self.questions):
            self.preview.clear()
            return

        self._selection_guard = True
        self._current_row = row
        self.table.selectRow(row)
        self._selection_guard = False

        if not trigger_preview:
            return

        q = self.questions[row]
        self.preview.setHtml(build_preview_html(q))
        self._animate_preview()

    def _on_fav_button_clicked(self, row: int, qid: int, btn: QPushButton):
        # 点击收藏按钮时，主动保持当前选择行和预览与按钮所在行一致。
        self._set_current_row(row, trigger_preview=True)
        self._toggle_favorite(qid, btn)

    def _on_selection_changed(self, *_):
        if self._selection_guard:
            return
        if QApplication.mouseButtons() != Qt.NoButton:
            return
        if self.table.hasFocus():
            return
        if self._current_row >= 0:
            self._set_current_row(self._current_row)

    def _toggle_favorite(self, qid: int, btn: QPushButton):
        if qid in self.favorite_ids:
            self.favorite_ids.remove(qid)
        else:
            self.favorite_ids.add(qid)
        save_favorite_ids(self.favorite_ids)
        self._update_fav_button_text(btn, qid)
        self._animate_button_pulse(btn)


class WrongOverviewDialog(QDialog):
    """错题本总览：浏览全部错题并可移除。"""

    def __init__(
        self,
        parent: QMainWindow,
        questions: List[Question],
        toggle_callback: Callable[[Question], bool],
        app_icon: Optional[QIcon] = None,
    ):
        super().__init__(parent)
        self.questions = list(questions)
        self.toggle_callback = toggle_callback
        self._current_row = -1
        self._selection_guard = False
        self.setWindowTitle("错题本总览")
        if app_icon:
            self.setWindowIcon(app_icon)
        self.resize(980, 620)

        layout = QVBoxLayout(self)

        self.info_label = QLabel("提示：可查看错题次数，或点击右侧按钮直接移出错题本。")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.table = QTableWidget(len(self.questions), 5, self)
        self.table.setHorizontalHeaderLabels(["题号", "题型", "题干预览", "错题次数", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setAutoScroll(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setMinimumSectionSize(82)

        layout.addWidget(self.table)

        preview_group = QGroupBox("完整题目 / 参考答案")
        preview_layout = QVBoxLayout(preview_group)
        self.preview = QTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(320)
        self.preview.setPlaceholderText("点击表格中的题目行，可以在这里预览题干和答案。")
        self.preview.setFont(QFont("Microsoft YaHei", 12))
        self.preview.setLineWrapMode(QTextEdit.WidgetWidth)
        self.preview.document().setDocumentMargin(8)
        preview_layout.addWidget(self.preview)
        layout.addWidget(preview_group)

        self._init_preview_animation()
        self.table.clicked.connect(self._on_row_clicked)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        self._populate_table()

        if self.questions:
            self._set_current_row(0, trigger_preview=True)

        self.setStyleSheet("""
        QDialog {
            background-color: #f4f6fb;
        }
        QTableWidget {
            background-color: #ffffff;
            color: #0f172a;
            gridline-color: #d1d5db;
            font-size: 13px;
            selection-background-color: #e0f2fe;
            selection-color: #0f172a;
        }
        QTableWidget::item {
            padding: 1px 3px;
        }
        QTableWidget::item:selected {
            background-color: #e0f2fe;
            color: #0f172a;
            font-weight: 700;
            border: 1px solid #bfdbfe;
            border-radius: 4px;
        }
        QTableWidget::item:focus {
            outline: none;
        }
        QTableWidget::item:selected:hover {
            background-color: #e0f2fe;
            color: #0f172a;
        }
        QTableWidget::item:hover {
            background-color: #f1f5f9;
        }
        QHeaderView::section {
            background-color: #e5edff;
            color: #111827;
            font-weight: 600;
        }
        QGroupBox {
            border: 1px solid #d0d7e2;
            border-radius: 6px;
            margin-top: 8px;
            font-size: 13px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
        }
        QTextEdit#overviewPreview {
            background-color: #ffffff;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            padding: 8px;
            font-size: 14px;
            outline: none;
        }
        QPushButton#removeWrongBtn {
            padding: 1px 6px;
            border-radius: 7px;
            border: 1px solid #fca5a5;
            background-color: #fef2f2;
            color: #b91c1c;
            font-weight: 700;
            font-size: 12px;
            min-height: 20px;
            min-width: 98px;
        }
        QPushButton#removeWrongBtn:hover {
            background-color: #fee2e2;
            border-color: #f87171;
        }
        QPushButton#removeWrongBtn:disabled {
            background-color: #f8fafc;
            border-color: #cbd5e1;
            color: #94a3b8;
        }
        """)

    def _init_preview_animation(self):
        self.preview.setObjectName("overviewPreview")
        self.preview_effect = QGraphicsOpacityEffect(self.preview)
        self.preview.setGraphicsEffect(self.preview_effect)
        self.preview_anim = QPropertyAnimation(self.preview_effect, b"opacity")
        self.preview_anim.setDuration(240)
        self.preview_anim.setStartValue(0.0)
        self.preview_anim.setEndValue(1.0)

    def _animate_preview(self):
        if not self.preview_anim or not self.preview_effect:
            return
        self.preview_anim.stop()
        self.preview_effect.setOpacity(0.0)
        self.preview_anim.start()

    def _populate_table(self):
        from functools import partial

        button_font = QFont("Microsoft YaHei", 10, QFont.DemiBold)

        for row, q in enumerate(self.questions):
            item_id = QTableWidgetItem(str(q.id))
            item_type = QTableWidgetItem(qtype_label(q.q_type))
            text = q.question.replace("\n", " ")
            if len(text) > 40:
                text = text[:40] + "..."
            item_q = QTableWidgetItem(text)
            wrong_times = getattr(q, "wrong_count", 0)
            item_wrong = QTableWidgetItem(str(wrong_times))

            self.table.setItem(row, 0, item_id)
            self.table.setItem(row, 1, item_type)
            self.table.setItem(row, 2, item_q)
            self.table.setItem(row, 3, item_wrong)

            btn = QPushButton("🗑 移出错题本", self)
            btn.setObjectName("removeWrongBtn")
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setFont(button_font)
            btn.setMinimumWidth(112)
            btn.setMinimumHeight(22)
            btn.clicked.connect(partial(self._on_toggle_clicked, q, btn))
            self._update_button_text(btn, True)

            container = QWidget(self)
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(6, 0, 6, 0)
            container_layout.setSpacing(0)
            container_layout.setAlignment(Qt.AlignCenter)
            container_layout.addWidget(btn)
            container_layout.setAlignment(btn, Qt.AlignCenter)
            self.table.setCellWidget(row, 4, container)

        # 让“移出错题本”按钮列保持足够宽度并保持居中显示
        self.table.setColumnWidth(4, max(self.table.columnWidth(4), 132))
        self.table.setColumnWidth(1, max(self.table.columnWidth(1), 92))

    def _on_row_clicked(self, model_index):
        row = model_index.row() if hasattr(model_index, "row") else self.table.currentRow()
        self._set_current_row(row, trigger_preview=True)

    def _set_current_row(self, row: int, trigger_preview: bool = False):
        if row < 0 or row >= len(self.questions):
            self.preview.clear()
            return

        self._selection_guard = True
        self._current_row = row
        self.table.selectRow(row)
        self._selection_guard = False

        if not trigger_preview:
            return

        q = self.questions[row]
        self.preview.setHtml(build_preview_html(q, include_wrong=True))
        self._animate_preview()

    def _on_toggle_clicked(self, question: Question, btn: QPushButton):
        if not self.toggle_callback:
            return

        in_book = self.toggle_callback(question)
        self._update_button_text(btn, in_book)
        self._animate_button_pulse(btn)
        self._sync_info_label(in_book)

    def _update_button_text(self, btn: QPushButton, in_book: bool):
        if in_book:
            btn.setText("🗑 移出错题本")
            btn.setStyleSheet("")
        else:
            btn.setText("↩ 加回错题本")
            btn.setStyleSheet(
                "background-color: #ecfdf3; border: 1px solid #bbf7d0;"
                " color: #166534;"
            )

    def _sync_info_label(self, in_book: bool):
        if in_book:
            self.info_label.setText("提示：可查看错题次数，或点击右侧按钮直接移出错题本。")
        else:
            self.info_label.setText("提示：已移出，可再次点击“加回错题本”恢复。")

    def _on_selection_changed(self, *_):
        if self._selection_guard:
            return
        if QApplication.mouseButtons() != Qt.NoButton:
            return
        if self.table.hasFocus():
            return
        if self._current_row >= 0:
            self._set_current_row(self._current_row)

    def _remove_row_by_id(self, qid: int):
        target_row = None
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.text() == str(qid):
                target_row = r
                break

        if target_row is None:
            return

        if 0 <= target_row < len(self.questions):
            self.questions.pop(target_row)
        self.table.removeRow(target_row)

        if self.table.rowCount() == 0:
            self.preview.setHtml("<b>错题本已清空，快去继续刷题吧！</b>")
            self.info_label.setText("当前错题本为空，可以关闭窗口返回刷题。")
            return

        next_row = min(target_row, self.table.rowCount() - 1)
        self._set_current_row(next_row, trigger_preview=True)


class QuizWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.app_icon = build_app_icon()
        self.setWindowTitle("本地刷题系统")
        self.setWindowIcon(self.app_icon)
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
        self.wrong_book_map: Dict[int, Question] = {}

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
        self.question_effect: Optional[QGraphicsOpacityEffect] = None
        self.question_anim: Optional[QPropertyAnimation] = None
        self.options_effect: Optional[QGraphicsOpacityEffect] = None
        self.options_anim: Optional[QPropertyAnimation] = None
        self.question_anim_group: Optional[QParallelAnimationGroup] = None

        self._hover_anims: Dict[QPushButton, QPropertyAnimation] = {}

        self.stats_effect: Optional[QGraphicsOpacityEffect] = None
        self.stats_anim: Optional[QPropertyAnimation] = None

        self._build_ui()
        self._apply_style()
        self._init_feedback_animation()
        self._init_question_animation()
        self._refresh_wrong_book_cache()
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

        title_label = QLabel("本地刷题系统")
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
        self.btn_wrong_overview = QPushButton("错题本总览")
        self.btn_view_favorites = QPushButton("查看收藏夹")
        bank_layout.addWidget(self.btn_import_bank)
        bank_layout.addWidget(self.btn_delete_bank)
        bank_layout.addWidget(self.btn_overview_bank)
        bank_layout.addWidget(self.btn_wrong_overview)
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
        progress_layout.addSpacing(10)
        self.btn_remove_wrong = QPushButton("移出错题本")
        self.btn_remove_wrong.setObjectName("removeWrongInline")
        progress_layout.addWidget(self.btn_remove_wrong)
        self.btn_star_favorite = QPushButton("☆ 收藏")
        self.btn_star_favorite.setObjectName("favoriteStar")
        self.btn_star_favorite.setToolTip("点击收藏 / 取消收藏当前题目")
        self.btn_star_favorite.setCheckable(True)
        progress_layout.addWidget(self.btn_star_favorite)
        progress_layout.addStretch()
        center_panel.addWidget(progress_frame)

        question_group = QGroupBox("题目")
        q_layout = QVBoxLayout(question_group)
        self.question_edit = QTextEdit()
        self.question_edit.setObjectName("questionEdit")
        self.question_edit.setReadOnly(True)
        self.question_edit.setAcceptRichText(False)
        self.question_edit.setMinimumHeight(160)
        self.question_edit.setFont(QFont("Microsoft YaHei", 19))
        q_layout.addWidget(self.question_edit)
        center_panel.addWidget(question_group, 3)

        options_group = QGroupBox("作答区域")
        options_layout_outer = QVBoxLayout(options_group)
        options_layout_outer.setSpacing(8)
        options_layout_outer.setContentsMargins(12, 10, 12, 10)

        self.options_box = QGroupBox("选择一个选项")
        self.options_layout = QVBoxLayout(self.options_box)
        self.options_layout.setSpacing(8)
        options_layout_outer.addWidget(self.options_box)

        self.short_answer_edit = QPlainTextEdit()
        self.short_answer_edit.setObjectName("shortAnswerEdit")
        self.short_answer_edit.setPlaceholderText("填空题 / 简答题：在这里输入你的答案。")
        self.short_answer_edit.setMinimumHeight(80)
        self.short_answer_edit.setFont(QFont("Microsoft YaHei", 16))
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

        stats_group = QGroupBox("总体统计")
        stats_layout = QVBoxLayout(stats_group)
        self.label_stat_total = QLabel("总答题数：0")
        self.label_stat_correct = QLabel("总正确数：0")
        self.label_stat_rate = QLabel("总体正确率：0.00%")
        for w in (self.label_stat_total, self.label_stat_correct, self.label_stat_rate):
            stats_layout.addWidget(w)

        self.label_stat_detail = QLabel("各题型表现：")
        self.label_stat_detail.setObjectName("statDetailTitle")
        stats_layout.addWidget(self.label_stat_detail)

        self.stats_detail_container = QVBoxLayout()
        self.stats_detail_container.setSpacing(4)
        stats_layout.addLayout(self.stats_detail_container)

        self.btn_refresh_stats = QPushButton("刷新 / 重置统计")
        self.btn_refresh_stats.setObjectName("refreshStatsBtn")
        stats_layout.addWidget(self.btn_refresh_stats)
        right_panel.addWidget(stats_group)

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
        bottom_layout.addStretch()
        self.footer_label = QLabel("感谢使用本地刷题系统 · 产品反馈邮箱：haoping0124@gmail.com")
        self.footer_label.setObjectName("footerNote")
        bottom_layout.addWidget(self.footer_label, 0, Qt.AlignRight)
        root_layout.addWidget(bottom_frame)

        # 信号连接
        self.btn_import_bank.clicked.connect(self.on_import_bank)
        self.btn_delete_bank.clicked.connect(self.on_delete_bank)
        self.btn_overview_bank.clicked.connect(self.on_overview_bank)
        self.btn_wrong_overview.clicked.connect(self.on_show_wrong_overview)
        self.btn_view_favorites.clicked.connect(self.on_view_favorites)
        self.btn_remove_wrong.clicked.connect(self.on_remove_from_wrong_book)

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
        self._refresh_remove_wrong_button()
        self._init_hover_animations()
        self._init_stats_animation(stats_group)

    def _apply_style(self):
        self.setStyleSheet("""
        * {
            color: #1f2933;
            font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
        }
        QMainWindow {
            background-color: #eef2f7;
        }
        QToolTip {
            background-color: #0b1221;
            color: #f8fafc;
            border: 1px solid #0b1221;
            border-radius: 10px;
            padding: 6px 10px;
            box-shadow: none;
        }
        QToolTip QLabel {
            background: transparent;
            border: none;
        }
        #header {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                       stop:0 #34495e, stop:1 #2c3e50);
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.12);
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
            font-size: 13.5px;
            box-shadow: 0 10px 28px rgba(15, 23, 42, 0.07);
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
        }

        QLabel {
            font-size: 15px;
        }
        #footerNote {
            font-size: 12px;
            color: #6b7280;
        }
        #answerSummary {
            font-size: 15px;
            font-weight: 500;
        }
        #statDetailTitle {
            font-size: 13px;
            color: #475569;
            margin-top: 6px;
        }
        #statDetailPlaceholder {
            font-size: 13px;
            color: #94a3b8;
            padding-left: 2px;
        }
        #statDetailLine {
            font-size: 13px;
            color: #0f172a;
            padding-left: 2px;
        }

        QComboBox, QSpinBox {
            background-color: #ffffff;
            color: #111827;
            border: 1px solid #d0d7e2;
            border-radius: 4px;
            padding: 2px 4px;
            font-size: 14px;
        }
        QComboBox QAbstractItemView {
            background-color: #ffffff;
            color: #111827;
            font-size: 14px;
        }

        QPushButton {
            padding: 6px 14px;
            border-radius: 6px;
            border: 1px solid #d0d7e2;
            background-color: #ffffff;
            font-size: 14px;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.06);
        }
        QPushButton:hover {
            background-color: #eff4ff;
            border-color: #3b82f6;
        }
        QPushButton#navButton {
            font-size: 15px;
            padding: 6px 18px;
        }
        QPushButton#primaryButton {
            background-color: #3b82f6;
            color: white;
            border-color: #3b82f6;
            font-weight: 500;
            font-size: 15px;
            padding: 6px 18px;
        }
        QPushButton#primaryButton:hover {
            background-color: #2563eb;
        }
        QPushButton#refreshStatsBtn {
            background-color: #0ea5e9;
            color: #f8fafc;
            border-color: #0284c7;
            font-weight: 600;
            font-size: 13px;
        }
        QPushButton#refreshStatsBtn:hover {
            background-color: #0284c7;
            border-color: #0369a1;
        }

        QTextEdit, QPlainTextEdit {
            border-radius: 6px;
            border: 1px solid #d0d7e2;
            background-color: #ffffff;
            font-size: 15px;
        }
        QTextEdit:focus, QPlainTextEdit:focus {
            outline: none;
            border: 1px solid #93c5fd;
            box-shadow: 0 0 0 2px rgba(147, 197, 253, 0.35);
        }
        #questionEdit {
            font-size: 17px;
            line-height: 1.7;
        }
        #shortAnswerEdit {
            font-size: 15px;
        }
        #feedbackEdit {
            background-color: #f9fbff;
            font-size: 15px;
        }

        #progressFrame {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                       stop:0 #e0ebff, stop:1 #f3f7ff);
            border-radius: 8px;
            border: 1px solid #d0ddf0;
        }

        QRadioButton {
            font-size: 16px;
            padding: 6px 4px;
            font-weight: 500;
        }
        QRadioButton::indicator {
            width: 18px;
            height: 18px;
            border: 1px solid #cbd5e1;
            border-radius: 9px;
            background: #ffffff;
            margin-right: 6px;
            transition: all 0.2s ease;
        }
        QRadioButton::indicator:hover {
            border-color: #3b82f6;
        }
        QRadioButton::indicator:checked {
            background-color: #3b82f6;
            border: 1px solid #1d4ed8;
            border-radius: 8px;
        }

        QSpinBox {
            padding-right: 28px;
        }
        QSpinBox::up-button, QSpinBox::down-button {
            width: 22px;
            border: none;
            background: transparent;
            margin: 0;
            padding: 2px 2px;
        }
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {
            background-color: #e5edff;
            border-radius: 4px;
        }
        QSpinBox::up-arrow, QSpinBox::down-arrow {
            width: 10px;
            height: 10px;
        }

        #favoriteStar {
            font-weight: 700;
            padding: 6px 16px;
            border-radius: 18px;
            border: 1px solid #fbbf24;
            background-color: #fff7ed;
            color: #b45309;
            min-width: 90px;
        }
        #favoriteStar:hover {
            background-color: #ffedd5;
            border-color: #f59e0b;
        }
        QPushButton#removeWrongInline {
            background-color: #fee2e2;
            border-color: #ef4444;
            color: #b91c1c;
            font-weight: 600;
            padding: 6px 14px;
        }
        QPushButton#removeWrongInline:hover {
            background-color: #fecdd3;
            border-color: #dc2626;
        }
        """)

    def _init_hover_animations(self):
        buttons = [
            self.btn_import_bank,
            self.btn_delete_bank,
            self.btn_overview_bank,
            self.btn_wrong_overview,
            self.btn_view_favorites,
            self.btn_remove_wrong,
            self.btn_start_normal,
            self.btn_start_wrong,
            self.btn_prev,
            self.btn_next,
            self.btn_submit,
            self.btn_card_jump,
            self.btn_star_favorite,
        ]
        for btn in buttons:
            self._attach_hover_animation(btn)

    def _attach_hover_animation(self, btn: QPushButton):
        effect = QGraphicsOpacityEffect(btn)
        effect.setOpacity(1.0)
        btn.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", btn)
        anim.setDuration(160)
        anim.setStartValue(1.0)
        anim.setEndValue(0.9)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._hover_anims[btn] = anim
        btn.installEventFilter(self)

    def _start_hover_anim(self, btn: QPushButton, target: float):
        anim = self._hover_anims.get(btn)
        effect = btn.graphicsEffect()
        if not anim or not isinstance(effect, QGraphicsOpacityEffect):
            return
        anim.stop()
        anim.setStartValue(effect.opacity())
        anim.setEndValue(target)
        anim.start()

    def eventFilter(self, obj, event):
        if obj in self._hover_anims:
            if event.type() == QEvent.Enter:
                self._start_hover_anim(obj, 0.86)
            elif event.type() == QEvent.Leave:
                self._start_hover_anim(obj, 1.0)
        return super().eventFilter(obj, event)

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

    def _init_question_animation(self):
        self.question_effect = QGraphicsOpacityEffect(self.question_edit)
        self.question_edit.setGraphicsEffect(self.question_effect)
        self.question_anim = QPropertyAnimation(self.question_effect, b"opacity")
        self.question_anim.setDuration(260)
        self.question_anim.setStartValue(0.0)
        self.question_anim.setEndValue(1.0)
        self.question_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.options_effect = QGraphicsOpacityEffect(self.options_box)
        self.options_box.setGraphicsEffect(self.options_effect)
        self.options_anim = QPropertyAnimation(self.options_effect, b"opacity")
        self.options_anim.setDuration(260)
        self.options_anim.setStartValue(0.0)
        self.options_anim.setEndValue(1.0)
        self.options_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.question_anim_group = QParallelAnimationGroup(self)
        self.question_anim_group.addAnimation(self.question_anim)
        self.question_anim_group.addAnimation(self.options_anim)

    def animate_question(self):
        if not self.question_anim_group or not self.question_anim:
            return
        self.question_anim_group.stop()
        if self.question_effect:
            self.question_effect.setOpacity(0.0)
        if self.options_effect:
            self.options_effect.setOpacity(0.0)
        self.question_anim_group.start()

    def _init_stats_animation(self, stats_group: QGroupBox):
        self.stats_effect = QGraphicsOpacityEffect(stats_group)
        stats_group.setGraphicsEffect(self.stats_effect)
        self.stats_anim = QPropertyAnimation(self.stats_effect, b"opacity", stats_group)
        self.stats_anim.setDuration(220)
        self.stats_anim.setStartValue(0.0)
        self.stats_anim.setEndValue(1.0)
        self.stats_anim.setEasingCurve(QEasingCurve.InOutQuad)

    def animate_stats(self):
        if not self.stats_anim or not self.stats_effect:
            return
        self.stats_anim.stop()
        self.stats_effect.setOpacity(0.0)
        self.stats_anim.start()

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

    def _refresh_remove_wrong_button(self):
        if not hasattr(self, "btn_remove_wrong"):
            return
        visible = self.mode == "wrong"
        self.btn_remove_wrong.setVisible(visible)
        if not visible or not self.current_question:
            self.btn_remove_wrong.setEnabled(False)
            self.btn_remove_wrong.setText("移出错题本")
            return

        count = self._get_wrong_count(self.current_question)
        in_book = self.current_question.id in self.wrong_book_map
        self.btn_remove_wrong.setEnabled(True)
        if in_book:
            if count > 0:
                self.btn_remove_wrong.setText(f"移出错题本（错 {count} 次）")
            else:
                self.btn_remove_wrong.setText("移出错题本")
        else:
            self.btn_remove_wrong.setText("加回错题本")

    def _set_star_style(self, is_fav: bool):
        base_style = (
            "font-weight: 800; font-size: 15px; padding: 8px 18px; border-radius: 18px;"
            " min-width: 110px; letter-spacing: 0.5px;"
        )
        if is_fav:
            self.btn_star_favorite.setChecked(True)
            self.btn_star_favorite.setText("★ 已收藏")
            self.btn_star_favorite.setStyleSheet(
                base_style
                + "border: 2px solid #f59e0b; background-color: #fff4e6; color: #9a3412;"
                + " box-shadow: 0 5px 14px rgba(234, 179, 8, 0.35);"
            )
        else:
            self.btn_star_favorite.setChecked(False)
            self.btn_star_favorite.setText("☆ 收藏")
            self.btn_star_favorite.setStyleSheet(
                base_style
                + "border: 2px dashed #cbd5e1; background-color: #f8fafc; color: #0f172a;"
                + " box-shadow: 0 4px 10px rgba(148, 163, 184, 0.35);"
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

    def _apply_stats_to_labels(self, stats: Dict[str, int]):
        total_answered = stats.get("total_answered", 0)
        total_correct = stats.get("total_correct", 0)
        rate = format_rate(total_correct, total_answered)
        self.label_stat_total.setText(f"总答题数：{total_answered}")
        self.label_stat_correct.setText(f"总正确数：{total_correct}")
        self.label_stat_rate.setText(f"总体正确率：{rate}")
        per_type_total = (
            stats.get("per_type_total")
            or stats.get("per_type_answered", {})
            or {}
        )
        per_type_correct = stats.get("per_type_correct", {}) or {}
        self._render_stats_details(per_type_total, per_type_correct)
        if self.stats_effect:
            self.stats_effect.setOpacity(1.0)

    def refresh_global_stats(self):
        stats = load_stats()
        self._apply_stats_to_labels(stats)

    def _render_stats_details(self, per_type_total: Dict[str, int], per_type_correct: Dict[str, int]):
        while self.stats_detail_container.count():
            item = self.stats_detail_container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)

        if not per_type_total:
            placeholder = QLabel("暂无题型统计数据。")
            placeholder.setObjectName("statDetailPlaceholder")
            self.stats_detail_container.addWidget(placeholder)
            return

        for qtype, total in per_type_total.items():
            correct = per_type_correct.get(qtype, 0)
            detail = QLabel(
                f"• {qtype_label(qtype)}：{correct}/{total}，正确率 {format_rate(correct, total)}"
            )
            detail.setObjectName("statDetailLine")
            self.stats_detail_container.addWidget(detail)

    def _refresh_wrong_book_cache(self):
        self.wrong_book_map = {q.id: q for q in load_wrong_questions()}

    def _get_wrong_count(self, question: Question) -> int:
        if not question:
            return 0
        cached = self.wrong_book_map.get(question.id)
        if cached:
            return getattr(cached, "wrong_count", 0)
        return getattr(question, "wrong_count", 0)

    def _save_wrong_question_immediately(self, question: Question):
        existing = load_wrong_questions()
        by_id = {q.id: q for q in existing}
        prev = by_id.get(question.id)
        prev_count = getattr(prev, "wrong_count", 0) if prev else 0
        question.wrong_count = prev_count + 1
        by_id[question.id] = question
        save_wrong_questions(list(by_id.values()))
        self.wrong_book_map = by_id

    def _toggle_wrong_book_entry(self, question: Question) -> bool:
        wrong_all = load_wrong_questions()
        by_id = {q.id: q for q in wrong_all}

        if question.id in by_id:
            by_id.pop(question.id)
            in_book = False
        else:
            question.wrong_count = max(self._get_wrong_count(question), 1)
            by_id[question.id] = question
            in_book = True

        save_wrong_questions(list(by_id.values()))
        self._refresh_wrong_book_cache()
        return in_book

    def _update_answer_summary(self):
        correct = sum(1 for s in self.index_status if s == "correct")
        wrong = sum(1 for s in self.index_status if s == "wrong")
        self.answer_summary_label.setText(f"做对 {correct} · 做错 {wrong}")

    def _cache_current_answer(self):
        """在跳题前缓存当前题目的作答，确保返回时可恢复。"""
        if not self.current_questions:
            return
        if self.current_index < 0 or self.current_index >= len(self.user_answers):
            return

        q = self.current_questions[self.current_index]
        if q.q_type in (config.QTYPE_SINGLE, config.QTYPE_TF):
            cached = self.current_option_value or ""
        else:
            cached = self.short_answer_edit.toPlainText().strip()
        self.user_answers[self.current_index] = cached

    # ---------- 答题卡（下拉框版） ----------

    def _clear_answer_card(self):
        self.card_combo.blockSignals(True)
        self.card_combo.clear()
        self.card_combo.blockSignals(False)

    def _setup_navigation(self, count: int):
        self.index_status = ["unanswered"] * count
        self.user_answers = [""] * count
        self.current_option_value = ""
        self.short_answer_edit.clear()

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

    def _update_status_for_current_question(self):
        if not self.current_questions or self.current_index < 0:
            return
        status = (
            self.index_status[self.current_index]
            if self.current_index < len(self.index_status)
            else "unanswered"
        )
        if status == "unanswered":
            self.set_status("请阅读题目后作答，提交后可查看反馈。")
        else:
            self.set_status("本题已判分，查看反馈后可点击“下一题”，或用左侧答题卡快速跳题。")

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

            success_msg = (
                f"共 {c_total} 道题（单选 {c_single} · 填空 {c_blank} · 判断 {c_tf} · 简答 {c_short}）。"
                "\n可以使用“题库总览 / 收藏题目”查看全部题目并收藏。"
            )
            self._show_result_dialog("题库导入成功", success_msg, success=True)
        except Exception as e:
            self.set_status(f"题库导入失败：{e}")
            self.set_feedback_text("导入失败，请检查题库格式是否为标准 .docx。")
            self.animate_feedback()

            fail_msg = f"导入失败：{e}\n请检查文件是否为可读取的 .docx 题库。"
            self._show_result_dialog("题库导入失败", fail_msg, success=False)

    def on_delete_bank(self):
        if not self._ask_delete_bank():
            self.set_status("已取消删除题库。")
            return

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
        self._refresh_wrong_book_cache()
        self._refresh_remove_wrong_button()

    def on_overview_bank(self):
        qs = load_questions_from_file()
        if not qs:
            self.set_status("当前题库为空，请先导入 Word 题库。")
            self.set_feedback_text("题库总览：当前没有可用题目。")
            self.animate_feedback()
            return

        dlg = QuestionOverviewDialog(self, qs, self.favorite_ids, self.app_icon)
        dlg.exec()
        self.set_status("题库总览窗口已关闭，可以继续刷题。")

    def on_show_wrong_overview(self):
        wrong_all = load_wrong_questions()
        if not wrong_all:
            self.set_status("错题本为空，暂无可预览的错题。")
            self.set_feedback_text("错题本为空：先刷几道题，错题会自动加入。")
            self.animate_feedback()
            return

        dlg = WrongOverviewDialog(self, wrong_all, self._toggle_wrong_book_entry, self.app_icon)
        dlg.exec()
        self._refresh_wrong_book_cache()
        self._refresh_remove_wrong_button()
        self.set_status("错题本总览窗口已关闭，可以继续刷题。")

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

        dlg = QuestionOverviewDialog(self, fav_questions, self.favorite_ids, self.app_icon)
        dlg.setWindowTitle("收藏夹 · 已收藏的题目")
        dlg.exec()
        self.set_status("收藏夹窗口已关闭，可以继续刷题。")

    def on_remove_from_wrong_book(self):
        q = self.current_question
        if not q:
            self.set_status("当前没有题目可移除。")
            self.set_feedback_text("需要先开始刷题或在错题本中跳转到某题。")
            self.animate_feedback()
            return

        was_in_book = q.id in self.wrong_book_map
        in_book = self._toggle_wrong_book_entry(q)
        if was_in_book and not in_book:
            q.wrong_count = 0
            self.set_status(f"已将题号 {q.id} 移出错题本。")
            self.set_feedback_text("该题已不再计入错题本。")
        elif not was_in_book and in_book:
            self.set_status(f"已重新将题号 {q.id} 放回错题本。")
            self.set_feedback_text("已恢复到错题本，可继续复习。")
        else:
            self.set_status("错题本状态未变动。")
            self.set_feedback_text("只有存在于错题本的题目才可以切换状态。")
        self.animate_feedback()
        if self.current_question:
            total = len(self.current_questions)
            idx = self.current_index + 1
            self.set_progress(
                f"第 {idx} / {total} 题  [{qtype_label(q.q_type)}]  (题号: {q.id})"
            )
        self._refresh_remove_wrong_button()

    def on_refresh_stats(self):
        reply_reset = self._ask_refresh_stats()

        if reply_reset:
            stats = reset_stats()
            status = "统计已重置为初始状态。"
        else:
            stats = load_stats()
            status = "已刷新总体统计。"

        # 更新“总体统计”区域
        self._apply_stats_to_labels(stats)
        self.animate_stats()

        # 右侧反馈区展示更详细的刷新结果
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
                lines.append(
                    f"- {qtype_label(qtype)}：{corr}/{tot}，正确率 {format_rate(corr, tot)}"
                )

        self.set_feedback_text("\n".join(lines))
        self.set_status(status)
        self.animate_feedback()

    def _ask_refresh_stats(self) -> bool:
        """自定义弹窗询问是否重置统计，不再播放提示音。"""

        dialog = QDialog(self)
        dialog.setWindowTitle("刷新统计")
        dialog.setWindowIcon(self.app_icon)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        title = QLabel("刷新统计数据")
        title.setObjectName("dialogTitle")
        desc = QLabel("是否将统计重置为初始值？选择“否”则仅重新读取当前统计数据。")
        desc.setWordWrap(True)
        desc.setObjectName("dialogDesc")

        layout.addWidget(title)
        layout.addWidget(desc)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_reset = QPushButton("重置")
        btn_reload = QPushButton("仅刷新")
        btn_row.addWidget(btn_reload)
        btn_row.addWidget(btn_reset)
        layout.addLayout(btn_row)

        dialog.setStyleSheet(
            """
            QDialog {
                background-color: #f3f6fb;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
            }
            #dialogTitle {
                font-size: 16px;
                font-weight: 700;
                color: #1f2937;
            }
            #dialogDesc {
                font-size: 13px;
                color: #475569;
            }
            QDialog QPushButton {
                padding: 8px 16px;
                border-radius: 8px;
                border: 1px solid #2c3e50;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #334155, stop:1 #1f2937);
                color: #e2e8f0;
                min-width: 92px;
                font-weight: 700;
            }
            QDialog QPushButton:hover {
                background-color: #1f2937;
                border-color: #1f2937;
            }
            QDialog QPushButton:pressed {
                background-color: #0f172a;
            }
            """
        )

        chosen_reset = False

        def _choose_reset():
            nonlocal chosen_reset
            chosen_reset = True
            dialog.accept()

        def _choose_reload():
            dialog.accept()

        btn_reset.clicked.connect(_choose_reset)
        btn_reload.clicked.connect(_choose_reload)

        dialog.exec()
        return chosen_reset

    def _ask_delete_bank(self) -> bool:
        """删除题库前的确认弹窗，美观且无提示音。"""

        dialog = QDialog(self)
        dialog.setWindowTitle("确认删除题库")
        dialog.setWindowIcon(self.app_icon)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        accent_bar = QFrame(dialog)
        accent_bar.setObjectName("dialogAccent")
        accent_bar.setFixedHeight(4)

        title = QLabel("删除当前题库？")
        title.setObjectName("dialogTitle")
        desc = QLabel("删除后将同时清空错题本并重置统计，操作不可撤销。")
        desc.setWordWrap(True)
        desc.setObjectName("dialogDesc")

        layout.addWidget(accent_bar)
        layout.addWidget(title)
        layout.addWidget(desc)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("取消")
        btn_confirm = QPushButton("确认删除")
        btn_confirm.setObjectName("dangerBtn")
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_confirm)
        layout.addLayout(btn_row)

        dialog.setStyleSheet(
            """
            QDialog {
                background-color: #f7f1ed;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
            }
            #dialogTitle {
                font-size: 16px;
                font-weight: 700;
                color: #7f1d1d;
            }
            #dialogDesc {
                font-size: 13px;
                color: #5b2020;
            }
            QDialog QPushButton {
                padding: 8px 16px;
                border-radius: 8px;
                border: 1px solid #2c3e50;
                background: #ffffff;
                min-width: 92px;
                font-weight: 700;
            }
            QDialog QPushButton:hover {
                background-color: #e2e8f0;
                border-color: #1f2937;
            }
            QPushButton#dangerBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ef4444, stop:1 #b91c1c);
                color: #f8fafc;
                border-color: #991b1b;
            }
            QPushButton#dangerBtn:hover {
                background-color: #b91c1c;
            }
            QFrame#dialogAccent {
                background-color: #dc2626;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }
            """
        )

        confirmed = False

        def _confirm_delete():
            nonlocal confirmed
            confirmed = True
            dialog.accept()

        btn_cancel.clicked.connect(dialog.reject)
        btn_confirm.clicked.connect(_confirm_delete)

        dialog.exec()
        return confirmed

    def _show_result_dialog(self, title: str, message: str, success: bool = True):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setWindowIcon(self.app_icon)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 12, 20, 16)
        layout.setSpacing(12)

        accent_bar = QFrame(dialog)
        accent_bar.setObjectName("dialogAccent")
        accent_bar.setFixedHeight(4)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("dialogTitle")
        desc_lbl = QLabel(message)
        desc_lbl.setObjectName("dialogDesc")
        desc_lbl.setWordWrap(True)

        layout.addWidget(accent_bar)
        layout.addWidget(title_lbl)
        layout.addWidget(desc_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton("好的")
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        accent_color = "#16a34a" if success else "#dc2626"
        title_color = "#166534" if success else "#b91c1c"

        dialog.setStyleSheet(
            f"""
            QDialog {{
                background-color: #f3f6fb;
                border: 1px solid #cbd5e1;
                border-radius: 12px;
            }}
            #dialogTitle {{
                font-size: 16px;
                font-weight: 700;
                color: {title_color};
            }}
            #dialogDesc {{
                font-size: 13px;
                color: #334155;
            }}
            QDialog QPushButton {{
                padding: 8px 16px;
                border-radius: 8px;
                border: 1px solid #1f2937;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #334155, stop:1 #1f2937);
                color: #e2e8f0;
                min-width: 92px;
                font-weight: 700;
            }}
            QDialog QPushButton:hover {{
                background-color: #1f2937;
                border-color: #1f2937;
            }}
            QDialog QPushButton:pressed {{
                background-color: #0f172a;
            }}
            QFrame#dialogAccent {{
                background-color: {accent_color};
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }}
            """
        )

        btn_ok.clicked.connect(dialog.accept)
        dialog.exec()

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
            self.mode = None
            self.current_questions = []
            self.current_index = -1
            self.current_question = None
            self.index_status.clear()
            self.user_answers.clear()
            self.clear_options()
            self.show_short_answer(False)
            self.btn_submit.setText("提交答案")
            self.btn_submit.setEnabled(False)
            self._refresh_answer_card()
            self._refresh_favorite_star()
            self._refresh_remove_wrong_button()
            self.animate_feedback()
            return

        n = int(self.count_spin.value())
        if n > len(wrong_all):
            n = len(wrong_all)
        questions = random.sample(wrong_all, k=n)
        self._begin_quiz(questions, mode="wrong")

    def _begin_quiz(self, questions: List[Question], mode: str):
        self.mode = mode
        self._refresh_wrong_book_cache()
        self.current_questions = list(questions)
        for q in self.current_questions:
            cached = self.wrong_book_map.get(q.id)
            if cached:
                q.wrong_count = getattr(cached, "wrong_count", 0)
        random.shuffle(self.current_questions)
        self.current_index = 0 if self.current_questions else -1
        self.current_question = (
            self.current_questions[0] if self.current_questions else None
        )

        self.per_type_total.clear()
        self.per_type_correct.clear()
        self.wrong_in_session.clear()
        self.waiting_answer = True
        self.current_option_value = ""
        self.short_answer_edit.clear()

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
            self.btn_submit.setText("提交答案")
            self.btn_submit.setEnabled(False)
            self._refresh_favorite_star()
            self._refresh_remove_wrong_button()
            self._refresh_answer_card()
            return

        q = self.current_question
        total = len(self.current_questions)
        idx = self.current_index + 1

        wrong_count = self._get_wrong_count(q)
        extra = f" · 错题次数：{wrong_count}" if wrong_count > 0 else ""
        self.set_progress(
            f"第 {idx} / {total} 题  [{qtype_label(q.q_type)}]  (题号: {q.id}){extra}"
        )
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
                    btn.setStyleSheet("font-size: 16px; padding: 6px 4px; font-weight: 500;")
                    btn.toggled.connect(self._make_option_handler(label))
                    self.options_layout.addWidget(btn)
                    self.option_buttons.append(btn)
                saved = (
                    self.user_answers[self.current_index]
                    if self.current_index < len(self.user_answers)
                    else ""
                )
                if saved:
                    self.current_option_value = saved
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
                btn.setStyleSheet("font-size: 17px; padding: 6px 4px; font-weight: 500;")
                btn.toggled.connect(self._make_option_handler(txt))
                self.options_layout.addWidget(btn)
                self.option_buttons.append(btn)
            saved = (
                self.user_answers[self.current_index]
                if self.current_index < len(self.user_answers)
                else ""
            )
            if saved:
                self.current_option_value = saved
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

        self.animate_question()
        self._update_answer_summary()
        self._refresh_answer_card()
        self._refresh_favorite_star()
        self._refresh_remove_wrong_button()

    def _make_option_handler(self, value: str):
        def handler(checked: bool):
            if checked:
                self.current_option_value = value
                if 0 <= self.current_index < len(self.user_answers):
                    self.user_answers[self.current_index] = value
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
            self.set_status("本题已判分，请使用“上一题 / 下一题”或左侧答题卡继续。")

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
            self._save_wrong_question_immediately(q)

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
        self.btn_submit.setText("已判分")

    def _goto_next_question(self):
        if not self.current_questions:
            return

        self._cache_current_answer()

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
            self.btn_submit.setText("已判分")
            self.btn_submit.setEnabled(False)
            self._show_existing_feedback()

        self._refresh_answer_card()
        self._update_status_for_current_question()

    def _goto_prev_question(self):
        if not self.current_questions:
            return
        if self.current_index <= 0:
            return

        self._cache_current_answer()

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
            self.btn_submit.setText("已判分")
            self.btn_submit.setEnabled(False)
            self._show_existing_feedback()

        self._refresh_answer_card()
        self._update_status_for_current_question()

    def _goto_question_idx(self, idx: int):
        if not self.current_questions:
            return
        if idx < 0 or idx >= len(self.current_questions):
            return

        self._cache_current_answer()

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
            self.btn_submit.setText("已判分")
            self.btn_submit.setEnabled(False)
            self._show_existing_feedback()

        self._refresh_answer_card()
        self._update_status_for_current_question()

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

        answered = sum(self.per_type_total.values())
        correct = sum(self.per_type_correct.values())
        wrong = answered - correct
        total_questions = len(self.current_questions)
        unanswered = max(total_questions - answered, 0)

        if self.mode in {"normal", "wrong"}:
            existing = load_wrong_questions()
            by_id = {q.id: q for q in existing}
            for q in self.wrong_in_session.values():
                prev = by_id.get(q.id)
                prev_count = getattr(prev, "wrong_count", 0) if prev else 0
                q.wrong_count = max(prev_count, getattr(q, "wrong_count", 0))
                by_id[q.id] = q
            save_wrong_questions(list(by_id.values()))
            wrong_msg = f"本轮记录错题 {len(self.wrong_in_session)} 次，错题本总数：{len(by_id)}。"
        else:
            wrong_msg = ""

        lines = [
            "📊 本轮刷题结束！",
            "",
            f"题目总数：{total_questions}",
            f"已答题：{answered}",
            f"答对数：{correct}",
            f"答错数：{wrong}",
            f"未作答：{unanswered}",
            f"本轮正确率：{format_rate(correct, answered)}",
        ]
        if wrong_msg:
            lines.append("")
            lines.append(wrong_msg)

        self.set_feedback_text("\n".join(lines))
        self.set_status("本轮已结束，可以重新配置题型和题量再来一轮。")
        self.set_progress("当前未在刷题。")
        self.set_question_text("本轮结果已在右侧显示，你可以看一眼整体情况。")
        self.animate_feedback()

        self.clear_options()
        self.show_short_answer(False)
        self.short_answer_edit.clear()
        self.options_box.setTitle("作答区域")

        self._refresh_wrong_book_cache()

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
        self._refresh_remove_wrong_button()


def main():
    app = QApplication(sys.argv)
    base_font = QFont("Microsoft YaHei", 12)
    app.setFont(base_font)

    win = QuizWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
