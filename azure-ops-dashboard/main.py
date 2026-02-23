"""Step10: Azure Env Diagrammer — tkinter GUIアプリ

Azure環境（既存リソース）を読み取り、
Draw.io（diagrams.net）で開ける .drawio 図を生成するGUI。

構成:
  Main Thread   → tkinter メインループ
  Worker Thread → az graph query → .drawio 生成（UIをブロックしない）

操作フロー:
  入力 → Collect → Review（Proceed/Cancel） → Generate → Preview → Open
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import threading
import time
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from collector import (
    Node,
    Edge,
    cell_id_for_azure_id,
    collect_advisor,
    collect_cost,
    collect_inventory,
    collect_network,
    collect_security,
    collect_diagram_view,
    list_resource_groups,
    list_subscriptions,
    preflight_check,
    type_summary,
)
from drawio_writer import build_drawio_xml, now_stamp

from app_paths import (
    ensure_user_dirs, load_all_settings, load_setting, save_all_settings,
    save_setting, saved_instructions_path, settings_path, user_templates_dir,
)
from gui_helpers import (
    WINDOW_TITLE, WINDOW_WIDTH, WINDOW_HEIGHT,
    WINDOW_BG, TEXT_FG, INPUT_BG, ACCENT_COLOR,
    SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR,
    FONT_FAMILY, FONT_SIZE,
    write_text, write_json, open_native,
    cached_drawio_path, cached_vscode_path,
    export_drawio_svg, _subprocess_no_window,
)
from i18n import t, set_language, get_language, on_language_changed, load_saved_language


# ============================================================
# GUI
# ============================================================

class App:
    """Azure Env Diagrammer GUIアプリ。

    レイアウト（上から）:
      1. タイトル
      2. 入力フォーム（Sub/RG/View/Limit）+ Refresh
      3. ボタン行（Collect / Open .drawio）
      4. ログ / レビュー / プレビューエリア
      5. ステータスバー（プログレス + ステップ + 経過時間）
    """

    def __init__(self) -> None:
        # 起動時に保存済み言語を復元
        load_saved_language()

        self._root = tk.Tk()
        self._root.title(WINDOW_TITLE)
        self._root.configure(bg=WINDOW_BG)
        self._root.minsize(600, 500)

        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = (sw - WINDOW_WIDTH) // 2
        y = (sh - WINDOW_HEIGHT) // 2
        self._root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")

        # 状態
        self._working = False
        self._cancel_event = threading.Event()
        self._preflight_ok = False  # preflight完了まではCollect不可
        self._activity_started_at: float | None = None
        self._elapsed_timer_id: str | None = None
        self._last_out_path: Path | None = None
        self._last_diff_path: Path | None = None
        self._subs_cache: list[dict[str, str]] = []
        self._rgs_cache: list[str] = []

        # 利用モデル（起動後に動的取得してUIに反映）
        self._models_cache: list[str] = []

        # レビュー待ち用
        self._review_event = threading.Event()
        self._review_proceed = False
        self._pending_nodes: list[Node] = []
        self._pending_meta: dict[str, Any] = {}

        self._setup_styles()
        self._setup_widgets()
        self._setup_keybindings()

        # 保存済み設定を復元
        self._restore_all_settings()

        # 起動時に事前チェック + Sub候補ロード（非同期）
        threading.Thread(target=self._bg_preflight, daemon=True).start()

        # 起動時に利用可能モデル一覧を取得（非同期）
        threading.Thread(target=self._bg_load_models, daemon=True).start()

        # ウィンドウを前面に表示（起動直後に背面に隠れる問題の対策）
        self._root.after(100, self._bring_to_front)

    # ------------------------------------------------------------------ #
    # ttk スタイル
    # ------------------------------------------------------------------ #

    def _setup_styles(self) -> None:
        style = ttk.Style(self._root)
        style.theme_use("default")
        style.configure("TProgressbar", troughcolor=INPUT_BG, background=ACCENT_COLOR, thickness=8)
        style.configure("Dark.TCombobox",
                         fieldbackground=INPUT_BG, background=INPUT_BG,
                         foreground=TEXT_FG, arrowcolor=TEXT_FG)

    # ------------------------------------------------------------------ #
    # ウィジェット配置
    # ------------------------------------------------------------------ #

    def _setup_widgets(self) -> None:

        # --- タイトル ---
        self._title_label = tk.Label(
            self._root, text=t("app.title"),
            bg=WINDOW_BG, fg=ACCENT_COLOR,
            font=(FONT_FAMILY, 16, "bold"),
        )
        self._title_label.pack(pady=(12, 2))

        self._subtitle_label = tk.Label(
            self._root,
            text=t("app.subtitle"),
            bg=WINDOW_BG, fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
        )
        self._subtitle_label.pack(pady=(0, 8))

        # --- 入力フォーム ---
        form = tk.Frame(self._root, bg=WINDOW_BG)
        form.pack(fill=tk.X, padx=16)
        form.columnconfigure(1, weight=1)

        # --- Row 0: Language ---
        self._lang_label = tk.Label(form, text=t("label.language"), bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), anchor="e")
        self._lang_label.grid(row=0, column=0, sticky="e", padx=(0, 6), pady=3)
        lang_frame = tk.Frame(form, bg=WINDOW_BG)
        lang_frame.grid(row=0, column=1, sticky="w", pady=3)
        self._lang_var = tk.StringVar(value=get_language())
        for val, label in [("ja", "日本語"), ("en", "English")]:
            tk.Radiobutton(lang_frame, text=label, variable=self._lang_var, value=val,
                           bg=WINDOW_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
                           activebackground=WINDOW_BG, activeforeground=TEXT_FG,
                           font=(FONT_FAMILY, FONT_SIZE - 1),
                           command=self._on_language_changed,
                           ).pack(side=tk.LEFT, padx=(0, 10))

        # --- Row 0: Model (right side) ---
        self._model_var = tk.StringVar(value="")
        self._model_label = tk.Label(
            form, text=t("label.model"), bg=WINDOW_BG, fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE), anchor="e",
        )
        self._model_label.grid(row=0, column=2, sticky="e", padx=(12, 6), pady=3)
        self._model_combo = ttk.Combobox(
            form, textvariable=self._model_var, state="disabled",
            values=[t("hint.loading_models")], width=24,
            font=(FONT_FAMILY, FONT_SIZE - 1),
        )
        self._model_combo.grid(row=0, column=3, sticky="w", pady=3, ipady=2)

        # --- Row 1: View ---
        self._view_var = tk.StringVar(value="inventory")
        self._view_label = tk.Label(form, text=t("label.view"), bg=WINDOW_BG, fg=ACCENT_COLOR,
                 font=(FONT_FAMILY, FONT_SIZE, "bold"), anchor="e")
        self._view_label.grid(row=1, column=0, sticky="e", padx=(0, 6), pady=3)
        self._view_combo = ttk.Combobox(form, textvariable=self._view_var, state="readonly",
                                         values=["inventory", "network", "security-report", "cost-report"],
                                         font=(FONT_FAMILY, FONT_SIZE))
        self._view_combo.grid(row=1, column=1, sticky="ew", pady=3, ipady=2)
        self._view_combo.bind("<<ComboboxSelected>>", self._on_view_changed)

        # View 説明ラベル
        self._view_desc_var = tk.StringVar(value=t("view.inventory"))
        tk.Label(form, textvariable=self._view_desc_var, bg=WINDOW_BG, fg="#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2)).grid(row=1, column=2, padx=(4, 0))

        # --- Row 2: Subscription ---
        self._sub_var = tk.StringVar()
        self._sub_label = tk.Label(form, text=t("label.subscription"), bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), anchor="e")
        self._sub_label.grid(row=2, column=0, sticky="e", padx=(0, 6), pady=3)
        self._sub_combo = ttk.Combobox(form, textvariable=self._sub_var, state="normal",
                                        font=(FONT_FAMILY, FONT_SIZE))
        self._sub_combo.grid(row=2, column=1, sticky="ew", pady=3, ipady=2)
        self._sub_combo.bind("<<ComboboxSelected>>", self._on_sub_selected)
        self._sub_hint = tk.Label(form, text=t("hint.optional"), bg=WINDOW_BG, fg="#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2))
        self._sub_hint.grid(row=2, column=2, padx=(4, 0))

        # --- Row 3: Resource Group ---
        self._rg_var = tk.StringVar()
        self._rg_label = tk.Label(form, text=t("label.resource_group"), bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), anchor="e")
        self._rg_label.grid(row=3, column=0, sticky="e", padx=(0, 6), pady=3)
        self._rg_combo = ttk.Combobox(form, textvariable=self._rg_var, state="normal",
                                       font=(FONT_FAMILY, FONT_SIZE))
        self._rg_combo.grid(row=3, column=1, sticky="ew", pady=3, ipady=2)
        self._rg_hint = tk.Label(form, text=t("hint.recommended"), bg=WINDOW_BG, fg="#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2))
        self._rg_hint.grid(row=3, column=2, padx=(4, 0))

        # --- Row 4: Max Nodes ---
        self._limit_var = tk.StringVar(value="300")
        self._limit_label = tk.Label(form, text=t("label.max_nodes"), bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), anchor="e")
        self._limit_label.grid(row=4, column=0, sticky="e", padx=(0, 6), pady=3)
        self._limit_entry = tk.Entry(form, textvariable=self._limit_var,
                 bg=INPUT_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE),
                 insertbackground=TEXT_FG, relief=tk.FLAT, borderwidth=0)
        self._limit_entry.grid(row=4, column=1, sticky="ew", pady=3, ipady=3)
        self._limit_hint = tk.Label(form, text=t("hint.default_300"), bg=WINDOW_BG, fg="#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2))
        self._limit_hint.grid(row=4, column=2, padx=(4, 0))

        # --- Row 5: Output Folder ---
        self._output_dir_var = tk.StringVar(value=str(Path.home() / "Documents"))
        self._outdir_label = tk.Label(form, text=t("label.output_dir"), bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), anchor="e")
        self._outdir_label.grid(row=5, column=0, sticky="e", padx=(0, 6), pady=3)
        outdir_frame = tk.Frame(form, bg=WINDOW_BG)
        outdir_frame.grid(row=5, column=1, sticky="ew", pady=3)
        outdir_frame.columnconfigure(0, weight=1)
        tk.Entry(outdir_frame, textvariable=self._output_dir_var,
                 bg=INPUT_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE),
                 insertbackground=TEXT_FG, relief=tk.FLAT, borderwidth=0
                 ).grid(row=0, column=0, sticky="ew", ipady=3)
        tk.Button(outdir_frame, text="...",
                  command=self._on_browse_output_dir,
                  bg="#3C3C3C", fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 1),
                  relief=tk.FLAT, padx=8, cursor="hand2",
                  ).grid(row=0, column=1, padx=(4, 0))
        self._open_dir_btn = tk.Button(form, text="📂",
                  command=self._on_open_output_dir,
                  bg="#3C3C3C", fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 1),
                  relief=tk.FLAT, padx=6, cursor="hand2")
        self._open_dir_btn.grid(row=5, column=2, padx=(4, 0))

        # --- Row 6: Open App ---
        self._open_app_var = tk.StringVar(value="auto")
        self._openwith_label = tk.Label(form, text=t("label.open_with"), bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), anchor="e")
        self._openwith_label.grid(row=6, column=0, sticky="e", padx=(0, 6), pady=3)
        app_frame = tk.Frame(form, bg=WINDOW_BG)
        app_frame.grid(row=6, column=1, sticky="ew", pady=3)
        for val, label in [("auto", "Auto"), ("drawio", "Draw.io"), ("vscode", "VS Code"), ("os", "OS default")]:
            tk.Radiobutton(app_frame, text=label, variable=self._open_app_var, value=val,
                           bg=WINDOW_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
                           activebackground=WINDOW_BG, activeforeground=TEXT_FG,
                           font=(FONT_FAMILY, FONT_SIZE - 1)
                           ).pack(side=tk.LEFT, padx=(0, 10))
        # Draw.io 検出状態表示
        drawio_path = cached_drawio_path()
        hint_drawio = t("hint.drawio_detected") if drawio_path else t("hint.drawio_not_found")
        self._drawio_hint_label = tk.Label(form, text=hint_drawio, bg=WINDOW_BG,
                 fg=SUCCESS_COLOR if drawio_path else "#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2))
        self._drawio_hint_label.grid(row=6, column=2, padx=(4, 0))

        # ============================================================
        # レポート設定パネル（レポート系View選択時のみ表示）
        # ============================================================
        self._report_panel = tk.Frame(self._root, bg="#252526", relief=tk.GROOVE, borderwidth=1)
        # pack は _on_view_changed で

        # --- ヘッダー行（常に表示 / クリックで本体を開閉） ---
        self._report_header = tk.Frame(self._report_panel, bg="#252526")
        self._report_header.pack(fill=tk.X, padx=0, pady=0)

        self._report_collapsed = True  # 初期は折りたたみ

        self._toggle_btn = tk.Label(
            self._report_header, text="▶", bg="#252526", fg=ACCENT_COLOR,
            font=(FONT_FAMILY, FONT_SIZE - 1, "bold"), cursor="hand2",
        )
        self._toggle_btn.pack(side=tk.LEFT, padx=(10, 2), pady=(4, 2))
        self._toggle_btn.bind("<Button-1>", lambda _: self._toggle_report_body())

        # --- Template 選択行（ヘッダー内） ---
        tmpl_row = tk.Frame(self._report_header, bg="#252526")
        tmpl_row.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=(4, 2))

        tk.Label(tmpl_row, text=t("label.template"), bg="#252526", fg=ACCENT_COLOR,
                 font=(FONT_FAMILY, FONT_SIZE - 1, "bold")).pack(side=tk.LEFT)
        self._template_var = tk.StringVar(value="Standard")
        self._template_combo = ttk.Combobox(tmpl_row, textvariable=self._template_var,
                                             state="readonly", width=20,
                                             font=(FONT_FAMILY, FONT_SIZE - 1))
        self._template_combo.pack(side=tk.LEFT, padx=(6, 0))
        self._template_combo.bind("<<ComboboxSelected>>", self._on_template_selected)

        self._template_desc_var = tk.StringVar(value="")
        tk.Label(tmpl_row, textvariable=self._template_desc_var,
                 bg="#252526", fg="#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2)).pack(side=tk.LEFT, padx=(8, 0))

        self._save_tmpl_btn = tk.Button(tmpl_row, text=t("btn.save_template"),
                  command=self._on_save_template,
                  bg="#3C3C3C", fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 2),
                  relief=tk.FLAT, padx=6, cursor="hand2")
        self._save_tmpl_btn.pack(side=tk.RIGHT)

        self._import_tmpl_btn = tk.Button(tmpl_row, text=t("btn.import_template"),
                  command=self._on_import_template,
                  bg="#3C3C3C", fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 2),
                  relief=tk.FLAT, padx=6, cursor="hand2")
        self._import_tmpl_btn.pack(side=tk.RIGHT, padx=(0, 4))

        # --- 折りたたみ本体（スクロール対応） ---
        self._report_body_outer = tk.Frame(self._report_panel, bg="#252526")
        # 初期は折りたたみなので pack しない

        self._report_canvas = tk.Canvas(
            self._report_body_outer, bg="#252526", highlightthickness=0,
            height=140,  # 最大表示高さ
        )
        self._report_scrollbar = tk.Scrollbar(
            self._report_body_outer, orient="vertical",
            command=self._report_canvas.yview,
        )
        self._report_canvas.configure(yscrollcommand=self._report_scrollbar.set)
        self._report_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._report_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._report_body = tk.Frame(self._report_canvas, bg="#252526")
        self._report_canvas_window = self._report_canvas.create_window(
            (0, 0), window=self._report_body, anchor="nw",
        )

        def _on_report_body_configure(_e: tk.Event) -> None:
            self._report_canvas.configure(scrollregion=self._report_canvas.bbox("all"))
            # 内容幅をキャンバス幅に合わせる
            self._report_canvas.itemconfigure(self._report_canvas_window, width=self._report_canvas.winfo_width())

        self._report_body.bind("<Configure>", _on_report_body_configure)
        self._report_canvas.bind("<Configure>", lambda e: self._report_canvas.itemconfigure(
            self._report_canvas_window, width=e.width))

        # マウスホイールでスクロール
        def _on_mousewheel(event: tk.Event) -> None:
            self._report_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel_recursive(widget: tk.Widget) -> None:
            """widget とその全子孫に MouseWheel バインドを適用。"""
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_mousewheel_recursive(child)

        self._report_canvas.bind("<MouseWheel>", _on_mousewheel)
        self._report_body.bind("<MouseWheel>", _on_mousewheel)
        # 初期子ウィジェットにもバインド（動的追加分は _rebuild_section_checks で対応）
        self._bind_report_mousewheel = _bind_mousewheel_recursive

        # --- セクションチェックボックス（2列グリッド） ---
        self._sections_frame = tk.Frame(self._report_body, bg="#252526")
        self._sections_frame.pack(fill=tk.X, padx=10, pady=(2, 2))
        self._section_vars: dict[str, tk.BooleanVar] = {}
        self._section_widgets: list[tk.Checkbutton] = []

        # --- カスタム指示欄（保存済み指示チェック + 自由入力） ---
        instr_frame = tk.Frame(self._report_body, bg="#252526")
        instr_frame.pack(fill=tk.X, padx=10, pady=(2, 2))

        self._instr_label = tk.Label(instr_frame, text=t("label.extra_instructions"), bg="#252526", fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE - 1, "bold"), anchor="nw")
        self._instr_label.pack(anchor="w")

        # 保存済み指示チェックボックス行
        self._saved_instr_frame = tk.Frame(instr_frame, bg="#252526")
        self._saved_instr_frame.pack(fill=tk.X, pady=(2, 2))
        self._saved_instr_vars: list[tuple[tk.BooleanVar, str]] = []
        self._saved_instr_widgets: list[tk.Checkbutton] = []

        # 自由入力欄
        free_row = tk.Frame(instr_frame, bg="#252526")
        free_row.pack(fill=tk.X, pady=(2, 2))
        free_row.columnconfigure(1, weight=1)
        self._free_input_label = tk.Label(free_row, text=t("label.free_input"), bg="#252526", fg="#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2), anchor="nw")
        self._free_input_label.grid(row=0, column=0, sticky="nw")
        self._custom_instruction = tk.Text(free_row, height=2,
                 bg=INPUT_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 1),
                 insertbackground=TEXT_FG, relief=tk.FLAT, borderwidth=0,
                 wrap=tk.WORD)
        self._custom_instruction.grid(row=0, column=1, sticky="ew", padx=(6, 0), ipady=2)

        free_btn_row = tk.Frame(free_row, bg="#252526")
        free_btn_row.grid(row=0, column=2, padx=(4, 0), sticky="n")
        self._save_instr_btn = tk.Button(free_btn_row, text=t("btn.save_instruction"),
                  command=self._on_save_instruction,
                  bg="#3C3C3C", fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 2),
                  relief=tk.FLAT, padx=4, cursor="hand2")
        self._save_instr_btn.pack(pady=(0, 2))
        self._del_instr_btn = tk.Button(free_btn_row, text=t("btn.delete_instruction"),
                  command=self._on_delete_instruction,
                  bg="#3C3C3C", fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 2),
                  relief=tk.FLAT, padx=4, cursor="hand2")
        self._del_instr_btn.pack()

        # --- 出力形式 + 自動オープン ---
        export_row = tk.Frame(self._report_body, bg="#252526")
        export_row.pack(fill=tk.X, padx=10, pady=(2, 6))

        self._export_label = tk.Label(export_row, text=t("label.export_format"), bg="#252526", fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE - 1))
        self._export_label.pack(side=tk.LEFT)
        self._export_md_var = tk.BooleanVar(value=True)
        tk.Checkbutton(export_row, text="Markdown", variable=self._export_md_var,
                       bg="#252526", fg=TEXT_FG, selectcolor=INPUT_BG,
                       activebackground="#252526", activeforeground=TEXT_FG,
                       font=(FONT_FAMILY, FONT_SIZE - 2)).pack(side=tk.LEFT, padx=(4, 0))
        self._export_docx_var = tk.BooleanVar(value=False)
        tk.Checkbutton(export_row, text="Word (.docx)", variable=self._export_docx_var,
                       bg="#252526", fg=TEXT_FG, selectcolor=INPUT_BG,
                       activebackground="#252526", activeforeground=TEXT_FG,
                       font=(FONT_FAMILY, FONT_SIZE - 2)).pack(side=tk.LEFT, padx=(4, 0))
        self._export_pdf_var = tk.BooleanVar(value=False)
        tk.Checkbutton(export_row, text="PDF", variable=self._export_pdf_var,
                       bg="#252526", fg=TEXT_FG, selectcolor=INPUT_BG,
                       activebackground="#252526", activeforeground=TEXT_FG,
                       font=(FONT_FAMILY, FONT_SIZE - 2)).pack(side=tk.LEFT, padx=(4, 0))

        # --- SVG エクスポート（drawio ビュー向け、Open App 行の近く） ---
        self._export_svg_var = tk.BooleanVar(value=False)

        # テンプレートキャッシュ
        self._templates_cache: list[dict] = []
        self._current_template: dict | None = None

        # --- ボタン行 ---
        btn_frame = tk.Frame(self._root, bg=WINDOW_BG)
        btn_frame.pack(pady=8)

        self._collect_btn = tk.Button(
            btn_frame, text=t("btn.collect"),
            command=self._on_collect,
            bg=ACCENT_COLOR, fg="white",
            font=(FONT_FAMILY, FONT_SIZE, "bold"),
            relief=tk.FLAT, padx=20, pady=6,
            cursor="hand2",
            activebackground="#005a9e", activeforeground="white",
            state=tk.DISABLED,  # preflight完了まで無効
        )
        self._collect_btn.pack(side=tk.LEFT)

        self._abort_btn = tk.Button(
            btn_frame, text=t("btn.cancel"),
            command=self._on_abort,
            bg=ERROR_COLOR, fg="white",
            font=(FONT_FAMILY, FONT_SIZE, "bold"),
            relief=tk.FLAT, padx=20, pady=6,
            cursor="hand2",
        )
        # 初期非表示 — _set_working(True) で pack される

        self._refresh_btn = tk.Button(
            btn_frame, text=t("btn.refresh"),
            command=self._on_refresh,
            bg="#3C3C3C", fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
        )
        self._refresh_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._open_btn = tk.Button(
            btn_frame, text=t("btn.open_file"),
            command=self._on_open_file,
            bg="#3C3C3C", fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
            state=tk.DISABLED,
        )
        self._open_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._diff_btn = tk.Button(
            btn_frame, text=t("btn.open_diff"),
            command=self._on_open_diff,
            bg="#3C3C3C", fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
            state=tk.DISABLED,
        )
        self._diff_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._copy_btn = tk.Button(
            btn_frame, text=t("btn.copy_log"),
            command=self._on_copy_log,
            bg="#3C3C3C", fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
        )
        self._copy_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._clear_log_btn = tk.Button(
            btn_frame, text=t("btn.clear_log"),
            command=self._on_clear_log,
            bg="#3C3C3C", fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
        )
        self._clear_log_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._login_btn = tk.Button(
            btn_frame, text=t("btn.az_login"),
            command=self._on_az_login,
            bg="#3C3C3C", fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
        )
        self._login_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._sp_login_btn = tk.Button(
            btn_frame, text=t("btn.sp_login"),
            command=self._on_sp_login,
            bg="#3C3C3C", fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
        )
        self._sp_login_btn.pack(side=tk.LEFT, padx=(6, 0))

        # --- auto_open（メインフォーム、図/レポート両方で有効） ---
        self._auto_open_var = tk.BooleanVar(value=True)
        self._auto_open_main_cb = tk.Checkbutton(
            btn_frame, text=t("btn.auto_open"), variable=self._auto_open_var,
            bg=WINDOW_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
            activebackground=WINDOW_BG, activeforeground=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 2))
        self._auto_open_main_cb.pack(side=tk.LEFT, padx=(12, 0))

        # SVG エクスポート チェック（diagram ビュー用、ボタン行に配置）
        self._svg_cb = tk.Checkbutton(
            btn_frame, text="SVG", variable=self._export_svg_var,
            bg=WINDOW_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
            activebackground=WINDOW_BG, activeforeground=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 2))
        self._svg_cb.pack(side=tk.LEFT, padx=(6, 0))

        # --- レビューパネル（初期非表示 / 2行構成） ---
        self._review_frame = tk.Frame(self._root, bg="#303030", relief=tk.RIDGE, borderwidth=1)
        # pack は _show_review で

        # 行1: サマリテキスト
        self._review_text_var = tk.StringVar(value="")
        tk.Label(self._review_frame, textvariable=self._review_text_var,
                 bg="#303030", fg=WARNING_COLOR, anchor="w", justify="left",
                 font=(FONT_FAMILY, FONT_SIZE - 1), wraplength=680
                 ).pack(fill=tk.X, padx=10, pady=(6, 2))

        # 行2: ボタン（左寄せで大きめ）
        review_btn_row = tk.Frame(self._review_frame, bg="#303030")
        review_btn_row.pack(fill=tk.X, padx=10, pady=(2, 6))

        self._proceed_btn = tk.Button(
            review_btn_row, text=t("btn.proceed"),
            command=self._on_proceed,
            bg=SUCCESS_COLOR, fg="#1e1e1e",
            font=(FONT_FAMILY, FONT_SIZE, "bold"),
            relief=tk.FLAT, padx=20, pady=6,
            cursor="hand2",
        )
        self._proceed_btn.pack(side=tk.LEFT)

        self._cancel_btn = tk.Button(
            review_btn_row, text=t("btn.cancel_review"),
            command=self._on_cancel,
            bg=ERROR_COLOR, fg="white",
            font=(FONT_FAMILY, FONT_SIZE),
            relief=tk.FLAT, padx=20, pady=6,
            cursor="hand2",
        )
        self._cancel_btn.pack(side=tk.LEFT, padx=(8, 0))

        # --- ログエリア ---
        self._log_area = scrolledtext.ScrolledText(
            self._root, wrap=tk.WORD, state=tk.DISABLED,
            bg=INPUT_BG, fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            insertbackground=TEXT_FG,
            relief=tk.FLAT, padx=10, pady=8, borderwidth=0,
            height=10,
        )
        self._log_area.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 4))

        self._log_area.tag_configure("info", foreground=TEXT_FG)
        self._log_area.tag_configure("success", foreground=SUCCESS_COLOR)
        self._log_area.tag_configure("warning", foreground=WARNING_COLOR)
        self._log_area.tag_configure("error", foreground=ERROR_COLOR)
        self._log_area.tag_configure("accent", foreground=ACCENT_COLOR)

        # --- Canvas プレビュー（初期非表示） ---
        self._preview_frame = tk.Frame(self._root, bg=WINDOW_BG)
        self._canvas = tk.Canvas(self._preview_frame, bg="#252526", highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        # パン/ズーム
        self._canvas_offset_x = 0.0
        self._canvas_offset_y = 0.0
        self._canvas_scale = 1.0
        self._drag_start: tuple[int, int] | None = None
        self._canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self._canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self._canvas.bind("<MouseWheel>", self._on_canvas_zoom)

        # --- ステータスバー（下部） ---
        status_frame = tk.Frame(self._root, bg="#252526")
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self._progress = ttk.Progressbar(status_frame, mode="indeterminate", length=100, style="TProgressbar")
        self._progress.pack(side=tk.LEFT, padx=(8, 4), pady=5)

        self._step_var = tk.StringVar(value="")
        tk.Label(status_frame, textvariable=self._step_var,
                 bg="#252526", fg=ACCENT_COLOR, anchor="w",
                 font=(FONT_FAMILY, FONT_SIZE - 2)).pack(side=tk.LEFT)

        self._status_var = tk.StringVar(value=t("status.ready"))
        tk.Label(status_frame, textvariable=self._status_var,
                 bg="#252526", fg=TEXT_FG, anchor="w",
                 font=(FONT_FAMILY, FONT_SIZE - 2), padx=8).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._elapsed_var = tk.StringVar(value="")
        tk.Label(status_frame, textvariable=self._elapsed_var,
                 bg="#252526", fg=TEXT_FG, anchor="e",
                 font=(FONT_FAMILY, FONT_SIZE - 2), padx=8).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------ #
    # キーバインド
    # ------------------------------------------------------------------ #

    def _setup_keybindings(self) -> None:
        self._root.bind("<Control-g>", lambda _: self._on_collect())
        self._root.bind("<Control-o>", lambda _: self._on_open_file())
        self._root.bind("<Control-l>", lambda _: self._on_copy_log())

    # ------------------------------------------------------------------ #
    # 設定の保存・復元
    # ------------------------------------------------------------------ #

    def _save_all_settings(self) -> None:
        """全フォーム設定を settings.json に一括保存する。"""
        data = load_all_settings()
        data["output_dir"] = self._output_dir_var.get()
        data["view"] = self._view_var.get()
        data["limit"] = self._limit_var.get()
        data["open_with"] = self._open_app_var.get()
        data["auto_open"] = "1" if self._auto_open_var.get() else "0"
        data["export_md"] = "1" if self._export_md_var.get() else "0"
        data["export_docx"] = "1" if self._export_docx_var.get() else "0"
        data["export_pdf"] = "1" if self._export_pdf_var.get() else "0"
        data["export_svg"] = "1" if self._export_svg_var.get() else "0"
        data["last_template"] = self._template_var.get()
        data["model"] = self._model_var.get()
        save_all_settings(data)

    def _restore_all_settings(self) -> None:
        """settings.json から全フォーム設定を復元する。"""
        # Output Dir
        saved_dir = load_setting("output_dir", "")
        if saved_dir and Path(saved_dir).is_dir():
            self._output_dir_var.set(saved_dir)

        # View
        saved_view = load_setting("view", "")
        if saved_view and saved_view in ("inventory", "network", "security-report", "cost-report"):
            self._view_var.set(saved_view)
            self._on_view_changed()

        # Max Nodes
        saved_limit = load_setting("limit", "")
        if saved_limit:
            self._limit_var.set(saved_limit)

        # Open with
        saved_open_with = load_setting("open_with", "")
        if saved_open_with in ("auto", "drawio", "vscode", "os"):
            self._open_app_var.set(saved_open_with)

        # Auto open
        saved_auto = load_setting("auto_open", "")
        if saved_auto in ("0", "1"):
            self._auto_open_var.set(saved_auto == "1")

        # Export formats
        saved_md = load_setting("export_md", "")
        if saved_md in ("0", "1"):
            self._export_md_var.set(saved_md == "1")
        saved_docx = load_setting("export_docx", "")
        if saved_docx in ("0", "1"):
            self._export_docx_var.set(saved_docx == "1")
        saved_pdf = load_setting("export_pdf", "")
        if saved_pdf in ("0", "1"):
            self._export_pdf_var.set(saved_pdf == "1")
        saved_svg = load_setting("export_svg", "")
        if saved_svg in ("0", "1"):
            self._export_svg_var.set(saved_svg == "1")

        # Model（一覧ロード後に適用するため、ここでは値だけ復元）
        saved_model = load_setting("model", "")
        if saved_model:
            self._model_var.set(saved_model)

    def _bg_load_models(self) -> None:
        """Copilot SDK から利用可能モデル一覧を取得してUIに反映する。"""
        try:
            from ai_reviewer import list_available_model_ids_sync, choose_default_model_id, MODEL

            self._log(t("log.loading_models"), "info")
            model_ids = list_available_model_ids_sync(
                on_status=lambda s: self._log(s, "info"),
                timeout=15,
            )
            model_ids = [m for m in model_ids if isinstance(m, str) and m.strip()]
            if not model_ids:
                # 取得失敗時はフォールバック定数を使用
                self._log(t("log.model_fallback"), "warning")
                model_ids = [MODEL]
            self._models_cache = model_ids

            def _apply() -> None:
                self._model_combo.configure(values=model_ids, state="readonly")

                current = self._model_var.get().strip()
                if current in model_ids:
                    return
                default_model = choose_default_model_id(model_ids)
                self._model_var.set(default_model)

            self._root.after(0, _apply)
        except Exception:
            return

    def _restore_last_template(self) -> None:
        """テンプレート一覧ロード後に前回選択を復元する。"""
        saved_tmpl = load_setting("last_template", "")
        if saved_tmpl:
            values = list(self._template_combo["values"])
            if saved_tmpl in values:
                self._template_var.set(saved_tmpl)
                self._on_template_selected()

    def _bring_to_front(self) -> None:
        """ウィンドウを前面に表示する。"""
        self._root.lift()
        self._root.attributes('-topmost', True)
        self._root.after(300, lambda: self._root.attributes('-topmost', False))
        self._root.focus_force()

    # ------------------------------------------------------------------ #
    # ファイル名ヘルパー
    # ------------------------------------------------------------------ #

    def _sub_display_name(self, sub_id: str | None) -> str | None:
        """サブスクID → 短い表示名（キャッシュから）。"""
        if not sub_id:
            return None
        for s in self._subs_cache:
            if s.get("id") == sub_id:
                name = s.get("name", sub_id)
                # ファイル名安全化: 英数字/ハイフン/アンダースコアのみ
                return re.sub(r"[^\w\-]", "_", name)[:30]
        return sub_id[:8]

    @staticmethod
    def _sanitize_for_filename(s: str) -> str:
        return re.sub(r"[^\w\-]", "_", s)[:30]

    def _make_filename(self, prefix: str, sub_id: str | None, rg: str | None, ext: str) -> str:
        """Sub/RG 情報を含んだファイル名を生成する。"""
        parts = [prefix]
        sub_name = self._sub_display_name(sub_id)
        if sub_name:
            parts.append(sub_name)
        if rg:
            parts.append(self._sanitize_for_filename(rg))
        parts.append(now_stamp())
        return "-".join(parts) + ext

    # ------------------------------------------------------------------ #
    # レポートパネル折りたたみ
    # ------------------------------------------------------------------ #

    def _toggle_report_body(self) -> None:
        """レポート設定パネルの本体を展開/折りたたみ切り替え。"""
        if self._report_collapsed:
            self._report_body_outer.pack(fill=tk.X)
            self._toggle_btn.configure(text="▼")
            self._report_collapsed = False
        else:
            self._report_body_outer.pack_forget()
            self._toggle_btn.configure(text="▶")
            self._report_collapsed = True

    # ------------------------------------------------------------------ #
    # View 切り替え
    # ------------------------------------------------------------------ #

    _VIEW_DESC_KEYS = {
        "inventory": "view.inventory",
        "network": "view.network",
        "security-report": "view.security_report",
        "cost-report": "view.cost_report",
    }

    def _on_view_changed(self, _event: tk.Event | None = None) -> None:
        """View 選択変更時にボタンラベル、説明、フォーム表示を更新。"""
        view = self._view_var.get().strip()
        desc_key = self._VIEW_DESC_KEYS.get(view, "")
        self._view_desc_var.set(t(desc_key) if desc_key else "")

        is_report = view in ("security-report", "cost-report")

        # diff はレポート用。レポート以外のビューでは常に無効化し、パスもクリア。
        if not is_report:
            self._last_diff_path = None
            self._diff_btn.configure(state=tk.DISABLED)
        else:
            # reportビューでは diff が存在する場合のみ有効（言語切替などで再評価される）
            if self._last_diff_path and self._last_diff_path.exists() and not self._working:
                self._diff_btn.configure(state=tk.NORMAL)
            else:
                self._diff_btn.configure(state=tk.DISABLED)

        # ボタンラベル
        if is_report:
            self._collect_btn.configure(text=t("btn.generate_report"))
        else:
            self._collect_btn.configure(text=t("btn.collect"))

        # RG / MaxNodes を動的に有効/無効化
        if is_report:
            self._rg_combo.configure(state="disabled")
            self._rg_label.configure(fg="#555555")
            self._rg_hint.configure(text=t("hint.not_used_report"))
            self._limit_entry.configure(state="disabled")
            self._limit_label.configure(fg="#555555")
            self._limit_hint.configure(text=t("hint.not_used_report"))
        else:
            self._rg_combo.configure(state="normal")
            self._rg_label.configure(fg=TEXT_FG)
            self._rg_hint.configure(text=t("hint.recommended"))
            self._limit_entry.configure(state="normal")
            self._limit_label.configure(fg=TEXT_FG)
            self._limit_hint.configure(text=t("hint.default_300"))

        # テンプレートパネル表示/非表示
        if is_report:
            self._report_panel.pack(fill=tk.X, padx=12, pady=(0, 4),
                                     before=self._log_area)
            report_type = "security" if view == "security-report" else "cost"
            self._load_templates_for_type(report_type)
        else:
            self._report_panel.pack_forget()

    # ------------------------------------------------------------------ #
    # テンプレート管理
    # ------------------------------------------------------------------ #

    def _load_templates_for_type(self, report_type: str) -> None:
        """テンプレート一覧をロードしてComboboxに設定。"""
        from ai_reviewer import list_templates
        templates = list_templates(report_type)
        self._templates_cache = templates
        names = [tmpl.get("template_name", "Unknown") for tmpl in templates]
        self._template_combo.configure(values=names if names else ["(No templates)"])
        if names:
            self._template_var.set(names[0])
            self._on_template_selected()
        else:
            self._current_template = None
            self._clear_section_checks()
        # 保存済み指示もロード
        self._load_saved_instructions()
        # 前回のテンプレート選択を復元
        self._restore_last_template()
        # レポートパネル内の全ウィジェットにマウスホイールバインド
        if hasattr(self, "_bind_report_mousewheel"):
            self._bind_report_mousewheel(self._report_body)

    def _load_saved_instructions(self) -> None:
        """保存済み指示をチェックボックスとしてロード。"""
        # 既存ウィジェットをクリア
        for w in self._saved_instr_widgets:
            w.destroy()
        self._saved_instr_widgets.clear()
        self._saved_instr_vars.clear()

        instr_path = saved_instructions_path()
        if not instr_path.exists():
            return
        try:
            data = json.loads(instr_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        row, col = 0, 0
        lang = get_language()
        for item in data:
            label = item.get(f"label_{lang}", item.get("label", ""))
            instruction = item.get("instruction", "")
            if not label:
                continue
            var = tk.BooleanVar(value=False)
            self._saved_instr_vars.append((var, instruction))
            cb = tk.Checkbutton(self._saved_instr_frame, text=label,
                                variable=var, bg="#252526", fg=TEXT_FG,
                                selectcolor=INPUT_BG, activebackground="#252526",
                                activeforeground=TEXT_FG,
                                font=(FONT_FAMILY, FONT_SIZE - 2),
                                anchor="w")
            cb.grid(row=row, column=col, sticky="w", padx=(0, 12))
            self._saved_instr_widgets.append(cb)
            col += 1
            if col >= 3:
                col = 0
                row += 1
        # 動的生成した指示チェックボックスにマウスホイールバインド
        if hasattr(self, "_bind_report_mousewheel"):
            self._bind_report_mousewheel(self._saved_instr_frame)

    def _on_template_selected(self, _event: tk.Event | None = None) -> None:
        """テンプレート選択時にチェックボックスを更新。"""
        name = self._template_var.get()
        lang = get_language()
        for tmpl in self._templates_cache:
            if tmpl.get("template_name") == name:
                self._current_template = tmpl
                desc = tmpl.get(f"description_{lang}", tmpl.get("description", ""))
                self._template_desc_var.set(desc)
                self._rebuild_section_checks(tmpl)
                return

    def _clear_section_checks(self) -> None:
        for w in self._section_widgets:
            w.destroy()
        self._section_widgets.clear()
        self._section_vars.clear()

    def _rebuild_section_checks(self, template: dict) -> None:
        """テンプレートのsectionsからチェックボックスを再構築。"""
        self._clear_section_checks()
        sections = template.get("sections", {})
        lang = get_language()
        row, col = 0, 0
        for key, sec in sections.items():
            var = tk.BooleanVar(value=sec.get("enabled", True))
            self._section_vars[key] = var
            label = sec.get(f"label_{lang}", sec.get("label", key))
            cb = tk.Checkbutton(self._sections_frame, text=label,
                                variable=var, bg="#252526", fg=TEXT_FG,
                                selectcolor=INPUT_BG, activebackground="#252526",
                                activeforeground=TEXT_FG,
                                font=(FONT_FAMILY, FONT_SIZE - 2),
                                anchor="w")
            cb.grid(row=row, column=col, sticky="w", padx=(0, 16))
            self._section_widgets.append(cb)
            col += 1
            if col >= 3:
                col = 0
                row += 1

    def _get_current_template_with_overrides(self) -> dict | None:
        """現在のテンプレートにチェックボックスの変更を反映した辞書を返す。"""
        if not self._current_template:
            return None
        tmpl = copy.deepcopy(self._current_template)
        sections = tmpl.get("sections", {})
        for key, var in self._section_vars.items():
            if key in sections:
                sections[key]["enabled"] = var.get()
        return tmpl

    def _get_custom_instruction(self) -> str:
        """チェック済みの保存済み指示 + 自由入力テキストを結合して返す。"""
        parts: list[str] = []
        # 保存済み指示（チェック済みのもの）
        for var, instruction in self._saved_instr_vars:
            if var.get():
                parts.append(instruction)
        # 自由入力
        free = self._custom_instruction.get("1.0", tk.END).strip()
        if free:
            parts.append(free)
        return "\n".join(parts)

    def _on_save_instruction(self) -> None:
        """自由入力欄のテキストを保存済み指示に追加する。"""
        text = self._custom_instruction.get("1.0", tk.END).strip()
        if not text:
            return

        # ラベル入力ダイアログ
        label = simpledialog.askstring(
            t("dlg.save_instruction"),
            t("dlg.label_prompt"),
            parent=self._root,
        )
        if not label or not label.strip():
            return
        label = label.strip()

        # JSONに追記（ユーザー領域に保存）
        ensure_user_dirs()
        instr_path = user_templates_dir() / "saved-instructions.json"
        try:
            if instr_path.exists():
                data = json.loads(instr_path.read_text(encoding="utf-8"))
            else:
                # 初回: bundled のプリセットをコピーして追記
                bundled = saved_instructions_path()
                if bundled.exists():
                    data = json.loads(bundled.read_text(encoding="utf-8"))
                else:
                    data = []
        except (json.JSONDecodeError, OSError):
            data = []

        data.append({"label": label, "instruction": text})
        instr_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        # UIリロード
        self._load_saved_instructions()
        self._custom_instruction.delete("1.0", tk.END)
        self._log(t("instr.saved", label=label), "success")

    def _on_delete_instruction(self) -> None:
        """チェック済みの保存済み指示を削除する。"""
        # ユーザー領域のファイルを操作（bundled は変更しない）
        ensure_user_dirs()
        instr_path = user_templates_dir() / "saved-instructions.json"

        # ユーザー領域にまだファイルがなければ bundled からコピー
        if not instr_path.exists():
            bundled = saved_instructions_path()
            if bundled.exists():
                try:
                    data = json.loads(bundled.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    return
            else:
                return
        else:
            try:
                data = json.loads(instr_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return

        # チェック済みの指示テキストを収集
        to_delete: set[str] = set()
        for var, instruction in self._saved_instr_vars:
            if var.get():
                to_delete.add(instruction)

        if not to_delete:
            self._log(t("instr.check_to_delete"), "warning")
            return

        # 確認
        count = len(to_delete)
        if not messagebox.askyesno(t("dlg.delete_instruction"), t("dlg.delete_confirm", count=count)):
            return

        # フィルタして保存
        data = [item for item in data if item.get("instruction", "") not in to_delete]
        instr_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        # UIリロード
        self._load_saved_instructions()
        self._log(t("instr.deleted", count=count), "success")

    def _on_save_template(self) -> None:
        """現在のチェック状態を新しいテンプレートとして保存。"""
        tmpl = self._get_current_template_with_overrides()
        if not tmpl:
            return

        # テンプレート名を入力ダイアログで聞く
        default_name = tmpl.get("template_name", "Custom")
        name = simpledialog.askstring(
            t("dlg.save_template"),
            t("dlg.template_name_prompt"),
            initialvalue=default_name,
            parent=self._root,
        )
        if not name or not name.strip():
            return
        name = name.strip()

        # frozen (PyInstaller) の同梱 templates は読み取り専用になり得るため、ユーザー領域を既定にする
        ensure_user_dirs()
        report_type = tmpl.get("report_type", "custom")
        safe_name = re.sub(r"[^\w\-]", "_", name).lower()
        p = filedialog.asksaveasfilename(
            title=t("dlg.save_template"),
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=str(user_templates_dir()) if user_templates_dir().is_dir() else str(Path.home() / "Documents"),
            initialfile=f"{report_type}-{safe_name}.json",
        )
        if p:
            from ai_reviewer import save_template
            tmpl["template_name"] = name
            # _pathは保存対象から除外
            tmpl.pop("_path", None)
            save_template(p, tmpl)
            self._log(t("instr.template_saved", path=p), "success")
            # リロード
            self._load_templates_for_type(report_type)

    def _on_import_template(self) -> None:
        """外部のテンプレート JSON をユーザー領域にインポート。"""
        src = filedialog.askopenfilename(
            title=t("dlg.import_template"),
            filetypes=[("JSON", "*.json")],
            initialdir=str(Path.home() / "Documents"),
        )
        if not src:
            return
        src_path = Path(src)
        try:
            data = json.loads(src_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            self._log(f"Import error: {e}", "error")
            return
        if not isinstance(data, dict) or "report_type" not in data:
            self._log("Invalid template JSON (missing 'report_type')", "error")
            return

        ensure_user_dirs()
        dest = user_templates_dir() / src_path.name
        # 同名ファイルが既にあれば末尾に番号を付与
        counter = 1
        while dest.exists():
            dest = user_templates_dir() / f"{src_path.stem}_{counter}.json"
            counter += 1
        import shutil
        shutil.copy2(src, dest)
        self._log(t("instr.template_imported", path=str(dest)), "success")
        # リロード
        report_type = data.get("report_type", "security")
        self._load_templates_for_type(report_type)

    # ------------------------------------------------------------------ #
    # 出力フォルダ
    # ------------------------------------------------------------------ #

    def _on_browse_output_dir(self) -> None:
        d = filedialog.askdirectory(
            title=t("dlg.select_output_dir"),
            initialdir=self._output_dir_var.get(),
        )
        if d:
            self._output_dir_var.set(d)

    def _on_open_output_dir(self) -> None:
        d = self._output_dir_var.get()
        if d and Path(d).exists():
            open_native(d)

    # ------------------------------------------------------------------ #
    # ログ / ステータス（スレッドセーフ）
    # ------------------------------------------------------------------ #

    def _log(self, text: str, tag: str = "info") -> None:
        def _do() -> None:
            self._log_area.configure(state=tk.NORMAL)
            self._log_area.insert(tk.END, text + "\n", tag)
            self._log_area.see(tk.END)
            self._log_area.configure(state=tk.DISABLED)
        self._root.after(0, _do)

    def _log_append_delta(self, delta: str) -> None:
        """ストリーミング用: 改行なしでテキストを追記。"""
        def _do() -> None:
            self._log_area.configure(state=tk.NORMAL)
            self._log_area.insert(tk.END, delta, "info")
            self._log_area.see(tk.END)
            self._log_area.configure(state=tk.DISABLED)
        self._root.after(0, _do)

    def _set_status(self, text: str) -> None:
        self._root.after(0, self._status_var.set, text)

    def _set_step(self, text: str) -> None:
        self._root.after(0, self._step_var.set, text)

    def _on_clear_log(self) -> None:
        """ログエリアとCanvasプレビューをクリア。"""
        def _do() -> None:
            self._log_area.configure(state=tk.NORMAL)
            self._log_area.delete("1.0", tk.END)
            self._log_area.configure(state=tk.DISABLED)
            # Canvas プレビューもクリア
            self._canvas.delete("all")
            if self._preview_frame.winfo_ismapped():
                self._preview_frame.pack_forget()
        self._root.after(0, _do)

    # ------------------------------------------------------------------ #
    # 進捗タイマー
    # ------------------------------------------------------------------ #

    def _start_timer(self) -> None:
        self._activity_started_at = time.monotonic()
        self._elapsed_var.set("00:00")
        self._tick_elapsed()

    def _stop_timer(self) -> None:
        if self._elapsed_timer_id is not None:
            try:
                self._root.after_cancel(self._elapsed_timer_id)
            except Exception:
                pass
        self._elapsed_timer_id = None
        self._activity_started_at = None

    def _tick_elapsed(self) -> None:
        if not self._working or self._activity_started_at is None:
            return
        elapsed_s = int(time.monotonic() - self._activity_started_at)
        self._elapsed_var.set(f"{elapsed_s // 60:02d}:{elapsed_s % 60:02d}")
        self._elapsed_timer_id = self._root.after(200, self._tick_elapsed)

    # ------------------------------------------------------------------ #
    # ワーキング状態
    # ------------------------------------------------------------------ #

    def _set_working(self, working: bool) -> None:
        def _do() -> None:
            self._working = working
            if working:
                self._collect_btn.pack_forget()
                self._abort_btn.pack(side=tk.LEFT, before=self._refresh_btn)
                self._refresh_btn.configure(state=tk.DISABLED)
                self._open_btn.configure(state=tk.DISABLED)
                self._diff_btn.configure(state=tk.DISABLED)
                self._progress.start(12)
                self._start_timer()
            else:
                self._abort_btn.pack_forget()
                self._collect_btn.pack(side=tk.LEFT, before=self._refresh_btn)
                self._refresh_btn.configure(state=tk.NORMAL)
                self._progress.stop()
                self._stop_timer()
                self._set_step("")
                self._elapsed_var.set("")
        self._root.after(0, _do)

    def _on_abort(self) -> None:
        """収集中にCancelボタンを押した場合。"""
        self._cancel_event.set()
        self._review_event.set()  # レビュー待ちも解除
        self._log(t("log.cancel_requested"), "warning")
        self._set_status(t("status.cancelling"))
        self._set_working(False)
        self._hide_review()

    # ------------------------------------------------------------------ #
    # 事前チェック + Sub/RG ロード（バックグラウンド）
    # ------------------------------------------------------------------ #

    def _bg_preflight(self) -> None:
        """起動時に az 環境チェック + Subscription 候補取得。"""
        warnings = preflight_check()
        self._preflight_ok = len(warnings) == 0
        for w in warnings:
            self._log(w, "warning")

        if self._preflight_ok:
            self._log(t("log.azure_cli_ok"), "success")
            self._root.after(0, lambda: self._collect_btn.configure(state=tk.NORMAL))
        else:
            self._log(t("log.fix_above"), "error")
            self._root.after(0, lambda: self._collect_btn.configure(state=tk.DISABLED))

        # Sub 候補ロード
        self._log(t("log.loading_subs"), "info")
        subs = list_subscriptions()
        self._subs_cache = subs
        if subs:
            values = [t("hint.all_subscriptions")] + [f"{s['name']}  ({s['id']})" for s in subs]
            self._root.after(0, lambda: self._sub_combo.configure(values=values))
            self._log(t("log.subs_found", count=len(subs)), "success")

            # Sub が1件なら自動選択 + RG自動ロード
            if len(subs) == 1:
                auto_val = values[1]  # 実際のSub（全サブスクではない）
                self._root.after(0, lambda: self._sub_var.set(auto_val))
                self._log(t("log.auto_selected_sub"), "info")
                sub_id = subs[0]["id"]
                self._bg_load_rgs(sub_id)
        else:
            self._log(t("log.subs_failed"), "warning")

    def _on_sub_selected(self, _event: tk.Event | None = None) -> None:
        """Subscription 選択時に RG 候補をロード。"""
        sub_id = self._extract_sub_id()
        if not sub_id:
            # 全サブスク選択時はRGリストをクリア
            self._rgs_cache = []
            self._root.after(0, lambda: self._rg_combo.configure(values=[]))
            self._root.after(0, lambda: self._rg_var.set(""))
            self._log(t("log.all_subs_selected"), "info")
            return
        threading.Thread(target=self._bg_load_rgs, args=(sub_id,), daemon=True).start()

    def _bg_load_rgs(self, sub_id: str) -> None:
        self._log(t("log.loading_rgs", sub=sub_id[:8] + "..."), "info")
        rgs = list_resource_groups(sub_id)
        self._rgs_cache = rgs
        if rgs:
            values = [t("hint.all_rgs")] + rgs
            self._root.after(0, lambda: self._rg_combo.configure(values=values))
            self._log(t("log.rgs_found", count=len(rgs)), "success")
        else:
            self._log(t("log.rgs_failed"), "warning")

    def _on_refresh(self) -> None:
        threading.Thread(target=self._bg_preflight, daemon=True).start()

    def _on_az_login(self) -> None:
        """az login をバックグラウンドで実行し、完了後に Refresh。"""
        def _do_login() -> None:
            self._log(t("log.az_login_running"), "info")
            self._root.after(0, lambda: self._login_btn.configure(state=tk.DISABLED))
            try:
                kwargs: dict = {
                    "capture_output": True, "text": True,
                    "timeout": 120, "encoding": "utf-8", "errors": "replace",
                }
                if sys.platform == "win32":
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                    kwargs["shell"] = True
                    cmd: str | list[str] = "az login"
                else:
                    cmd = ["az", "login"]
                result = subprocess.run(cmd, **kwargs)
                if result.returncode == 0:
                    self._log(t("log.az_login_success"), "success")
                    # Sub/RG をクリア
                    self._root.after(0, lambda: self._sub_var.set(""))
                    self._root.after(0, lambda: self._rg_var.set(""))
                    self._root.after(0, lambda: self._sub_combo.configure(values=[]))
                    self._root.after(0, lambda: self._rg_combo.configure(values=[]))
                    self._bg_preflight()
                else:
                    self._log(t("log.az_login_failed", err=result.stderr[:200]), "error")
            except Exception as e:
                self._log(t("log.az_login_error", err=str(e)), "error")
            finally:
                self._root.after(0, lambda: self._login_btn.configure(state=tk.NORMAL))

        threading.Thread(target=_do_login, daemon=True).start()

    def _on_sp_login(self) -> None:
        """Service Principal で az login を実行する（Secret は保存しない）。"""

        dlg = tk.Toplevel(self._root)
        dlg.title(t("dlg.sp_login"))
        dlg.configure(bg=WINDOW_BG)
        dlg.resizable(False, False)
        dlg.transient(self._root)
        dlg.grab_set()

        client_var = tk.StringVar(value=load_setting("sp_client_id", ""))
        tenant_var = tk.StringVar(value=load_setting("sp_tenant_id", ""))
        secret_var = tk.StringVar(value="")

        form = tk.Frame(dlg, bg=WINDOW_BG)
        form.pack(padx=16, pady=12)
        form.columnconfigure(1, weight=1)

        tk.Label(form, text=t("label.client_id"), bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE)).grid(row=0, column=0, sticky="e", padx=(0, 8), pady=6)
        tk.Entry(form, textvariable=client_var, bg=INPUT_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), insertbackground=TEXT_FG,
                 relief=tk.FLAT, borderwidth=0, width=44).grid(row=0, column=1, sticky="ew", ipady=3)

        tk.Label(form, text=t("label.tenant_id"), bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE)).grid(row=1, column=0, sticky="e", padx=(0, 8), pady=6)
        tk.Entry(form, textvariable=tenant_var, bg=INPUT_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), insertbackground=TEXT_FG,
                 relief=tk.FLAT, borderwidth=0).grid(row=1, column=1, sticky="ew", ipady=3)

        tk.Label(form, text=t("label.client_secret"), bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE)).grid(row=2, column=0, sticky="e", padx=(0, 8), pady=6)
        tk.Entry(form, textvariable=secret_var, bg=INPUT_BG, fg=TEXT_FG,
                 show="*", font=(FONT_FAMILY, FONT_SIZE), insertbackground=TEXT_FG,
                 relief=tk.FLAT, borderwidth=0).grid(row=2, column=1, sticky="ew", ipady=3)

        btns = tk.Frame(dlg, bg=WINDOW_BG)
        btns.pack(fill=tk.X, padx=16, pady=(0, 12))

        def _close() -> None:
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()

        def _login() -> None:
            client_id = client_var.get().strip()
            tenant_id = tenant_var.get().strip()
            secret = secret_var.get().strip()
            if not client_id or not tenant_id or not secret:
                self._log(t("log.sp_login_missing"), "warning")
                return

            # Secret は永続化しない。Client/Tenant のみ保存。
            save_setting("sp_client_id", client_id)
            save_setting("sp_tenant_id", tenant_id)

            _close()

            def _do_login() -> None:
                self._log(t("log.sp_login_running"), "info")
                self._root.after(0, lambda: self._login_btn.configure(state=tk.DISABLED))
                self._root.after(0, lambda: self._sp_login_btn.configure(state=tk.DISABLED))
                try:
                    kwargs: dict = {
                        "capture_output": True, "text": True,
                        "timeout": 120, "encoding": "utf-8", "errors": "replace",
                    }
                    if sys.platform == "win32":
                        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                        kwargs["shell"] = True
                        cmd: str | list[str] = (
                            f"az login --service-principal -u {client_id} -p {secret} --tenant {tenant_id}"
                        )
                    else:
                        cmd = [
                            "az", "login", "--service-principal",
                            "-u", client_id, "-p", secret, "--tenant", tenant_id,
                        ]
                    result = subprocess.run(cmd, **kwargs)
                    if result.returncode == 0:
                        self._log(t("log.sp_login_success"), "success")
                        # Sub/RG をクリアして再ロード
                        self._root.after(0, lambda: self._sub_var.set(""))
                        self._root.after(0, lambda: self._rg_var.set(""))
                        self._root.after(0, lambda: self._sub_combo.configure(values=[]))
                        self._root.after(0, lambda: self._rg_combo.configure(values=[]))
                        self._bg_preflight()
                    else:
                        err = (result.stderr or "").strip()[:200]
                        self._log(t("log.sp_login_failed", err=err), "error")
                except Exception as e:
                    self._log(t("log.sp_login_failed", err=str(e)), "error")
                finally:
                    self._root.after(0, lambda: self._login_btn.configure(state=tk.NORMAL))
                    self._root.after(0, lambda: self._sp_login_btn.configure(state=tk.NORMAL))

            threading.Thread(target=_do_login, daemon=True).start()

        tk.Button(btns, text=t("btn.login"), command=_login,
                  bg=ACCENT_COLOR, fg="white", font=(FONT_FAMILY, FONT_SIZE, "bold"),
                  relief=tk.FLAT, padx=16, pady=6, cursor="hand2").pack(side=tk.LEFT)
        tk.Button(btns, text=t("btn.cancel_small"), command=_close,
                  bg="#3C3C3C", fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE),
                  relief=tk.FLAT, padx=16, pady=6, cursor="hand2").pack(side=tk.LEFT, padx=(8, 0))

        dlg.bind("<Escape>", lambda _e: _close())
        dlg.bind("<Return>", lambda _e: _login())

    def _extract_sub_id(self) -> str | None:
        """Combobox の表示値からサブスクID部分を取り出す。"""
        raw = self._sub_var.get().strip()
        if not raw or raw == t("hint.all_subscriptions"):
            return None
        # "name  (id)" 形式
        if "(" in raw and raw.endswith(")"):
            return raw.rsplit("(", 1)[-1].rstrip(")")
        return raw

    # ------------------------------------------------------------------ #
    # Collect → Review → Generate
    # ------------------------------------------------------------------ #

    def _on_collect(self) -> None:
        if self._working:
            return

        sub = self._extract_sub_id()
        rg_raw = self._rg_var.get().strip()
        rg = None if (not rg_raw or rg_raw == t("hint.all_rgs")) else rg_raw
        view = self._view_var.get().strip()
        try:
            limit = int(self._limit_var.get().strip())
        except ValueError:
            limit = 300

        self._cancel_event.clear()

        # 前回の差分ファイルは新規実行でクリア（誤って古いdiffを開かない）
        self._last_diff_path = None
        self._diff_btn.configure(state=tk.DISABLED)

        self._set_working(True)
        self._hide_review()

        # Canvasプレビューをリセット
        def _reset_preview() -> None:
            self._canvas.delete("all")
            if self._preview_frame.winfo_ismapped():
                self._preview_frame.pack_forget()
        self._root.after(0, _reset_preview)

        # ログクリア（新しい実行ごとに見やすく）
        def _clear_log() -> None:
            self._log_area.configure(state=tk.NORMAL)
            self._log_area.delete("1.0", tk.END)
            self._log_area.configure(state=tk.DISABLED)
        self._root.after(0, _clear_log)

        self._log("=" * 50, "accent")
        self._log(f"  View: {view}", "accent")
        if sub:
            self._log(f"  Subscription: {sub}")
        if rg:
            self._log(f"  Resource Group: {rg}")
        self._log(f"  Limit: {limit}")

        threading.Thread(
            target=self._worker_collect,
            args=(sub, rg, limit, view),
            daemon=True,
        ).start()

    def _worker_collect(self, sub: str | None, rg: str | None, limit: int, view: str = "inventory") -> None:
        """収集ワーカー。完了後にレビュー画面を表示して待つ。"""
        try:
            # レポートビューの場合は別フローへ
            if view in ("security-report", "cost-report"):
                self._worker_report(sub, rg, limit, view)
                return

            # Step 1: Collect
            self._set_step("Step 1/5: Collect")
            self._set_status(t("status.running_query"))
            self._log(t("log.query_running", view=view), "info")

            nodes, collected_edges, meta = collect_diagram_view(
                view=view,
                subscription=sub,
                resource_group=rg,
                limit=limit,
            )
            if view == "network":
                self._log(t("log.net_resources_found", nodes=len(nodes), edges=len(collected_edges)), "success")
            else:
                self._log(t("log.resources_found", count=len(nodes)), "success")

            if self._cancel_event.is_set():
                self._log(t("log.cancelled"), "warning")
                return

            # type別サマリ
            summary = type_summary(nodes)
            for rtype, count in sorted(summary.items()):
                short = rtype.split("/")[-1] if "/" in rtype else rtype
                self._log(f"    {short}: {count}", "info")

            if limit <= len(nodes):
                self._log(t("log.limit_reached", limit=limit), "warning")

            # レビュー表示して Proceed/Cancel 待ち
            self._pending_nodes = nodes
            self._pending_meta = meta

            # --- AI レビュー（Copilot SDK） ---
            self._set_step("Step 2/5: AI Review")
            self._set_status(t("status.reviewing"))
            self._log("─" * 40, "accent")
            self._log(t("log.ai_review_start"), "info")

            # サマリテキスト作成
            summary_lines = []
            if sub:
                summary_lines.append(f"Subscription: {sub}")
            if rg:
                summary_lines.append(f"Resource Group: {rg}")
            summary_lines.append(f"View: {view}")
            summary_lines.append(f"Total resources: {len(nodes)}")
            summary_lines.append("")
            for rtype, count in sorted(summary.items()):
                short = rtype.split("/")[-1] if "/" in rtype else rtype
                summary_lines.append(f"  {short}: {count}")
            summary_lines.append("")
            summary_lines.append("Resources:")
            for node in nodes[:100]:  # 多すぎる場合は100件まで
                summary_lines.append(f"  - {node.name} ({node.type})")
            if len(nodes) > 100:
                summary_lines.append(f"  ... and {len(nodes) - 100} more")
            resource_text = "\n".join(summary_lines)

            ai_review_result: str | None = None
            try:
                from ai_reviewer import run_ai_review
                ai_review_result = run_ai_review(
                    resource_text=resource_text,
                    on_delta=lambda d: self._log_append_delta(d),
                    on_status=lambda s: self._log(s, "info"),
                    model_id=self._model_var.get().strip() or None,
                )
            except Exception as e:
                self._log(t("log.ai_review_skip", err=str(e)), "warning")

            self._log("", "info")  # 改行
            self._log("─" * 40, "accent")

            if self._cancel_event.is_set():
                self._log(t("log.cancelled"), "warning")
                return

            review_text = (
                f"{len(nodes)} resources | "
                f"{len(summary)} types | "
                f"Sub: {sub or '(default)'} | "
                f"RG: {rg or '(all)'}"
            )
            self._show_review(review_text)
            self._set_step("Review")
            self._set_status(t("status.review_prompt"))

            # ブロッキング待ち（ワーカースレッド上）
            self._review_event.clear()
            self._review_event.wait()

            if not self._review_proceed or self._cancel_event.is_set():
                self._log(t("log.cancelled"), "warning")
                self._set_status(t("status.cancelled"))
                return

            self._hide_review()

            # Step 2: 保存先決定（Output Dir設定済みなら自動、未設定ならダイアログ）
            initial_dir = self._output_dir_var.get().strip()
            default_name = self._make_filename("env", sub, rg, ".drawio")

            if initial_dir and Path(initial_dir).is_dir():
                # 自動保存
                out_path = Path(initial_dir) / default_name
                self._log(t("log.auto_save", path=str(out_path)), "info")
            else:
                # ダイアログ
                out_path_holder: list[str] = []
                done_event = threading.Event()

                def _ask_save() -> None:
                    p = filedialog.asksaveasfilename(
                        title=t("dlg.save_drawio"),
                        defaultextension=".drawio",
                        filetypes=[("Draw.io XML", "*.drawio"), ("All files", "*.*")],
                        initialfile=default_name,
                        initialdir=str(Path.home() / "Documents"),
                    )
                    if p:
                        out_path_holder.append(p)
                    done_event.set()

                self._root.after(0, _ask_save)
                done_event.wait()

                if not out_path_holder:
                    self._log(t("log.save_not_selected"), "warning")
                    self._set_status(t("status.cancelled"))
                    return
                out_path = Path(out_path_holder[0])

            # Step 3: Normalize
            self._set_step("Step 3/5: Normalize")
            self._set_status(t("status.normalizing"))
            azure_to_cell_id = {n.azure_id: cell_id_for_azure_id(n.azure_id) for n in nodes}
            edges: list[Edge] = collected_edges

            # Step 4: Build XML
            self._set_step("Step 4/5: Build XML")
            self._set_status(t("status.generating_xml"))
            self._log(t("log.generating_xml"))
            xml = build_drawio_xml(
                nodes=nodes, edges=edges,
                azure_to_cell_id=azure_to_cell_id,
                diagram_name=f"{view}-{now_stamp()}",
            )

            # Step 5: Save
            self._set_step("Step 5/5: Save")
            self._set_status(t("status.saving"))
            write_text(out_path, xml)
            self._log(f"  → {out_path}", "success")

            out_dir = out_path.parent
            env_payload = {
                "generatedAt": datetime.now().isoformat(timespec="seconds"),
                "view": view,
                "subscription": sub,
                "resourceGroup": rg,
                "nodes": [
                    {"id": n.azure_id, "name": n.name, "type": n.type,
                     "resourceGroup": n.resource_group, "location": n.location}
                    for n in nodes
                ],
                "edges": [
                    {"source": e.source, "target": e.target, "kind": e.kind}
                    for e in edges
                ],
                "azureIdToCellId": azure_to_cell_id,
            }
            write_json(out_dir / "env.json", env_payload)
            self._log(f"  → {out_dir / 'env.json'}", "success")

            write_json(out_dir / "collect.log.json", {"tool": "az graph query", "meta": meta})

            # SVG エクスポート
            if self._export_svg_var.get():
                svg_result = export_drawio_svg(out_path)
                if svg_result:
                    self._log(f"  → {svg_result}", "success")
                else:
                    self._log(t("log.svg_export_skip"), "warning")

            # Done + Preview
            self._set_step("Done")
            self._log(t("log.done"), "success")
            self._set_status(f"Done — {out_path}")

            self._last_out_path = out_path
            self._root.after(0, lambda: self._open_btn.configure(state=tk.NORMAL))

            # Canvas プレビュー
            self._draw_preview(nodes, edges, azure_to_cell_id)

            # 自動オープン
            if self._auto_open_var.get() and out_path.exists():
                self._root.after(500, lambda p=out_path: self._open_file_with(p))

        except Exception as e:
            self._log(f"ERROR: {e}", "error")
            self._set_status(t("status.error"))
        finally:
            self._set_working(False)

    # ------------------------------------------------------------------ #
    # レビュー
    # ------------------------------------------------------------------ #

    def _show_review(self, text: str) -> None:
        def _do() -> None:
            self._review_text_var.set(text)
            self._review_frame.pack(fill=tk.X, padx=12, pady=(0, 4), before=self._log_area)
        self._root.after(0, _do)

    def _hide_review(self) -> None:
        self._root.after(0, self._review_frame.pack_forget)

    def _on_proceed(self) -> None:
        self._review_proceed = True
        self._review_event.set()

    def _on_cancel(self) -> None:
        self._review_proceed = False
        self._cancel_event.set()
        self._review_event.set()
        self._hide_review()

    # ------------------------------------------------------------------ #
    # Canvas プレビュー
    # ------------------------------------------------------------------ #

    def _draw_preview(self, nodes: list[Node], edges: list[Edge],
                      azure_to_cell_id: dict[str, str]) -> None:
        """ログエリアの下にCanvasで簡易描画。色はdrawio_writerと同じ。"""
        from drawio_writer import _color_for_type, _TYPE_ICONS

        def _do() -> None:
            self._canvas.delete("all")
            self._canvas_scale = 1.0
            self._canvas_offset_x = 0.0
            self._canvas_offset_y = 0.0

            if not self._preview_frame.winfo_ismapped():
                self._preview_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 4))

            type_to_col: dict[str, int] = {}
            col_next = 0
            cell_w, cell_h = 100, 50
            x0, y0 = 20, 40
            x_gap, y_gap = 30, 16
            header_h = 16
            placed: dict[int, int] = {}
            positions: dict[str, tuple[float, float]] = {}

            # type別の色マップ（公式アイコンtypeはAzureブルー、それ以外はハッシュ色）
            type_colors: dict[str, str] = {}

            for node in nodes:
                col = type_to_col.get(node.type)
                if col is None:
                    col = col_next
                    type_to_col[node.type] = col
                    col_next += 1

                    # type色を決定
                    lower = node.type.lower()
                    if lower in _TYPE_ICONS:
                        type_colors[node.type] = "#0078d4"  # Azure Blue
                    else:
                        type_colors[node.type] = _color_for_type(node.type)

                    # 列ヘッダー
                    short_header = node.type.split("/")[-1] if "/" in node.type else node.type
                    hx = x0 + col * (cell_w + x_gap) + cell_w / 2
                    self._canvas.create_text(
                        hx, y0 - header_h,
                        text=short_header,
                        fill=ACCENT_COLOR,
                        font=(FONT_FAMILY, 7, "bold"),
                        anchor="center",
                    )

                row = placed.get(col, 0)
                placed[col] = row + 1

                px = x0 + col * (cell_w + x_gap)
                py = y0 + row * (cell_h + y_gap)
                positions[node.azure_id] = (px, py)

                color = type_colors.get(node.type, "#3C3C3C")
                display_name = node.name[:14] + "…" if len(node.name) > 14 else node.name
                short_type = node.type.split("/")[-1] if "/" in node.type else node.type

                self._canvas.create_rectangle(
                    px, py, px + cell_w, py + cell_h,
                    fill=color, outline="#555555", width=1,
                )
                self._canvas.create_text(
                    px + cell_w / 2, py + cell_h / 2,
                    text=f"{display_name}\n{short_type}",
                    fill="white", font=(FONT_FAMILY, 6),
                    anchor="center",
                )

            for edge in edges:
                sp = positions.get(edge.source)
                tp = positions.get(edge.target)
                if sp and tp:
                    self._canvas.create_line(
                        sp[0] + cell_w, sp[1] + cell_h / 2,
                        tp[0], tp[1] + cell_h / 2,
                        fill="#888888", width=1,
                    )

        self._root.after(0, _do)

    def _on_canvas_press(self, event: tk.Event) -> None:
        self._drag_start = (event.x, event.y)

    def _on_canvas_drag(self, event: tk.Event) -> None:
        if self._drag_start:
            dx = event.x - self._drag_start[0]
            dy = event.y - self._drag_start[1]
            self._canvas.move("all", dx, dy)
            self._drag_start = (event.x, event.y)

    def _on_canvas_zoom(self, event: tk.Event) -> None:
        factor = 1.1 if event.delta > 0 else 0.9
        self._canvas.scale("all", event.x, event.y, factor, factor)
        self._canvas_scale *= factor

    # ------------------------------------------------------------------ #
    # Copy Log
    # ------------------------------------------------------------------ #

    def _on_copy_log(self) -> None:
        content = self._log_area.get("1.0", tk.END).strip()
        if content:
            self._root.clipboard_clear()
            self._root.clipboard_append(content)
            self._set_status(t("status.log_copied"))

    # ------------------------------------------------------------------ #
    # Open File / Show Diff
    # ------------------------------------------------------------------ #

    def _on_open_file(self) -> None:
        if self._last_out_path and self._last_out_path.exists():
            self._open_file_with(self._last_out_path)

    def _on_open_diff(self) -> None:
        if self._last_diff_path and self._last_diff_path.exists():
            self._open_file_with(self._last_diff_path)
        else:
            self._log(t("label.diff_not_found"), "warning")

    def _open_file_with(self, path: Path) -> None:
        """Open App 設定に応じてファイルを開く。"""
        choice = self._open_app_var.get()
        suffix = path.suffix.lower()
        is_drawio = suffix == ".drawio"

        if choice == "auto":
            if is_drawio:
                # Draw.io があればそれ、なければ VS Code、それもなければ OS既定
                dp = cached_drawio_path()
                if dp:
                    subprocess.Popen([dp, str(path)], **_subprocess_no_window())
                    return
                vp = cached_vscode_path()
                if vp:
                    subprocess.Popen([vp, str(path)], **_subprocess_no_window())
                    return
            open_native(path)

        elif choice == "drawio":
            dp = cached_drawio_path()
            if dp:
                subprocess.Popen([dp, str(path)], **_subprocess_no_window())
            else:
                self._log(t("log.drawio_not_found"), "warning")
                open_native(path)

        elif choice == "vscode":
            vp = cached_vscode_path()
            if vp:
                subprocess.Popen([vp, str(path)], **_subprocess_no_window())
            else:
                self._log(t("log.vscode_not_found"), "warning")
                open_native(path)

        else:  # "os"
            open_native(path)

    # ------------------------------------------------------------------ #
    # レポート生成ワーカー (security-report / cost-report)
    # ------------------------------------------------------------------ #

    def _worker_report(self, sub: str | None, rg: str | None, limit: int, view: str) -> None:
        """Security / Cost レポート生成ワーカー。"""
        try:
            # テンプレートとカスタム指示をUIスレッドで取得
            template = self._get_current_template_with_overrides()
            custom_instruction = self._get_custom_instruction()

            # サブスクリプション表示名（AIがレポートタイトルに使う）
            sub_display = self._sub_var.get().strip()
            if not sub_display or sub_display == t("hint.all_subscriptions"):
                sub_display = sub or ""

            if template:
                tname = template.get('template_name', '?')
                enabled_count = sum(1 for s in template.get('sections', {}).values() if s.get('enabled'))
                total_count = len(template.get('sections', {}))
                self._log(t("log.template_info", name=tname, enabled=enabled_count, total=total_count), "info")
            if custom_instruction:
                truncated = custom_instruction[:80] + ('...' if len(custom_instruction) > 80 else '')
                self._log(t("log.custom_instr_info", text=truncated), "info")
            # Step 1: リソース収集
            self._set_step("Step 1/3: Collect")
            self._set_status(t("status.collecting"))
            self._log(t("log.query_running", view=view), "info")

            nodes, meta = collect_inventory(subscription=sub, resource_group=rg, limit=limit)
            self._log(t("log.resources_found", count=len(nodes)), "success")

            # リソーステキスト作成
            summary = type_summary(nodes)
            resource_types = list(summary.keys())  # Docs 検索用
            summary_lines = []
            for rtype, count in sorted(summary.items()):
                short = rtype.split("/")[-1] if "/" in rtype else rtype
                summary_lines.append(f"  {short}: {count}")
            for node in nodes[:100]:
                summary_lines.append(f"  - {node.name} ({node.type})")
            resource_text = "\n".join(summary_lines)

            if self._cancel_event.is_set():
                return

            # Step 2: 追加データ収集 + AIレポート生成
            self._set_step("Step 2/3: AI Report")
            self._log("─" * 40, "accent")

            report_result: str | None = None

            if view == "security-report":
                self._set_status(t("status.collecting_sec"))
                self._log(t("log.sec_collecting"), "info")
                security_data = collect_security(sub)
                score = security_data.get("secure_score")
                if score:
                    self._log(t("log.sec_score", current=score.get('current'), max=score.get('max')), "info")
                assess = security_data.get("assessments_summary")
                if assess:
                    self._log(t("log.sec_assess", total=assess.get('total'), healthy=assess.get('healthy'), unhealthy=assess.get('unhealthy')), "info")

                self._log(t("log.sec_ai_gen"), "info")
                try:
                    from ai_reviewer import run_security_report
                    report_result = run_security_report(
                        security_data=security_data,
                        resource_text=resource_text,
                        template=template,
                        custom_instruction=custom_instruction,
                        on_delta=lambda d: self._log_append_delta(d),
                        on_status=lambda s: self._log(s, "info"),
                        model_id=self._model_var.get().strip() or None,
                        subscription_info=sub_display,
                    )
                except Exception as e:
                    self._log(t("log.ai_report_error", err=str(e)), "error")

            elif view == "cost-report":
                self._set_status(t("status.collecting_cost"))
                self._log(t("log.cost_collecting"), "info")
                cost_data = collect_cost(sub)
                svc = cost_data.get("cost_by_service")
                if svc:
                    self._log(t("log.cost_by_svc", count=len(svc)), "info")
                rg_cost = cost_data.get("cost_by_rg")
                if rg_cost:
                    self._log(t("log.cost_by_rg", count=len(rg_cost)), "info")

                self._log(t("log.advisor_collecting"), "info")
                advisor_data = collect_advisor(sub)
                adv_summary = advisor_data.get("summary", {})
                if adv_summary:
                    for cat, cnt in adv_summary.items():
                        self._log(f"    {cat}: {cnt}", "info")

                self._log(t("log.cost_ai_gen"), "info")
                try:
                    from ai_reviewer import run_cost_report
                    report_result = run_cost_report(
                        cost_data=cost_data,
                        advisor_data=advisor_data,
                        template=template,
                        custom_instruction=custom_instruction,
                        on_delta=lambda d: self._log_append_delta(d),
                        on_status=lambda s: self._log(s, "info"),
                        resource_types=resource_types,
                        model_id=self._model_var.get().strip() or None,
                        subscription_info=sub_display,
                    )
                except Exception as e:
                    self._log(t("log.ai_report_error", err=str(e)), "error")

            self._log("", "info")
            self._log("─" * 40, "accent")

            if self._cancel_event.is_set():
                return

            if not report_result:
                self._log(t("log.report_failed"), "error")
                self._set_status(t("status.failed"))
                return

            # レビュー表示して Proceed/Cancel 待ち（ワーカースレッド上）
            self._show_review(t("status.report_review_prompt"))
            self._set_step("Review")
            self._set_status(t("status.report_review_prompt"))
            self._review_proceed = False
            self._review_event.clear()
            self._review_event.wait()

            if not self._review_proceed or self._cancel_event.is_set():
                self._log(t("log.cancelled"), "warning")
                self._set_status(t("status.cancelled"))
                return

            self._hide_review()

            # Step 3: 保存（Output Dir設定済みなら自動、未設定ならダイアログ）
            self._set_step("Step 3/3: Save")
            report_type = "security" if view == "security-report" else "cost"
            default_name = self._make_filename(f"{report_type}-report", sub, rg, ".md")
            initial_dir = self._output_dir_var.get().strip()

            if initial_dir and Path(initial_dir).is_dir():
                # 自動保存
                out_path = Path(initial_dir) / default_name
                self._log(t("log.auto_save", path=str(out_path)), "info")
            else:
                # ダイアログ
                out_path_holder: list[str] = []
                done_event = threading.Event()

                def _ask_save() -> None:
                    p = filedialog.asksaveasfilename(
                        title=t("dlg.save_report", type=report_type),
                        defaultextension=".md",
                        filetypes=[("Markdown", "*.md"), ("All files", "*.*")],
                        initialfile=default_name,
                        initialdir=str(Path.home() / "Documents"),
                    )
                    if p:
                        out_path_holder.append(p)
                    done_event.set()

                self._root.after(0, _ask_save)
                done_event.wait()

                if not out_path_holder:
                    self._log(t("log.save_not_selected"), "warning")
                    self._set_status(t("status.cancelled"))
                    return
                out_path = Path(out_path_holder[0])
            write_text(out_path, report_result)
            self._last_out_path = out_path
            self._log(f"  → {out_path}", "success")

            # レポート入力（収集データ/テンプレ/指示）を隣に保存（再生成・監査用）
            try:
                input_payload: dict[str, Any] = {
                    "generatedAt": datetime.now().isoformat(timespec="seconds"),
                    "view": view,
                    "report_type": report_type,
                    "subscription": sub,
                    "subscription_display": sub_display,
                    "template": template,
                    "custom_instruction": custom_instruction,
                    "resource_types": resource_types,
                    "resource_text": resource_text,
                }
                if view == "security-report":
                    input_payload["security_data"] = security_data
                elif view == "cost-report":
                    input_payload["cost_data"] = cost_data
                    input_payload["advisor_data"] = advisor_data

                write_json(out_path.with_name(out_path.stem + "-input.json"), input_payload)
            except Exception:
                pass

            # 差分レポート（前回が存在すれば自動生成）
            try:
                from exporter import find_previous_report, generate_diff_report
                prev = find_previous_report(out_path.parent, report_type, out_path.name)
                if prev:
                    diff_md = generate_diff_report(prev, out_path)
                    diff_path = out_path.with_name(out_path.stem + "-diff.md")
                    write_text(diff_path, diff_md)
                    self._last_diff_path = diff_path
                    self._root.after(0, lambda: self._diff_btn.configure(state=tk.NORMAL))
                    self._log(t("log.diff_generated", path=str(diff_path.name)), "success")
            except Exception:
                pass  # 差分生成は best-effort

            # 追加出力形式
            if self._export_docx_var.get():
                try:
                    from exporter import md_to_docx
                    docx_path = out_path.with_suffix(".docx")
                    md_to_docx(report_result, docx_path)
                    self._log(t("log.word_output", path=str(docx_path)), "success")
                except Exception as e:
                    self._log(t("log.word_error", err=str(e)), "warning")

            if self._export_pdf_var.get():
                try:
                    from exporter import md_to_pdf
                    pdf_path = out_path.with_suffix(".pdf")
                    result = md_to_pdf(report_result, pdf_path)
                    if result:
                        self._log(t("log.pdf_output", path=str(pdf_path)), "success")
                    else:
                        self._log(t("log.pdf_not_found"), "warning")
                except Exception as e:
                    self._log(t("log.pdf_error", err=str(e)), "warning")

            self._root.after(0, lambda: self._open_btn.configure(state=tk.NORMAL))
            self._set_status(t("status.done"))
            self._log(t("log.done"), "success")

            # 自動オープン
            if self._auto_open_var.get() and out_path.exists():
                self._root.after(500, lambda p=out_path: self._open_file_with(p))

        except Exception as e:
            self._log(f"ERROR: {e}", "error")
            self._set_status(t("status.error"))
        finally:
            self._set_working(False)

    # ------------------------------------------------------------------ #
    # 言語切替ハンドラ
    # ------------------------------------------------------------------ #

    def _on_language_changed(self) -> None:
        """言語ラジオボタン変更時にUIテキストを更新。"""
        lang = self._lang_var.get()
        set_language(lang)
        self._refresh_ui_texts()
        # テンプレートパネルのセクション名・指示ラベルを再描画
        view = self._view_var.get().strip()
        if view in ("security-report", "cost-report"):
            report_type = "security" if view == "security-report" else "cost"
            self._load_templates_for_type(report_type)

    def _refresh_ui_texts(self) -> None:
        """全ウィジェットのテキストを現在の言語で再設定。"""
        # タイトル
        self._title_label.configure(text=t("app.title"))
        self._subtitle_label.configure(text=t("app.subtitle"))

        # フォームラベル
        self._lang_label.configure(text=t("label.language"))
        self._model_label.configure(text=t("label.model"))
        self._view_label.configure(text=t("label.view"))
        self._sub_label.configure(text=t("label.subscription"))
        self._sub_hint.configure(text=t("hint.optional"))
        self._rg_label.configure(text=t("label.resource_group"))
        self._limit_label.configure(text=t("label.max_nodes"))
        self._outdir_label.configure(text=t("label.output_dir"))
        self._openwith_label.configure(text=t("label.open_with"))

        # Draw.io 検出ヒント
        drawio_path = cached_drawio_path()
        self._drawio_hint_label.configure(
            text=t("hint.drawio_detected") if drawio_path else t("hint.drawio_not_found"))

        # ボタン
        self._refresh_btn.configure(text=t("btn.refresh"))
        self._open_btn.configure(text=t("btn.open_file"))
        self._diff_btn.configure(text=t("btn.open_diff"))
        self._copy_btn.configure(text=t("btn.copy_log"))
        self._clear_log_btn.configure(text=t("btn.clear_log"))
        self._login_btn.configure(text=t("btn.az_login"))
        self._sp_login_btn.configure(text=t("btn.sp_login"))
        self._proceed_btn.configure(text=t("btn.proceed"))
        self._cancel_btn.configure(text=t("btn.cancel_review"))
        self._abort_btn.configure(text=t("btn.cancel"))
        self._auto_open_main_cb.configure(text=t("btn.auto_open"))

        # レポートパネル
        self._instr_label.configure(text=t("label.extra_instructions"))
        self._free_input_label.configure(text=t("label.free_input"))
        self._save_instr_btn.configure(text=t("btn.save_instruction"))
        self._del_instr_btn.configure(text=t("btn.delete_instruction"))
        self._export_label.configure(text=t("label.export_format"))
        self._save_tmpl_btn.configure(text=t("btn.save_template"))

        # View依存（再トリガ）
        self._on_view_changed()

    # ------------------------------------------------------------------ #
    # 起動
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        # App 終了時に設定保存 + CopilotClient を graceful shutdown する
        def _on_close() -> None:
            # 全設定を永続化
            self._save_all_settings()
            # CopilotClient + イベントループをシャットダウン
            try:
                from ai_reviewer import shutdown_sync
                shutdown_sync()
            except Exception:
                pass
            self._root.destroy()

        self._root.protocol("WM_DELETE_WINDOW", _on_close)
        self._root.mainloop()


# ============================================================
# エントリポイント
# ============================================================

def main() -> None:
    app = App()
    app.run()


if __name__ == "__main__":
    main()
