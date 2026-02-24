"""Azure Ops Dashboard — tkinter GUIアプリ

Azure環境（既存リソース）を読み取り、
Draw.io（diagrams.net）で開ける .drawio 図を生成するGUI。

構成:
  Main Thread   → tkinter メインループ
  Worker Thread → az graph query → .drawio 生成（UIをブロックしない）

操作フロー:
    入力 → Collect → (AI Reviewをログに表示) → Generate → Preview → Open
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
    run_az_command,
    type_summary,
)
from drawio_writer import build_drawio_xml, now_stamp, preprocess_nodes

from app_paths import (
    ensure_user_dirs, load_all_settings, load_setting, save_all_settings,
    save_setting, saved_instructions_path, user_saved_instructions_path, settings_path, user_templates_dir,
    bundled_templates_dir,
)
from gui_helpers import (
    WINDOW_TITLE, WINDOW_WIDTH, WINDOW_HEIGHT,
    WINDOW_BG, PANEL_BG, TEXT_FG, MUTED_FG, INPUT_BG, ACCENT_COLOR,
    SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR,
    BUTTON_BG, BUTTON_FG,
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
        self._delta_buffer: list[str] = []          # ストリーミングデルタのバッチバッファ
        self._delta_flush_scheduled: bool = False   # flush 予約済みフラグ
        self._last_out_path: Path | None = None
        self._last_diff_path: Path | None = None
        self._subs_cache: list[dict[str, str]] = []
        self._rgs_cache: list[str] = []

        # 利用モデル（起動後に動的取得してUIに反映）
        self._models_cache: list[str] = []

        # レビュー待ち用
        self._pending_nodes: list[Node] = []
        self._pending_meta: dict[str, Any] = {}

        self._setup_styles()
        self._setup_widgets()
        self._setup_keybindings()

        # 保存済み設定を復元
        self._restore_all_settings()

        # 起動時に事前チェック + Sub候補ロード（非同期）
        # NOTE: mainloop 開始後に遅延起動して after() コールバックの安全性を保証 (review #17)
        self._root.after(100, lambda: threading.Thread(target=self._bg_preflight, daemon=True).start())

        # 起動時に利用可能モデル一覧を取得（非同期）
        self._root.after(200, lambda: threading.Thread(target=self._bg_load_models, daemon=True).start())

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

        # --- Row 1: Output targets (checkboxes) ---
        self._view_label = tk.Label(form, text=t("label.view"), bg=WINDOW_BG, fg=ACCENT_COLOR,
                 font=(FONT_FAMILY, FONT_SIZE, "bold"), anchor="e")
        self._view_label.grid(row=1, column=0, sticky="e", padx=(0, 6), pady=3)

        view_cb_frame = tk.Frame(form, bg=WINDOW_BG)
        view_cb_frame.grid(row=1, column=1, columnspan=2, sticky="w", pady=3)

        self._view_inventory_var = tk.BooleanVar(value=False)
        self._view_network_var = tk.BooleanVar(value=False)
        self._gen_security_var = tk.BooleanVar(value=False)
        self._gen_cost_var = tk.BooleanVar(value=False)

        self._view_inventory_cb = tk.Checkbutton(
            view_cb_frame, text=t("opt.inventory_diagram"),
            variable=self._view_inventory_var,
            command=self._on_view_changed,
            bg=WINDOW_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
            activebackground=WINDOW_BG, activeforeground=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
        )
        self._view_inventory_cb.pack(side=tk.LEFT, padx=(0, 6))

        self._view_network_cb = tk.Checkbutton(
            view_cb_frame, text=t("opt.network_diagram"),
            variable=self._view_network_var,
            command=self._on_view_changed,
            bg=WINDOW_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
            activebackground=WINDOW_BG, activeforeground=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
        )
        self._view_network_cb.pack(side=tk.LEFT, padx=(0, 6))

        self._gen_security_cb = tk.Checkbutton(
            view_cb_frame, text=t("opt.security_report"),
            variable=self._gen_security_var,
            command=self._on_view_changed,
            bg=WINDOW_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
            activebackground=WINDOW_BG, activeforeground=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
        )
        self._gen_security_cb.pack(side=tk.LEFT, padx=(0, 6))

        self._gen_cost_cb = tk.Checkbutton(
            view_cb_frame, text=t("opt.cost_report"),
            variable=self._gen_cost_var,
            command=self._on_view_changed,
            bg=WINDOW_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
            activebackground=WINDOW_BG, activeforeground=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
        )
        self._gen_cost_cb.pack(side=tk.LEFT, padx=(0, 6))

        # View 説明ラベル（動的に更新）
        self._view_desc_var = tk.StringVar(value="")
        tk.Label(view_cb_frame, textvariable=self._view_desc_var, bg=WINDOW_BG, fg=MUTED_FG,
                 font=(FONT_FAMILY, FONT_SIZE - 2)).pack(side=tk.LEFT, padx=(8, 0))

        # --- Row 1: AI-powered diagram layout (diagrams only, placed right of checkboxes) ---
        self._ai_drawio_var = tk.BooleanVar(value=True)
        self._ai_drawio_cb = tk.Checkbutton(
            view_cb_frame,
            text=t("opt.ai_drawio_layout"),
            variable=self._ai_drawio_var,
            bg=WINDOW_BG,
            fg=TEXT_FG,
            selectcolor=INPUT_BG,
            activebackground=WINDOW_BG,
            activeforeground=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 2),
        )
        self._ai_drawio_cb.pack(side=tk.RIGHT, padx=(6, 0))

        # --- Row 2: Subscription ---
        self._sub_var = tk.StringVar()
        self._sub_label = tk.Label(form, text=t("label.subscription"), bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), anchor="e")
        self._sub_label.grid(row=2, column=0, sticky="e", padx=(0, 6), pady=3)
        self._sub_combo = ttk.Combobox(form, textvariable=self._sub_var, state="normal",
                                        font=(FONT_FAMILY, FONT_SIZE))
        self._sub_combo.grid(row=2, column=1, sticky="ew", pady=3, ipady=2)
        self._sub_combo.bind("<<ComboboxSelected>>", self._on_sub_selected)
        self._sub_hint = tk.Label(form, text=t("hint.optional"), bg=WINDOW_BG, fg=MUTED_FG,
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
        self._rg_hint = tk.Label(form, text=t("hint.recommended"), bg=WINDOW_BG, fg=MUTED_FG,
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
        self._limit_hint = tk.Label(form, text=t("hint.default_300"), bg=WINDOW_BG, fg=MUTED_FG,
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
                  bg=BUTTON_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 1),
                  relief=tk.FLAT, padx=8, cursor="hand2",
                  ).grid(row=0, column=1, padx=(4, 0))
        self._open_dir_btn = tk.Button(form, text="📂",
                  command=self._on_open_output_dir,
                  bg=BUTTON_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 1),
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
                 fg=SUCCESS_COLOR if drawio_path else MUTED_FG,
                 font=(FONT_FAMILY, FONT_SIZE - 2))
        self._drawio_hint_label.grid(row=6, column=2, padx=(4, 0))

        # ============================================================
        # レポート設定パネル（レポート系View選択時のみ表示）
        # ============================================================
        self._report_panel = tk.Frame(self._root, bg=PANEL_BG, relief=tk.GROOVE, borderwidth=1)
        # pack は _on_view_changed で

        # --- ヘッダー行（常に表示 / クリックで本体を開閉） ---
        self._report_header = tk.Frame(self._report_panel, bg=PANEL_BG)
        self._report_header.pack(fill=tk.X, padx=0, pady=0)

        self._report_collapsed = True  # 初期は折りたたみ

        self._toggle_btn = tk.Label(
            self._report_header, text="▶", bg=PANEL_BG, fg=ACCENT_COLOR,
            font=(FONT_FAMILY, FONT_SIZE - 1, "bold"), cursor="hand2",
        )
        self._toggle_btn.pack(side=tk.LEFT, padx=(10, 2), pady=(4, 2))
        self._toggle_btn.bind("<Button-1>", lambda _: self._toggle_report_body())

        # --- Template 選択行（ヘッダー内） ---
        tmpl_row = tk.Frame(self._report_header, bg=PANEL_BG)
        tmpl_row.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=(4, 2))

        tk.Label(tmpl_row, text=t("label.template"), bg=PANEL_BG, fg=ACCENT_COLOR,
                 font=(FONT_FAMILY, FONT_SIZE - 1, "bold")).pack(side=tk.LEFT)
        self._template_var = tk.StringVar(value="Standard")
        self._template_combo = ttk.Combobox(tmpl_row, textvariable=self._template_var,
                                             state="readonly", width=20,
                                             font=(FONT_FAMILY, FONT_SIZE - 1))
        self._template_combo.pack(side=tk.LEFT, padx=(6, 0))
        self._template_combo.bind("<<ComboboxSelected>>", self._on_template_selected)

        self._template_desc_var = tk.StringVar(value="")
        tk.Label(tmpl_row, textvariable=self._template_desc_var,
                 bg=PANEL_BG, fg=MUTED_FG,
                 font=(FONT_FAMILY, FONT_SIZE - 2)).pack(side=tk.LEFT, padx=(8, 0))

        self._save_tmpl_btn = tk.Button(tmpl_row, text=t("btn.save_template"),
                  command=self._on_save_template,
                  bg=BUTTON_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 2),
                  relief=tk.FLAT, padx=6, cursor="hand2")
        self._save_tmpl_btn.pack(side=tk.RIGHT)

        self._import_tmpl_btn = tk.Button(tmpl_row, text=t("btn.import_template"),
                  command=self._on_import_template,
                  bg=BUTTON_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 2),
                  relief=tk.FLAT, padx=6, cursor="hand2")
        self._import_tmpl_btn.pack(side=tk.RIGHT, padx=(0, 4))

        # (Report target checkboxes moved to View row — no longer needed here)

        # --- 折りたたみ本体（スクロール対応） ---
        self._report_body_outer = tk.Frame(self._report_panel, bg=PANEL_BG)
        # 初期は折りたたみなので pack しない

        self._report_canvas = tk.Canvas(
            self._report_body_outer, bg=PANEL_BG, highlightthickness=0,
            height=140,  # 最大表示高さ
        )
        self._report_scrollbar = tk.Scrollbar(
            self._report_body_outer, orient="vertical",
            command=self._report_canvas.yview,
        )
        self._report_canvas.configure(yscrollcommand=self._report_scrollbar.set)
        self._report_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._report_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._report_body = tk.Frame(self._report_canvas, bg=PANEL_BG)
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

        def _bind_mousewheel_recursive(widget: tk.Misc) -> None:
            """widget とその全子孫に MouseWheel バインドを適用。"""
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_mousewheel_recursive(child)

        self._report_canvas.bind("<MouseWheel>", _on_mousewheel)
        self._report_body.bind("<MouseWheel>", _on_mousewheel)
        # 初期子ウィジェットにもバインド（動的追加分は _rebuild_section_checks で対応）
        self._bind_report_mousewheel = _bind_mousewheel_recursive

        # --- セクションチェックボックス（2列グリッド） ---
        self._sections_frame = tk.Frame(self._report_body, bg=PANEL_BG)
        self._sections_frame.pack(fill=tk.X, padx=10, pady=(2, 2))
        self._section_vars: dict[str, tk.BooleanVar] = {}
        self._section_widgets: list[tk.Checkbutton] = []

        # --- カスタム指示欄（保存済み指示チェック + 自由入力） ---
        instr_frame = tk.Frame(self._report_body, bg=PANEL_BG)
        instr_frame.pack(fill=tk.X, padx=10, pady=(2, 2))

        self._instr_label = tk.Label(instr_frame, text=t("label.extra_instructions"), bg=PANEL_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE - 1, "bold"), anchor="nw")
        self._instr_label.pack(anchor="w")

        # 保存済み指示チェックボックス行
        self._saved_instr_frame = tk.Frame(instr_frame, bg=PANEL_BG)
        self._saved_instr_frame.pack(fill=tk.X, pady=(2, 2))
        self._saved_instr_vars: list[tuple[tk.BooleanVar, str]] = []
        self._saved_instr_widgets: list[tk.Checkbutton] = []

        # 自由入力欄
        free_row = tk.Frame(instr_frame, bg=PANEL_BG)
        free_row.pack(fill=tk.X, pady=(2, 2))
        free_row.columnconfigure(1, weight=1)
        self._free_input_label = tk.Label(free_row, text=t("label.free_input"), bg=PANEL_BG, fg=MUTED_FG,
                 font=(FONT_FAMILY, FONT_SIZE - 2), anchor="nw")
        self._free_input_label.grid(row=0, column=0, sticky="nw")
        self._custom_instruction = tk.Text(free_row, height=2,
                 bg=INPUT_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 1),
                 insertbackground=TEXT_FG, relief=tk.FLAT, borderwidth=0,
                 wrap=tk.WORD)
        self._custom_instruction.grid(row=0, column=1, sticky="ew", padx=(6, 0), ipady=2)

        free_btn_row = tk.Frame(free_row, bg=PANEL_BG)
        free_btn_row.grid(row=0, column=2, padx=(4, 0), sticky="n")
        self._save_instr_btn = tk.Button(free_btn_row, text=t("btn.save_instruction"),
                  command=self._on_save_instruction,
              bg=BUTTON_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 2),
                  relief=tk.FLAT, padx=4, cursor="hand2")
        self._save_instr_btn.pack(pady=(0, 2))
        self._del_instr_btn = tk.Button(free_btn_row, text=t("btn.delete_instruction"),
                  command=self._on_delete_instruction,
                  bg=BUTTON_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 2),
                  relief=tk.FLAT, padx=4, cursor="hand2")
        self._del_instr_btn.pack()

        # --- 出力形式 + 自動オープン ---
        export_row = tk.Frame(self._report_body, bg=PANEL_BG)
        export_row.pack(fill=tk.X, padx=10, pady=(2, 6))

        self._export_label = tk.Label(export_row, text=t("label.export_format"), bg=PANEL_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE - 1))
        self._export_label.pack(side=tk.LEFT)
        self._export_md_var = tk.BooleanVar(value=True)
        tk.Checkbutton(export_row, text="Markdown", variable=self._export_md_var,
                       bg=PANEL_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
                       activebackground=PANEL_BG, activeforeground=TEXT_FG,
                       font=(FONT_FAMILY, FONT_SIZE - 2)).pack(side=tk.LEFT, padx=(4, 0))
        self._export_docx_var = tk.BooleanVar(value=False)
        tk.Checkbutton(export_row, text="Word (.docx)", variable=self._export_docx_var,
                       bg=PANEL_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
                       activebackground=PANEL_BG, activeforeground=TEXT_FG,
                       font=(FONT_FAMILY, FONT_SIZE - 2)).pack(side=tk.LEFT, padx=(4, 0))
        self._export_pdf_var = tk.BooleanVar(value=False)
        tk.Checkbutton(export_row, text="PDF", variable=self._export_pdf_var,
                       bg=PANEL_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
                       activebackground=PANEL_BG, activeforeground=TEXT_FG,
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
            bg=ACCENT_COLOR, fg=BUTTON_FG,
            font=(FONT_FAMILY, FONT_SIZE, "bold"),
            relief=tk.FLAT, padx=20, pady=6,
            cursor="hand2",
            activebackground="#005a9e", activeforeground=BUTTON_FG,
            state=tk.DISABLED,  # preflight完了まで無効
        )
        self._collect_btn.pack(side=tk.LEFT)

        self._abort_btn = tk.Button(
            btn_frame, text=t("btn.cancel"),
            command=self._on_abort,
            bg=ERROR_COLOR, fg=BUTTON_FG,
            font=(FONT_FAMILY, FONT_SIZE, "bold"),
            relief=tk.FLAT, padx=20, pady=6,
            cursor="hand2",
        )
        # 初期非表示 — _set_working(True) で pack される

        self._refresh_btn = tk.Button(
            btn_frame, text=t("btn.refresh"),
            command=self._on_refresh,
            bg=BUTTON_BG, fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
        )
        self._refresh_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._open_btn = tk.Button(
            btn_frame, text=t("btn.open_file"),
            command=self._on_open_file,
            bg=BUTTON_BG, fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
            state=tk.DISABLED,
        )
        self._open_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._diff_btn = tk.Button(
            btn_frame, text=t("btn.open_diff"),
            command=self._on_open_diff,
            bg=BUTTON_BG, fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
            state=tk.DISABLED,
        )
        self._diff_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._copy_btn = tk.Button(
            btn_frame, text=t("btn.copy_log"),
            command=self._on_copy_log,
            bg=BUTTON_BG, fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
        )
        self._copy_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._clear_log_btn = tk.Button(
            btn_frame, text=t("btn.clear_log"),
            command=self._on_clear_log,
            bg=BUTTON_BG, fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
        )
        self._clear_log_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._login_btn = tk.Button(
            btn_frame, text=t("btn.az_login"),
            command=self._on_az_login,
            bg=BUTTON_BG, fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
        )
        self._login_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._sp_login_btn = tk.Button(
            btn_frame, text=t("btn.sp_login"),
            command=self._on_sp_login,
            bg=BUTTON_BG, fg=TEXT_FG,
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
        self._canvas = tk.Canvas(self._preview_frame, bg=PANEL_BG, highlightthickness=0)
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
        status_frame = tk.Frame(self._root, bg=PANEL_BG)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self._progress = ttk.Progressbar(status_frame, mode="indeterminate", length=100, style="TProgressbar")
        self._progress.pack(side=tk.LEFT, padx=(8, 4), pady=5)

        self._step_var = tk.StringVar(value="")
        tk.Label(status_frame, textvariable=self._step_var,
                 bg=PANEL_BG, fg=ACCENT_COLOR, anchor="w",
                 font=(FONT_FAMILY, FONT_SIZE - 2)).pack(side=tk.LEFT)

        self._status_var = tk.StringVar(value=t("status.ready"))
        tk.Label(status_frame, textvariable=self._status_var,
                 bg=PANEL_BG, fg=TEXT_FG, anchor="w",
                 font=(FONT_FAMILY, FONT_SIZE - 2), padx=8).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._elapsed_var = tk.StringVar(value="")
        tk.Label(status_frame, textvariable=self._elapsed_var,
                 bg=PANEL_BG, fg=TEXT_FG, anchor="e",
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
        data["view_inventory"] = "1" if self._view_inventory_var.get() else "0"
        data["view_network"] = "1" if self._view_network_var.get() else "0"
        data["view_security"] = "1" if self._gen_security_var.get() else "0"
        data["view_cost"] = "1" if self._gen_cost_var.get() else "0"
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

        # View checkboxes
        for key, var in [("view_inventory", self._view_inventory_var),
                         ("view_network", self._view_network_var),
                         ("view_security", self._gen_security_var),
                         ("view_cost", self._gen_cost_var)]:
            saved = load_setting(key, "")
            if saved in ("0", "1"):
                var.set(saved == "1")

        # Legacy: old "view" key migration
        saved_view = load_setting("view", "")
        if saved_view and saved_view in ("inventory", "network", "security-report", "cost-report"):
            # Migrate old format → checkboxes (one-time)
            self._view_inventory_var.set(saved_view == "inventory")
            self._view_network_var.set(saved_view == "network")
            self._gen_security_var.set(saved_view == "security-report")
            self._gen_cost_var.set(saved_view == "cost-report")
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
            timeout_sec = 45 if getattr(sys, "_MEIPASS", None) else 15
            model_ids = list_available_model_ids_sync(
                on_status=lambda s: self._log(s, "info"),
                timeout=timeout_sec,
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
        except Exception as exc:
            self._log(t("log.model_list_error", err=str(exc)[:200]), "warning")
            import traceback
            traceback.print_exc()

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
    # View 切り替え（チェックボックス方式）
    # ------------------------------------------------------------------ #

    def _has_diagram_selected(self) -> bool:
        return self._view_inventory_var.get() or self._view_network_var.get()

    def _has_report_selected(self) -> bool:
        return self._gen_security_var.get() or self._gen_cost_var.get()

    def _selected_diagram_views(self) -> list[str]:
        views: list[str] = []
        if self._view_inventory_var.get():
            views.append("inventory")
        if self._view_network_var.get():
            views.append("network")
        return views

    def _selected_report_views(self, fallback_view: str = "") -> list[str]:
        """Security/Cost の選択状態から report view のリストを返す。"""
        views: list[str] = []
        if self._gen_security_var.get():
            views.append("security-report")
        if self._gen_cost_var.get():
            views.append("cost-report")
        return views or ([fallback_view] if fallback_view else [])

    def _primary_view(self) -> str:
        """後方互換: 内部ロジック用に代表的な view 文字列を返す。"""
        if self._has_report_selected() and not self._has_diagram_selected():
            return "security-report" if self._gen_security_var.get() else "cost-report"
        if self._has_diagram_selected() and not self._has_report_selected():
            return "network" if self._view_network_var.get() else "inventory"
        # mixed or nothing
        return "network" if self._view_network_var.get() else "inventory"

    def _on_view_changed(self, _event: tk.Event | None = None) -> None:
        """View チェックボックス変更時にボタンラベル、説明、フォーム表示を更新。"""
        has_diagram = self._has_diagram_selected()
        has_report = self._has_report_selected()

        # 説明ラベル
        if has_diagram and has_report:
            self._view_desc_var.set(t("view.mixed"))
        elif has_diagram:
            self._view_desc_var.set(t("view.diagram_only"))
        elif has_report:
            self._view_desc_var.set(t("view.report_only"))
        else:
            self._view_desc_var.set(t("view.nothing"))

        # AI 図生成は diagram 選択時のみ有効
        try:
            self._ai_drawio_cb.configure(state=tk.NORMAL if has_diagram else tk.DISABLED)
        except Exception:
            pass

        # diff はレポート用
        if not has_report:
            self._last_diff_path = None
            self._diff_btn.configure(state=tk.DISABLED)
        else:
            if self._last_diff_path and self._last_diff_path.exists() and not self._working:
                self._diff_btn.configure(state=tk.NORMAL)
            else:
                self._diff_btn.configure(state=tk.DISABLED)

        # ボタンラベル
        if has_diagram and has_report:
            self._collect_btn.configure(text=t("btn.generate"))
        elif has_report:
            self._collect_btn.configure(text=t("btn.generate_report"))
        elif has_diagram:
            self._collect_btn.configure(text=t("btn.collect"))
        else:
            self._collect_btn.configure(text=t("btn.generate"))

        # RG / MaxNodes — レポートのみの場合は無効化
        report_only = has_report and not has_diagram
        if report_only:
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
        if has_report:
            self._report_panel.pack(fill=tk.X, padx=12, pady=(0, 4),
                                     before=self._log_area)
            report_type = "security" if self._gen_security_var.get() else "cost"
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
            fallback = bundled_templates_dir() / "saved-instructions.json"
            if fallback != instr_path and fallback.exists():
                try:
                    data = json.loads(fallback.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    return
            else:
                return

        if not isinstance(data, list):
            return

        row, col = 0, 0
        lang = get_language()
        for item in data:
            if not isinstance(item, dict):
                continue
            label = item.get(f"label_{lang}", item.get("label", ""))
            instruction = item.get("instruction", "")
            if not label:
                continue
            var = tk.BooleanVar(value=False)
            self._saved_instr_vars.append((var, instruction))
            cb = tk.Checkbutton(self._saved_instr_frame, text=label,
                                variable=var, bg=PANEL_BG, fg=TEXT_FG,
                                selectcolor=INPUT_BG, activebackground=PANEL_BG,
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
                                variable=var, bg=PANEL_BG, fg=TEXT_FG,
                                selectcolor=INPUT_BG, activebackground=PANEL_BG,
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
        instr_path = user_saved_instructions_path()
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

        if not isinstance(data, list):
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
        instr_path = user_saved_instructions_path()

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

        if not isinstance(data, list):
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
        filtered: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get("instruction", "") in to_delete:
                continue
            filtered.append(item)
        data = filtered
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
            try:
                open_native(d)
            except Exception as exc:
                self._log(t("log.open_failed", err=str(exc)[:200]), "warning")

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
        """ストリーミング用: デルタをバッファに溜め、100ms間隔で一括挿入。

        高頻度の root.after(0, ...) がタイマー(_tick_elapsed)を圧迫するのを防ぐ。
        """
        self._delta_buffer.append(delta)
        if not self._delta_flush_scheduled:
            self._delta_flush_scheduled = True
            self._root.after(100, self._flush_delta_buffer)

    def _flush_delta_buffer(self) -> None:
        """バッファに溜まったデルタを一括でログエリアに挿入する。"""
        self._delta_flush_scheduled = False
        # アトミックなバッファスワップ（STORE_ATTR は GIL 下で単一命令）
        # ワーカースレッドの append() との競合を防ぐ
        buf = self._delta_buffer
        self._delta_buffer = []
        if not buf:
            return
        chunk = "".join(buf)
        self._log_area.configure(state=tk.NORMAL)
        self._log_area.insert(tk.END, chunk, "info")
        self._log_area.see(tk.END)
        self._log_area.configure(state=tk.DISABLED)

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
                self._progress.configure(mode="indeterminate")
                self._progress.start(12)
                self._start_timer()
            else:
                self._abort_btn.pack_forget()
                self._collect_btn.pack(side=tk.LEFT, before=self._refresh_btn)
                self._refresh_btn.configure(state=tk.NORMAL)
                self._progress.stop()
                # 完了時は determinate + 100% で「完了」を視覚的に示す
                self._progress.configure(mode="determinate", maximum=100, value=100)
                self._stop_timer()
                self._set_step("")
                self._elapsed_var.set("")
                # ステータスが「生成中」のまま残るのを防ぐ
                cur = self._status_var.get()
                generating_keywords = ("generating", "collecting", "running", "reviewing",
                                       "normalizing", "saving", "choosing", "生成中", "収集中",
                                       "実行中", "レビュー")
                if cur and any(kw in cur.lower() for kw in generating_keywords):
                    self._status_var.set(t("status.done") if self._last_out_path else "")
                # 残留デルタバッファをフラッシュ
                if self._delta_buffer:
                    self._flush_delta_buffer()
        self._root.after(0, _do)

    def _on_abort(self) -> None:
        """収集中にCancelボタンを押した場合。"""
        self._cancel_event.set()
        self._log(t("log.cancel_requested"), "warning")
        self._set_status(t("status.cancelling"))
        self._set_working(False)

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
                code, _out, err = run_az_command(["login"], timeout_s=120)
                if code == 0:
                    self._log(t("log.az_login_success"), "success")
                    # Sub/RG をクリア
                    self._root.after(0, lambda: self._sub_var.set(""))
                    self._root.after(0, lambda: self._rg_var.set(""))
                    self._root.after(0, lambda: self._sub_combo.configure(values=[]))
                    self._root.after(0, lambda: self._rg_combo.configure(values=[]))
                    self._bg_preflight()
                else:
                    self._log(t("log.az_login_failed", err=(err or "")[:200]), "error")
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

            # Entry の内容はすぐ消しておく（Secret を画面/メモリに残しにくくする）
            try:
                secret_var.set("")
            except Exception:
                pass

            _close()

            def _do_login(*, sp_client_id: str, sp_tenant_id: str, sp_secret: str) -> None:
                self._log(t("log.sp_login_running"), "info")
                self._root.after(0, lambda: self._login_btn.configure(state=tk.DISABLED))
                self._root.after(0, lambda: self._sp_login_btn.configure(state=tk.DISABLED))
                try:
                    cmd: list[str] = [
                        "login", "--service-principal",
                        "-u", sp_client_id, "-p", sp_secret, "--tenant", sp_tenant_id,
                    ]
                    code, _out, err = run_az_command(cmd, timeout_s=120)
                    if code == 0:
                        self._log(t("log.sp_login_success"), "success")
                        # Sub/RG をクリアして再ロード
                        self._root.after(0, lambda: self._sub_var.set(""))
                        self._root.after(0, lambda: self._rg_var.set(""))
                        self._root.after(0, lambda: self._sub_combo.configure(values=[]))
                        self._root.after(0, lambda: self._rg_combo.configure(values=[]))
                        self._bg_preflight()
                    else:
                        err_short = (err or "").strip()[:200]
                        self._log(t("log.sp_login_failed", err=err_short), "error")
                except Exception as e:
                    self._log(t("log.sp_login_failed", err=str(e)), "error")
                finally:
                    self._root.after(0, lambda: self._login_btn.configure(state=tk.NORMAL))
                    self._root.after(0, lambda: self._sp_login_btn.configure(state=tk.NORMAL))

            threading.Thread(
                target=_do_login,
                kwargs={
                    "sp_client_id": client_id,
                    "sp_tenant_id": tenant_id,
                    "sp_secret": secret,
                },
                daemon=True,
            ).start()
            secret = ""  # ベストエフォートで参照を落とす

        tk.Button(btns, text=t("btn.login"), command=_login,
                  bg=ACCENT_COLOR, fg=BUTTON_FG, font=(FONT_FAMILY, FONT_SIZE, "bold"),
                  relief=tk.FLAT, padx=16, pady=6, cursor="hand2").pack(side=tk.LEFT)
        tk.Button(btns, text=t("btn.cancel_small"), command=_close,
                  bg=BUTTON_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE),
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
        try:
            limit = int(self._limit_var.get().strip())
        except ValueError:
            limit = 300

        # Azure Resource Graph の取得上限に合わせてクランプ
        requested_limit = limit
        if limit < 1:
            limit = 1
        if limit > 1000:
            limit = 1000
            self._log(t("log.limit_clamped", requested=requested_limit, applied=limit), "warning")

        diagram_views = self._selected_diagram_views()
        report_views = self._selected_report_views()

        if not diagram_views and not report_views:
            self._log(t("view.nothing"), "warning")
            return

        # 後方互換: worker に渡す代表 view
        view = self._primary_view()

        self._cancel_event.clear()

        # 前回の差分ファイルは新規実行でクリア（誤って古いdiffを開かない）
        self._last_diff_path = None
        self._diff_btn.configure(state=tk.DISABLED)

        self._set_working(True)

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
        targets = [v for v in diagram_views] + [v for v in report_views]
        self._log(t("log.targets", targets=", ".join(targets)), "accent")
        if sub:
            self._log(t("log.subscription", subscription=sub))
        if rg:
            self._log(t("log.resource_group", rg=rg))
        if diagram_views:
            self._log(t("log.limit", limit=limit))

        # --- GUI 変数のスナップショット (review #1/#2) ---
        # tkinter は単一スレッドモデル。ワーカースレッドから StringVar.get() を
        # 呼ぶのは未定義動作になり得るため、UI スレッドで全変数を取得してから渡す。
        worker_opts: dict[str, Any] = {
            "model_id": self._model_var.get().strip() or None,
            "ai_drawio": bool(self._ai_drawio_var.get()),
            "export_svg": bool(self._export_svg_var.get()),
            "export_docx": bool(self._export_docx_var.get()),
            "export_pdf": bool(self._export_pdf_var.get()),
            "auto_open": bool(self._auto_open_var.get()),
            "output_dir": self._output_dir_var.get().strip(),
            "sub_display": self._sub_var.get().strip(),
            "rg_display": rg or "",
            "open_app": self._open_app_var.get(),
        }

        threading.Thread(
            target=self._worker_collect,
            args=(sub, rg, limit, view, report_views, diagram_views, worker_opts),
            daemon=True,
        ).start()

    def _worker_collect(self, sub: str | None, rg: str | None, limit: int, view: str = "inventory",
                        report_views: list[str] | None = None,
                        diagram_views: list[str] | None = None,
                        opts: dict[str, Any] | None = None) -> None:
        """収集ワーカー。完了後にレビュー画面を表示して待つ。"""
        if opts is None:
            opts = {}
        try:
            diagram_results: list[tuple[str, Path, dict[str, Any]]] = []  # (view, out_path, summary)
            generated_reports: list[tuple[str, Path]] = []  # (report_type, path)

            # 図の生成（1つ以上の diagram view）
            diagram_list: list[str] = list(diagram_views) if diagram_views else []

            first_diagram = True
            for dv in diagram_list:
                if self._cancel_event.is_set():
                    self._log(t("log.cancelled"), "warning")
                    return
                if not first_diagram:
                    self._log("─" * 40, "accent")
                first_diagram = False
                result = self._worker_single_diagram(sub, rg, limit, dv, opts=opts)
                if result:
                    out_path, summary = result
                    diagram_results.append((dv, out_path, summary))

            # 図が終わったらレポートも（同時選択時 or レポートのみ）
            if report_views:
                self._log("─" * 40, "accent")
                if len(report_views) > 1:
                    self._log(t("log.multi_report_start", count=len(report_views)), "info")
                generated_reports = self._worker_reports(sub, rg, limit, report_views, opts=opts)

            # 複数出力があれば統合レポートを生成
            if not self._cancel_event.is_set() and (len(diagram_results) + len(generated_reports) >= 2):
                self._generate_integrated_report(sub, diagram_results, generated_reports, opts=opts)

        except Exception as e:
            self._log(f"ERROR: {e}", "error")
            self._set_status(t("status.error"))
        finally:
            self._set_working(False)

    def _worker_single_diagram(self, sub: str | None, rg: str | None, limit: int, view: str,
                                *, opts: dict[str, Any] | None = None) -> tuple[Path, dict[str, Any]] | None:
        """単一の diagram view を収集→生成する（_worker_collect から呼ばれる）。"""
        if opts is None:
            opts = {}
        self._log(f"  📊 Diagram: {view}", "accent")

        # Step 1: Collect
        self._set_step("Step 1/6: Collect")
        self._set_status(t("status.running_query"))
        self._log(t("log.query_running", view=view), "info")

        def _check_cancel(msg: str) -> None:
            if self._cancel_event.is_set():
                raise RuntimeError("Cancelled")
            self._log(f"    {msg}", "info")

        nodes, collected_edges, meta = collect_diagram_view(
            view=view,
            subscription=sub,
            resource_group=rg,
            limit=limit,
            on_progress=_check_cancel,
        )
        if view == "network":
            self._log(t("log.net_resources_found", nodes=len(nodes), edges=len(collected_edges)), "success")
        else:
            self._log(t("log.resources_found", count=len(nodes)), "success")

        if self._cancel_event.is_set():
            self._log(t("log.cancelled"), "warning")
            return None

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
        self._set_step("Step 2/6: AI Review")
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
                model_id=opts.get("model_id"),
            )
        except Exception as e:
            self._log(t("log.ai_review_skip", err=str(e)), "warning")

        self._log("", "info")  # 改行
        self._log("─" * 40, "accent")

        if self._cancel_event.is_set():
            self._log(t("log.cancelled"), "warning")
            return None

        # NOTE:
        # 図生成では Proceed/Cancel の確認を挟まず、自動で次へ進む。

        # Step 2: 保存先決定（Output Dir設定済みなら自動、未設定ならダイアログ）
        self._set_step("Step 3/6: Output")
        self._set_status(t("status.choosing_output"))
        initial_dir = opts.get("output_dir", "")
        default_name = self._make_filename(f"env-{view}", sub, rg, ".drawio")

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
            done_event.wait(timeout=300)  # 5分でタイムアウト (review #14)

            if not out_path_holder:
                self._log(t("log.save_not_selected"), "warning")
                self._set_status(t("status.cancelled"))
                return None
            out_path = Path(out_path_holder[0])

        # Step 3: Normalize + Preprocess
        self._set_step("Step 4/6: Normalize")
        self._set_status(t("status.normalizing"))
        edges: list[Edge] = collected_edges

        # ノード前処理: ノイズ除去 + 類似リソースグルーピング
        pp_nodes, pp_edges, pp_groups = preprocess_nodes(nodes, edges)
        if pp_groups:
            for g in pp_groups:
                if g["type"] == "noise":
                    self._log(f"    \u26a1 {g['prefix']}: {g['total']} noise resources removed", "info")
                else:
                    shown = len(g["representative"])
                    self._log(f"    \u26a1 {g['prefix']}: {g['total']} resources \u2192 {shown} shown + summary", "info")
        nodes = pp_nodes
        edges = pp_edges

        azure_to_cell_id = {n.azure_id: cell_id_for_azure_id(n.azure_id) for n in nodes}

        # Step 4: Build XML
        self._set_step("Step 5/6: Build XML")
        diagram_name = f"{view}-{now_stamp()}"
        xml: str | None = None

        # AI mode (preferred)
        if opts.get("ai_drawio"):
            try:
                from ai_reviewer import run_drawio_generation

                self._set_status(t("status.ai_generating_xml"))

                nodes_for_ai = [
                    {
                        "id": n.azure_id,
                        "cellId": azure_to_cell_id.get(n.azure_id),
                        "name": n.name,
                        "type": n.type,
                        "resourceGroup": n.resource_group,
                        "location": n.location,
                    }
                    for n in nodes
                ]

                edges_for_ai: list[dict[str, Any]] = []
                for e in edges:
                    src = azure_to_cell_id.get(e.source)
                    tgt = azure_to_cell_id.get(e.target)
                    if not src or not tgt:
                        continue
                    edges_for_ai.append({
                        "source": e.source,
                        "target": e.target,
                        "kind": e.kind,
                        "sourceCellId": src,
                        "targetCellId": tgt,
                    })

                diagram_request: dict[str, Any] = {
                    "diagramName": diagram_name,
                    "view": view,
                    "subscription": sub,
                    "resourceGroup": rg,
                    "nodes": nodes_for_ai,
                    "edges": edges_for_ai,
                    "preprocessed": True,
                    "groups": [
                        {"prefix": g["prefix"], "type": g["type"], "total": g["total"]}
                        for g in pp_groups
                    ] if pp_groups else [],
                    "rules": {
                        "requireAzure2Icons": True,
                        "preferContainers": True,
                    },
                }

                ai_xml = run_drawio_generation(
                    diagram_request,
                    on_status=lambda s: self._log(s, "info"),
                    model_id=opts.get("model_id"),
                )
                if ai_xml:
                    xml = ai_xml
                else:
                    self._log(t("log.ai_drawio_fallback"), "warning")
            except Exception:
                self._log(t("log.ai_drawio_fallback"), "warning")

        # Deterministic fallback
        if not xml:
            self._set_status(t("status.generating_xml"))
            self._log(t("log.generating_xml"))
            xml = build_drawio_xml(
                nodes=nodes, edges=edges,
                azure_to_cell_id=azure_to_cell_id,
                diagram_name=diagram_name,
            )

        # Step 5: Save
        self._set_step("Step 6/6: Save")
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
        env_json_path = out_path.with_name(out_path.stem + "-env.json")
        write_json(env_json_path, env_payload)
        self._log(f"  → {env_json_path}", "success")

        collect_log_path = out_path.with_name(out_path.stem + "-collect-log.json")
        write_json(collect_log_path, {"tool": "az graph query", "meta": meta})
        self._log(f"  → {collect_log_path}", "success")

        # SVG エクスポート
        if opts.get("export_svg"):
            svg_result, svg_err = export_drawio_svg(out_path)
            if svg_result:
                self._log(f"  → {svg_result}", "success")
            elif svg_err:
                self._log(t("log.svg_export_failed", err=svg_err[:200]), "warning")
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
        if opts.get("auto_open") and out_path.exists():
            open_choice = (opts.get("open_app") if isinstance(opts, dict) else None) or None
            self._root.after(500, lambda p=out_path, c=open_choice: self._open_file_with(p, choice_override=c))

        # 統合レポート用に、最小のサマリ情報を返す
        try:
            compact_type_summary = type_summary(nodes)
            samples = [
                {
                    "name": n.name,
                    "type": n.type,
                    "resourceGroup": n.resource_group,
                    "location": n.location,
                }
                for n in nodes[:30]
            ]
            diagram_summary: dict[str, Any] = {
                "view": view,
                "drawio": out_path.name,
                "nodes": len(nodes),
                "edges": len(edges),
                "typeSummary": compact_type_summary,
                "sampleResources": samples,
            }
        except Exception:
            diagram_summary = {"view": view, "drawio": out_path.name}

        return out_path, diagram_summary

    @staticmethod
    def _pick_standard_template(report_type: str) -> dict | None:
        from ai_reviewer import list_templates
        templates = list_templates(report_type)
        if not templates:
            return None
        for tmpl in templates:
            if str(tmpl.get("template_name", "")).strip().lower() == "standard":
                return tmpl
        return templates[0]

    def _worker_reports(self, sub: str | None, rg: str | None, limit: int, views: list[str],
                        *, opts: dict[str, Any] | None = None) -> list[tuple[str, Path]]:
        total = len(views)
        generated_reports: list[tuple[str, Path]] = []  # (report_type, path)

        for idx, view in enumerate(views, start=1):
            if self._cancel_event.is_set():
                return generated_reports

            # 複数生成時は常に Standard テンプレ（既定セクション）を使用
            template_override: dict | None = None
            if total > 1:
                report_type = "security" if view == "security-report" else "cost"
                template_override = self._pick_standard_template(report_type)
                self._log(t("log.multi_report_template", name=report_type), "info")

            if total > 1:
                name = "security" if view == "security-report" else "cost"
                self._log(t("log.multi_report_item", index=idx, total=total, name=name), "accent")

            # 複数レポート生成中は、各レポート完了ごとの自動オープンを抑制する
            # （途中で別アプリが起動して体験が悪くなる / まだ次のレポート生成中など）
            item_opts = dict(opts or {})
            if total > 1:
                item_opts["auto_open"] = False

            result_path = self._worker_report(
                sub,
                rg,
                limit,
                view,
                template_override=template_override,
                opts=item_opts,
            )
            if result_path:
                rtype = "security" if view == "security-report" else "cost"
                generated_reports.append((rtype, result_path))

        return generated_reports

    def _generate_integrated_report(
        self,
        sub: str | None,
        diagram_results: list[tuple[str, Path, dict[str, Any]]],
        generated_reports: list[tuple[str, Path]],
        *,
        opts: dict[str, Any] | None = None,
    ) -> None:
        """複数ビュー（図/レポート）を統合したレポートを生成・保存する。"""
        try:
            self._set_step(t("step.integrated"))
            self._set_status(t("status.generating_integrated"))
            self._log("═" * 50, "accent")
            self._log(
                t(
                    "log.integrated_start",
                    diagrams=len(diagram_results),
                    reports=len(generated_reports),
                ),
                "info",
            )

            # 各レポートの本文を読み込み
            report_contents: list[tuple[str, str]] = []
            for rtype, path in generated_reports:
                try:
                    content = path.read_text(encoding="utf-8")
                    report_contents.append((rtype, content))
                    self._log(t("log.integrated_read_report", type=rtype, path=path.name), "info")
                except Exception as e:
                    self._log(f"  Skip {rtype}: {e}", "warning")

            # 図サマリを整形
            diagram_summaries: list[dict[str, Any]] = []
            for dv, out_path, summary in diagram_results:
                base = {"view": dv, "path": out_path.name}
                if isinstance(summary, dict):
                    base.update(summary)
                diagram_summaries.append(base)

            if (len(diagram_summaries) + len(report_contents)) < 2:
                return

            sub_display = opts.get("sub_display", "") if opts else ""
            if not sub_display or sub_display == t("hint.all_subscriptions"):
                sub_display = sub or ""

            self._log(t("log.integrated_ai_gen"), "info")
            self._log("─" * 40, "accent")

            # 差分レポートがあれば統合レポートに含める
            diff_contents: list[tuple[str, str]] = []
            for rtype, path in generated_reports:
                try:
                    diff_path = path.with_name(path.stem + "-diff.md")
                    if diff_path.exists():
                        diff_md = diff_path.read_text(encoding="utf-8")
                        # unified diff は巨大になりやすいので、要約セクションのみ渡す
                        # 1) ```diff フェンスがあればそこから先を落とす（フェンス破断を避ける）
                        fence = "```diff"
                        if fence in diff_md:
                            diff_md = diff_md.split(fence, 1)[0].rstrip() + "\n"
                        else:
                            # 2) セクション見出しで落とす（前後改行の有無に依存しない）
                            for marker in ("## 詳細 Diff", "## Detailed Diff"):
                                idx = diff_md.find(marker)
                                if idx >= 0:
                                    diff_md = diff_md[:idx].rstrip() + "\n"
                                    break
                        # 念のため文字数上限を設ける（コンテキスト肥大化の回避）
                        if len(diff_md) > 4000:
                            diff_md = diff_md[:4000].rstrip() + "\n…(truncated)\n"
                        diff_contents.append((rtype, diff_md))
                        self._log(t("log.integrated_read_diff", type=rtype, path=diff_path.name), "info")
                except Exception:
                    pass  # diff is best-effort

            integrated_result: str | None = None
            try:
                from ai_reviewer import run_integrated_report
                rg_display = opts.get("rg_display", "") if opts else ""

                integrated_result = run_integrated_report(
                    diagram_summaries=diagram_summaries,
                    report_contents=report_contents,
                    diff_contents=diff_contents if diff_contents else None,
                    on_delta=lambda d: self._log_append_delta(d),
                    on_status=lambda s: self._log(s, "info"),
                    model_id=opts.get("model_id") if opts else None,
                    subscription_info=sub_display,
                    resource_group=rg_display,
                )
            except Exception as e:
                self._log(f"  AI integrated skipped: {e}", "warning")

            self._log("", "info")
            self._log("─" * 40, "accent")

            if not integrated_result:
                self._log(t("log.integrated_fallback"), "warning")
                integrated_result = self._build_integrated_report_fallback(
                    sub_display=sub_display,
                    diagram_summaries=diagram_summaries,
                    report_paths=generated_reports,
                    rg_display=opts.get("rg_display", "") if opts else "",
                )
            if not integrated_result:
                self._log(t("log.integrated_failed"), "warning")
                return

            # 保存先は最初に生成できた成果物（図 or レポート）と同じディレクトリ
            first_path: Path | None = None
            if diagram_results:
                first_path = diagram_results[0][1]
            elif generated_reports:
                first_path = generated_reports[0][1]
            if not first_path:
                return
            out_dir = first_path.parent
            rg_for_filename = opts.get("rg_display", "") if opts else ""
            rg_val = rg_for_filename or None
            out_name = self._make_filename("integrated-report", sub, rg_val, ".md")
            out_path = out_dir / out_name
            # 未使用脚注などをベストエフォートでクリーンアップ
            try:
                from exporter import remove_unused_footnote_definitions, validate_markdown

                integrated_result, removed = remove_unused_footnote_definitions(integrated_result)
                if removed:
                    self._log(
                        ("  ℹ 未使用の脚注定義を削除: " + ", ".join(removed))
                        if get_language() != "en"
                        else ("  ℹ Removed unused footnote definitions: " + ", ".join(removed)),
                        "info",
                    )

                md_warnings = validate_markdown(integrated_result)
                if md_warnings:
                    self._log("⚠ Markdown validation:", "warning")
                    for w in md_warnings:
                        self._log(f"  {w}", "warning")
                else:
                    self._log("✓ Markdown validation: OK", "success")
            except Exception:
                pass

            write_text(out_path, integrated_result)
            self._last_out_path = out_path
            self._log(f"  → {out_path}", "success")

            # Word 出力（オプション）
            if opts.get("export_docx") if opts else False:
                try:
                    from exporter import md_to_docx
                    docx_path = out_path.with_suffix(".docx")
                    md_to_docx(integrated_result, docx_path)
                    self._log(t("log.word_output", path=str(docx_path)), "success")
                except Exception as e:
                    self._log(t("log.word_error", err=str(e)), "warning")

            self._root.after(0, lambda: self._open_btn.configure(state=tk.NORMAL))
            self._log(t("log.integrated_done"), "success")

            if opts.get("auto_open") and out_path.exists() if opts else False:
                open_choice = (opts.get("open_app") if isinstance(opts, dict) else None) or None
                self._root.after(500, lambda p=out_path, c=open_choice: self._open_file_with(p, choice_override=c))

        except Exception as e:
            self._log(f"Integrated ERROR: {e}", "error")

    def _build_integrated_report_fallback(
        self,
        *,
        sub_display: str,
        diagram_summaries: list[dict[str, Any]],
        report_paths: list[tuple[str, Path]],
        rg_display: str = "",
    ) -> str:
        """AIなしでも最低限読める統合レポート（Markdown）を生成する。"""
        en = get_language() == "en"
        lines: list[str] = []
        lines.append("# Azure Environment Integrated Report" if en else "# Azure 環境 統合レポート")
        if sub_display:
            lines.append(f"- Subscription: {sub_display}")

        if rg_display:
            lines.append(f"- Resource Group: {rg_display}")
        lines.append("")

        if diagram_summaries:
            lines.append("## Diagram Summaries" if en else "## 図サマリ")
            for ds in diagram_summaries:
                view = str(ds.get("view", ""))
                nodes = ds.get("nodes")
                edges = ds.get("edges")
                drawio = ds.get("drawio") or ds.get("path") or ""
                lines.append(f"- {view}: {nodes} nodes / {edges} edges ({drawio})")
            lines.append("")

        if report_paths:
            lines.append("## Generated Reports" if en else "## 生成レポート")
            for rtype, path in report_paths:
                lines.append(f"- {rtype}: {path.name}")
            lines.append("")

        lines.append("## Priority Actions (Draft)" if en else "## 優先アクション (暫定)")
        if en:
            lines.append("- Quick win: Identify and remove unused resources")
            lines.append("- Quick win: Triage and remediate Critical/High security findings")
            lines.append("- Strategic: Re-validate network boundaries and access control design")
            lines.append("- Strategic: Establish cost allocation (tags/policies) and continuous monitoring")
            lines.append("- Strategic: Create an execution plan (owner/due date/impact metrics)")
        else:
            lines.append("- Quick win: 不要/未使用リソースの棚卸しと削除候補の抽出")
            lines.append("- Quick win: セキュリティの Critical/High を先に潰す")
            lines.append("- Strategic: ネットワーク境界とアクセス制御の設計再確認")
            lines.append("- Strategic: コスト配賦（タグ/ポリシー）と継続的モニタリング")
            lines.append("- Strategic: 改善の実行計画（担当/期限/効果測定）")
        lines.append("")

        lines.append("---")
        lines.append(
            "Note: AI integrated generation was unavailable; this is a basic fallback. Please refer to individual outputs for details."
            if en
            else "※ AI 統合が利用できなかったため簡易版です。詳細は個別成果物を参照してください。"
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Canvas プレビュー
    # ------------------------------------------------------------------ #

    def _draw_preview(self, nodes: list[Node], edges: list[Edge],
                      azure_to_cell_id: dict[str, str]) -> None:
        """ログエリアの下にCanvasで簡易描画。色はdrawio_writerと同じ。"""
        from drawio_writer import get_type_icon, color_for_type

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
                    if get_type_icon(node.type):
                        type_colors[node.type] = "#0078d4"  # Azure Blue
                    else:
                        type_colors[node.type] = color_for_type(node.type)

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

                color = type_colors.get(node.type, BUTTON_BG)
                display_name = node.name[:14] + "…" if len(node.name) > 14 else node.name
                short_type = node.type.split("/")[-1] if "/" in node.type else node.type

                self._canvas.create_rectangle(
                    px, py, px + cell_w, py + cell_h,
                    fill=color, outline="#555555", width=1,
                )
                self._canvas.create_text(
                    px + cell_w / 2, py + cell_h / 2,
                    text=f"{display_name}\n{short_type}",
                    fill=BUTTON_FG, font=(FONT_FAMILY, 6),
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
            try:
                self._root.clipboard_clear()
                self._root.clipboard_append(content)
                self._set_status(t("status.log_copied"))
            except Exception as exc:
                self._log(t("log.clipboard_failed", err=str(exc)[:200]), "warning")

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

    def _open_file_with(self, path: Path, *, choice_override: str | None = None) -> None:
        """Open App 設定に応じてファイルを開く。"""
        choice = choice_override or self._open_app_var.get()
        suffix = path.suffix.lower()
        is_drawio = suffix == ".drawio" or path.name.lower().endswith(".drawio.svg")

        def _open_notepad_if_possible() -> bool:
            # レポート(.md) などを OS 既定で開くと、環境によっては Draw.io が関連付いて
            # しまい誤起動することがあるため、Windows では安全側に Notepad を使う。
            if sys.platform != "win32":
                return False
            if suffix not in (".md", ".json", ".txt"):
                return False
            try:
                subprocess.Popen(["notepad.exe", str(path)], **_subprocess_no_window())
                return True
            except Exception:
                return False

        def _open_os_default() -> None:
            try:
                open_native(path)
            except Exception as exc:
                self._log(t("log.open_failed", err=str(exc)[:200]), "warning")

        def _try_popen(exe_path: str) -> bool:
            try:
                subprocess.Popen([exe_path, str(path)], **_subprocess_no_window())
                return True
            except Exception as exc:
                self._log(t("log.open_failed", err=str(exc)[:200]), "warning")
                return False

        if choice == "auto":
            if is_drawio:
                # Draw.io があればそれ、なければ VS Code、それもなければ OS既定
                dp = cached_drawio_path()
                if dp and _try_popen(dp):
                    return
                vp = cached_vscode_path()
                if vp and _try_popen(vp):
                    return
                _open_os_default()
                return

            # Markdown 等は VS Code を優先（OS 側の関連付けが無い/不安定でも開ける）
            vp = cached_vscode_path()
            if vp and _try_popen(vp):
                return
            _open_os_default()
            if _open_notepad_if_possible():
                return

        elif choice == "drawio":
            # Draw.io は .drawio（および .drawio.svg）以外を開く用途に向かないため、
            # Markdown 等は VS Code/OS 既定で開く。
            if not is_drawio:
                vp = cached_vscode_path()
                if vp and _try_popen(vp):
                    return
                if _open_notepad_if_possible():
                    return
                # 非 drawio を Draw.io に渡さないことを最優先（Invalid file data 回避）
                _open_os_default()
                return
            dp = cached_drawio_path()
            if dp:
                if not _try_popen(dp):
                    _open_os_default()
            else:
                self._log(t("log.drawio_not_found"), "warning")
                _open_os_default()

        elif choice == "vscode":
            vp = cached_vscode_path()
            if vp:
                if not _try_popen(vp):
                    if not _open_notepad_if_possible():
                        _open_os_default()
            else:
                self._log(t("log.vscode_not_found"), "warning")
                if not _open_notepad_if_possible():
                    _open_os_default()

        else:  # "os"
            _open_os_default()

    # ------------------------------------------------------------------ #
    # レポート生成ワーカー (security-report / cost-report)
    # ------------------------------------------------------------------ #

    def _worker_report(self, sub: str | None, rg: str | None, limit: int, view: str,
                       template_override: dict | None = None,
                       opts: dict[str, Any] | None = None) -> Path | None:
        """Security / Cost レポート生成ワーカー。成功時は保存パスを返す。"""
        try:
            # テンプレートとカスタム指示をUIスレッドで取得
            template = template_override if template_override is not None else self._get_current_template_with_overrides()
            custom_instruction = self._get_custom_instruction()

            # サブスクリプション表示名（AIがレポートタイトルに使う）
            sub_display = opts.get("sub_display", "") if opts else ""
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
            security_data: dict[str, Any] = {}
            cost_data: dict[str, Any] = {}
            advisor_data: dict[str, Any] = {}

            if view == "security-report":
                self._set_status(t("status.collecting_sec"))
                self._log(t("log.sec_collecting"), "info")
                try:
                    security_data = collect_security(sub)
                except Exception as e:
                    self._log(t("log.sec_collect_failed", err=str(e)), "warning")
                    security_data = {"error": str(e)}
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
                        model_id=opts.get("model_id") if opts else None,
                        subscription_info=sub_display,
                    )
                except Exception as e:
                    self._log(t("log.ai_report_error", err=str(e)), "error")

            elif view == "cost-report":
                self._set_status(t("status.collecting_cost"))
                self._log(t("log.cost_collecting"), "info")
                try:
                    cost_data = collect_cost(sub)
                except Exception as e:
                    self._log(t("log.cost_collect_failed", err=str(e)), "warning")
                    cost_data = {"error": str(e)}
                svc = cost_data.get("cost_by_service")
                if svc:
                    self._log(t("log.cost_by_svc", count=len(svc)), "info")
                rg_cost = cost_data.get("cost_by_rg")
                if rg_cost:
                    self._log(t("log.cost_by_rg", count=len(rg_cost)), "info")

                self._log(t("log.advisor_collecting"), "info")
                try:
                    advisor_data = collect_advisor(sub)
                except Exception as e:
                    self._log(t("log.advisor_collect_failed", err=str(e)), "warning")
                    advisor_data = {"error": str(e)}
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
                        model_id=opts.get("model_id") if opts else None,
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

            # 保存（Output Dir設定済みなら自動、未設定ならダイアログ）
            self._set_step("Step 3/3: Save")
            report_type = "security" if view == "security-report" else "cost"
            default_name = self._make_filename(f"{report_type}-report", sub, rg, ".md")
            initial_dir = opts.get("output_dir", "") if opts else ""

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
                done_event.wait(timeout=300)  # 5分でタイムアウト (review #14)

                if not out_path_holder:
                    self._log(t("log.save_not_selected"), "warning")
                    self._set_status(t("status.cancelled"))
                    return
                out_path = Path(out_path_holder[0])
            write_text(out_path, report_result)
            # 未使用脚注などをベストエフォートでクリーンアップ（保存後の diff/再現性は維持）
            try:
                from exporter import remove_unused_footnote_definitions

                cleaned, removed = remove_unused_footnote_definitions(report_result)
                if removed and cleaned.strip() != report_result.strip():
                    report_result = cleaned
                    write_text(out_path, report_result)
                    self._log(
                        ("  ℹ 未使用の脚注定義を削除: " + ", ".join(removed))
                        if get_language() != "en"
                        else ("  ℹ Removed unused footnote definitions: " + ", ".join(removed)),
                        "info",
                    )
            except Exception:
                pass
            self._last_out_path = out_path
            self._log(f"  → {out_path}", "success")

            # Markdown バリデーション（機械チェック）
            try:
                from exporter import validate_markdown
                md_warnings = validate_markdown(report_result)
                if md_warnings:
                    self._log("⚠ Markdown validation:", "warning")
                    for w in md_warnings:
                        self._log(f"  {w}", "warning")
                else:
                    self._log("✓ Markdown validation: OK", "success")
            except Exception:
                pass

            # レポート入力（収集データ/テンプレ/指示）を隣に保存（再生成・監査用）
            try:
                from ai_reviewer import get_last_run_debug
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
                    "ai_debug": get_last_run_debug(),
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
            if opts.get("export_docx") if opts else False:
                try:
                    from exporter import md_to_docx
                    docx_path = out_path.with_suffix(".docx")
                    md_to_docx(report_result, docx_path)
                    self._log(t("log.word_output", path=str(docx_path)), "success")
                except Exception as e:
                    self._log(t("log.word_error", err=str(e)), "warning")

            if opts.get("export_pdf") if opts else False:
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
            if opts.get("auto_open") and out_path.exists() if opts else False:
                open_choice = (opts.get("open_app") if isinstance(opts, dict) else None) or None
                self._root.after(500, lambda p=out_path, c=open_choice: self._open_file_with(p, choice_override=c))

            return out_path

        except Exception as e:
            self._log(f"ERROR: {e}", "error")
            self._set_status(t("status.error"))
            return None

    # ------------------------------------------------------------------ #
    # 言語切替ハンドラ
    # ------------------------------------------------------------------ #

    def _on_language_changed(self) -> None:
        """言語ラジオボタン変更時にUIテキストを更新。"""
        lang = self._lang_var.get()
        set_language(lang)
        self._refresh_ui_texts()
        # テンプレートパネルのセクション名・指示ラベルを再描画
        if self._has_report_selected():
            report_type = "security" if self._gen_security_var.get() else "cost"
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

        # Diagram options
        self._ai_drawio_cb.configure(text=t("opt.ai_drawio_layout"))

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
        self._abort_btn.configure(text=t("btn.cancel"))
        self._auto_open_main_cb.configure(text=t("btn.auto_open"))

        # レポートパネル
        self._instr_label.configure(text=t("label.extra_instructions"))
        self._free_input_label.configure(text=t("label.free_input"))
        self._save_instr_btn.configure(text=t("btn.save_instruction"))
        self._del_instr_btn.configure(text=t("btn.delete_instruction"))
        self._export_label.configure(text=t("label.export_format"))
        self._save_tmpl_btn.configure(text=t("btn.save_template"))
        self._import_tmpl_btn.configure(text=t("btn.import_template"))
        # View チェックボックス
        self._view_inventory_cb.configure(text=t("opt.inventory_diagram"))
        self._view_network_cb.configure(text=t("opt.network_diagram"))
        self._gen_security_cb.configure(text=t("opt.security_report"))
        self._gen_cost_cb.configure(text=t("opt.cost_report"))

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
