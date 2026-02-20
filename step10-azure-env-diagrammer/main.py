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

import json
import os
import shutil
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
    list_resource_groups,
    list_subscriptions,
    preflight_check,
    type_summary,
)
from drawio_writer import build_drawio_xml, now_stamp

from app_paths import ensure_user_dirs, saved_instructions_path, user_templates_dir


# ============================================================
# 定数
# ============================================================

WINDOW_TITLE = "Azure Ops Dashboard"
WINDOW_WIDTH = 720
WINDOW_HEIGHT = 640
WINDOW_BG = "#1e1e1e"
TEXT_FG = "#d4d4d4"
INPUT_BG = "#2d2d2d"
ACCENT_COLOR = "#0078d4"
SUCCESS_COLOR = "#4ec9b0"
WARNING_COLOR = "#dcdcaa"
ERROR_COLOR = "#f44747"
FONT_FAMILY = "Consolas" if sys.platform == "win32" else "Menlo" if sys.platform == "darwin" else "Monospace"
FONT_SIZE = 11


# ============================================================
# ファイル書き出し
# ============================================================

def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _open_native(path: str | Path) -> None:
    """OS ごとの既定アプリでファイル/フォルダを開く。"""
    p = str(path)
    if sys.platform == "win32":
        os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def _detect_drawio_path() -> str | None:
    """Draw.io デスクトップアプリのパスを探す。"""
    # shutil.which で PATH 上を検索
    for name in ("draw.io", "drawio"):
        p = shutil.which(name)
        if p:
            return p

    if sys.platform == "win32":
        # Windows の典型インストール先
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "draw.io" / "draw.io.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "draw.io" / "draw.io.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "draw.io" / "draw.io.exe",
        ]
    elif sys.platform == "darwin":
        # macOS: .app バンドル
        candidates = [
            Path("/Applications/draw.io.app/Contents/MacOS/draw.io"),
            Path.home() / "Applications" / "draw.io.app" / "Contents" / "MacOS" / "draw.io",
        ]
    else:
        # Linux snap / flatpak / AppImage
        candidates = [
            Path("/snap/drawio/current/opt/draw.io/drawio"),
            Path("/opt/draw.io/drawio"),
        ]

    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _detect_vscode_path() -> str | None:
    """VS Code のパスを探す。"""
    for name in ("code", "code-insiders", "code.cmd"):
        p = shutil.which(name)
        if p:
            return p
    return None




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
        self._cancel_requested = False
        self._preflight_ok = False  # preflight完了まではCollect不可
        self._activity_started_at: float | None = None
        self._elapsed_timer_id: str | None = None
        self._last_out_path: Path | None = None
        self._history: list[dict[str, str]] = []  # 最近5件
        self._subs_cache: list[dict[str, str]] = []
        self._rgs_cache: list[str] = []

        # レビュー待ち用
        self._review_event = threading.Event()
        self._review_proceed = False
        self._pending_nodes: list[Node] = []
        self._pending_meta: dict[str, Any] = {}

        self._setup_styles()
        self._setup_widgets()
        self._setup_keybindings()

        # 起動時に事前チェック + Sub候補ロード（非同期）
        threading.Thread(target=self._bg_preflight, daemon=True).start()

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
        tk.Label(
            self._root, text="Azure Ops Dashboard",
            bg=WINDOW_BG, fg=ACCENT_COLOR,
            font=(FONT_FAMILY, 16, "bold"),
        ).pack(pady=(12, 2))

        tk.Label(
            self._root,
            text="Azure環境を読み取って Draw.io 図 / レポートを生成",
            bg=WINDOW_BG, fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
        ).pack(pady=(0, 8))

        # --- 入力フォーム ---
        form = tk.Frame(self._root, bg=WINDOW_BG)
        form.pack(fill=tk.X, padx=16)
        form.columnconfigure(1, weight=1)

        # --- Row 0: View（最初に選ぶ） ---
        self._view_var = tk.StringVar(value="inventory")
        tk.Label(form, text="View:", bg=WINDOW_BG, fg=ACCENT_COLOR,
                 font=(FONT_FAMILY, FONT_SIZE, "bold"), anchor="e").grid(row=0, column=0, sticky="e", padx=(0, 6), pady=3)
        self._view_combo = ttk.Combobox(form, textvariable=self._view_var, state="readonly",
                                         values=["inventory", "network", "security-report", "cost-report"],
                                         font=(FONT_FAMILY, FONT_SIZE))
        self._view_combo.grid(row=0, column=1, sticky="ew", pady=3, ipady=2)
        self._view_combo.bind("<<ComboboxSelected>>", self._on_view_changed)

        # View 説明ラベル
        self._view_desc_var = tk.StringVar(value=".drawio 図生成")
        tk.Label(form, textvariable=self._view_desc_var, bg=WINDOW_BG, fg="#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2)).grid(row=0, column=2, padx=(4, 0))

        # --- Row 1: Subscription ---
        self._sub_var = tk.StringVar()
        tk.Label(form, text="Subscription:", bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), anchor="e").grid(row=1, column=0, sticky="e", padx=(0, 6), pady=3)
        self._sub_combo = ttk.Combobox(form, textvariable=self._sub_var, state="normal",
                                        font=(FONT_FAMILY, FONT_SIZE))
        self._sub_combo.grid(row=1, column=1, sticky="ew", pady=3, ipady=2)
        self._sub_combo.bind("<<ComboboxSelected>>", self._on_sub_selected)
        self._sub_hint = tk.Label(form, text="(任意)", bg=WINDOW_BG, fg="#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2))
        self._sub_hint.grid(row=1, column=2, padx=(4, 0))

        # --- Row 2: Resource Group ---
        self._rg_var = tk.StringVar()
        self._rg_label = tk.Label(form, text="Resource Group:", bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), anchor="e")
        self._rg_label.grid(row=2, column=0, sticky="e", padx=(0, 6), pady=3)
        self._rg_combo = ttk.Combobox(form, textvariable=self._rg_var, state="normal",
                                       font=(FONT_FAMILY, FONT_SIZE))
        self._rg_combo.grid(row=2, column=1, sticky="ew", pady=3, ipady=2)
        self._rg_hint = tk.Label(form, text="(指定推奨)", bg=WINDOW_BG, fg="#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2))
        self._rg_hint.grid(row=2, column=2, padx=(4, 0))

        # --- Row 3: Max Nodes ---
        self._limit_var = tk.StringVar(value="300")
        self._limit_label = tk.Label(form, text="Max Nodes:", bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), anchor="e")
        self._limit_label.grid(row=3, column=0, sticky="e", padx=(0, 6), pady=3)
        self._limit_entry = tk.Entry(form, textvariable=self._limit_var,
                 bg=INPUT_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE),
                 insertbackground=TEXT_FG, relief=tk.FLAT, borderwidth=0)
        self._limit_entry.grid(row=3, column=1, sticky="ew", pady=3, ipady=3)
        self._limit_hint = tk.Label(form, text="(既定: 300)", bg=WINDOW_BG, fg="#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2))
        self._limit_hint.grid(row=3, column=2, padx=(4, 0))

        # --- Row 4: Output Folder ---
        self._output_dir_var = tk.StringVar(value=str(Path.home() / "Documents"))
        tk.Label(form, text="Output Dir:", bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), anchor="e").grid(row=4, column=0, sticky="e", padx=(0, 6), pady=3)
        outdir_frame = tk.Frame(form, bg=WINDOW_BG)
        outdir_frame.grid(row=4, column=1, sticky="ew", pady=3)
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
        self._open_dir_btn.grid(row=4, column=2, padx=(4, 0))

        # --- Row 5: Open App ---
        self._open_app_var = tk.StringVar(value="auto")
        tk.Label(form, text="Open with:", bg=WINDOW_BG, fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE), anchor="e").grid(row=5, column=0, sticky="e", padx=(0, 6), pady=3)
        app_frame = tk.Frame(form, bg=WINDOW_BG)
        app_frame.grid(row=5, column=1, sticky="ew", pady=3)
        for val, label in [("auto", "Auto"), ("drawio", "Draw.io"), ("vscode", "VS Code"), ("os", "OS既定")]:
            tk.Radiobutton(app_frame, text=label, variable=self._open_app_var, value=val,
                           bg=WINDOW_BG, fg=TEXT_FG, selectcolor=INPUT_BG,
                           activebackground=WINDOW_BG, activeforeground=TEXT_FG,
                           font=(FONT_FAMILY, FONT_SIZE - 1)
                           ).pack(side=tk.LEFT, padx=(0, 10))
        # Draw.io 検出状態表示
        drawio_path = _detect_drawio_path()
        hint = "✅ Draw.io 検出" if drawio_path else "⚠️ Draw.io 未検出"
        tk.Label(form, text=hint, bg=WINDOW_BG,
                 fg=SUCCESS_COLOR if drawio_path else "#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2)).grid(row=5, column=2, padx=(4, 0))

        # ============================================================
        # レポート設定パネル（レポート系View選択時のみ表示）
        # ============================================================
        self._report_panel = tk.Frame(self._root, bg="#252526", relief=tk.GROOVE, borderwidth=1)
        # pack は _on_view_changed で

        # --- Template 選択行 ---
        tmpl_row = tk.Frame(self._report_panel, bg="#252526")
        tmpl_row.pack(fill=tk.X, padx=10, pady=(6, 2))

        tk.Label(tmpl_row, text="Template:", bg="#252526", fg=ACCENT_COLOR,
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

        tk.Button(tmpl_row, text="💾 Save as…",
                  command=self._on_save_template,
                  bg="#3C3C3C", fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 2),
                  relief=tk.FLAT, padx=6, cursor="hand2").pack(side=tk.RIGHT)

        # --- セクションチェックボックス（2列グリッド） ---
        self._sections_frame = tk.Frame(self._report_panel, bg="#252526")
        self._sections_frame.pack(fill=tk.X, padx=10, pady=(2, 2))
        self._section_vars: dict[str, tk.BooleanVar] = {}
        self._section_widgets: list[tk.Checkbutton] = []

        # --- カスタム指示欄（保存済み指示チェック + 自由入力） ---
        instr_frame = tk.Frame(self._report_panel, bg="#252526")
        instr_frame.pack(fill=tk.X, padx=10, pady=(2, 2))

        tk.Label(instr_frame, text="追加指示:", bg="#252526", fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE - 1, "bold"), anchor="nw").pack(anchor="w")

        # 保存済み指示チェックボックス行
        self._saved_instr_frame = tk.Frame(instr_frame, bg="#252526")
        self._saved_instr_frame.pack(fill=tk.X, pady=(2, 2))
        self._saved_instr_vars: list[tuple[tk.BooleanVar, str]] = []
        self._saved_instr_widgets: list[tk.Checkbutton] = []

        # 自由入力欄
        free_row = tk.Frame(instr_frame, bg="#252526")
        free_row.pack(fill=tk.X, pady=(2, 2))
        free_row.columnconfigure(1, weight=1)
        tk.Label(free_row, text="自由入力:", bg="#252526", fg="#808080",
                 font=(FONT_FAMILY, FONT_SIZE - 2), anchor="nw").grid(row=0, column=0, sticky="nw")
        self._custom_instruction = tk.Text(free_row, height=2,
                 bg=INPUT_BG, fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 1),
                 insertbackground=TEXT_FG, relief=tk.FLAT, borderwidth=0,
                 wrap=tk.WORD)
        self._custom_instruction.grid(row=0, column=1, sticky="ew", padx=(6, 0), ipady=2)

        free_btn_row = tk.Frame(free_row, bg="#252526")
        free_btn_row.grid(row=0, column=2, padx=(4, 0), sticky="n")
        tk.Button(free_btn_row, text="💾 記憶",
                  command=self._on_save_instruction,
                  bg="#3C3C3C", fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 2),
                  relief=tk.FLAT, padx=4, cursor="hand2").pack(pady=(0, 2))
        tk.Button(free_btn_row, text="🗑 削除",
                  command=self._on_delete_instruction,
                  bg="#3C3C3C", fg=TEXT_FG, font=(FONT_FAMILY, FONT_SIZE - 2),
                  relief=tk.FLAT, padx=4, cursor="hand2").pack()

        # --- 出力形式 + 自動オープン ---
        export_row = tk.Frame(self._report_panel, bg="#252526")
        export_row.pack(fill=tk.X, padx=10, pady=(2, 6))

        tk.Label(export_row, text="出力形式:", bg="#252526", fg=TEXT_FG,
                 font=(FONT_FAMILY, FONT_SIZE - 1)).pack(side=tk.LEFT)
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

        ttk.Separator(export_row, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)

        self._auto_open_var = tk.BooleanVar(value=True)
        tk.Checkbutton(export_row, text="生成後に自動で開く", variable=self._auto_open_var,
                       bg="#252526", fg=TEXT_FG, selectcolor=INPUT_BG,
                       activebackground="#252526", activeforeground=TEXT_FG,
                       font=(FONT_FAMILY, FONT_SIZE - 2)).pack(side=tk.LEFT, padx=(4, 0))

        # テンプレートキャッシュ
        self._templates_cache: list[dict] = []
        self._current_template: dict | None = None

        # --- ボタン行 ---
        btn_frame = tk.Frame(self._root, bg=WINDOW_BG)
        btn_frame.pack(pady=8)

        self._collect_btn = tk.Button(
            btn_frame, text="▶ Collect",
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
            btn_frame, text="✖ Cancel",
            command=self._on_abort,
            bg=ERROR_COLOR, fg="white",
            font=(FONT_FAMILY, FONT_SIZE, "bold"),
            relief=tk.FLAT, padx=20, pady=6,
            cursor="hand2",
        )
        # 初期非表示 — _set_working(True) で pack される

        self._refresh_btn = tk.Button(
            btn_frame, text="🔄 Refresh",
            command=self._on_refresh,
            bg="#3C3C3C", fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
        )
        self._refresh_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._open_btn = tk.Button(
            btn_frame, text="Open File",
            command=self._on_open_file,
            bg="#3C3C3C", fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
            state=tk.DISABLED,
        )
        self._open_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._copy_btn = tk.Button(
            btn_frame, text="Copy Log",
            command=self._on_copy_log,
            bg="#3C3C3C", fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
        )
        self._copy_btn.pack(side=tk.LEFT, padx=(6, 0))

        self._login_btn = tk.Button(
            btn_frame, text="🔑 az login",
            command=self._on_az_login,
            bg="#3C3C3C", fg=TEXT_FG,
            font=(FONT_FAMILY, FONT_SIZE - 1),
            relief=tk.FLAT, padx=12, pady=6,
            cursor="hand2",
        )
        self._login_btn.pack(side=tk.LEFT, padx=(6, 0))

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
            review_btn_row, text="  ✔ Proceed — 生成する  ",
            command=self._on_proceed,
            bg=SUCCESS_COLOR, fg="#1e1e1e",
            font=(FONT_FAMILY, FONT_SIZE, "bold"),
            relief=tk.FLAT, padx=20, pady=6,
            cursor="hand2",
        )
        self._proceed_btn.pack(side=tk.LEFT)

        self._cancel_btn = tk.Button(
            review_btn_row, text="  ✖ Cancel  ",
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

        self._status_var = tk.StringVar(value="Ready")
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
    # View 切り替え
    # ------------------------------------------------------------------ #

    _VIEW_DESCRIPTIONS = {
        "inventory": ".drawio 図生成",
        "network": ".drawio ネットワーク図",
        "security-report": "🛡️ セキュリティレポート (.md)",
        "cost-report": "💰 コストレポート (.md)",
    }

    def _on_view_changed(self, _event: tk.Event | None = None) -> None:
        """View 選択変更時にボタンラベル、説明、フォーム表示を更新。"""
        view = self._view_var.get().strip()
        desc = self._VIEW_DESCRIPTIONS.get(view, "")
        self._view_desc_var.set(desc)

        is_report = view in ("security-report", "cost-report")

        # ボタンラベル
        if is_report:
            self._collect_btn.configure(text="▶ Generate Report")
        else:
            self._collect_btn.configure(text="▶ Collect")

        # RG / MaxNodes を動的に有効/無効化
        if is_report:
            self._rg_combo.configure(state="disabled")
            self._rg_label.configure(fg="#555555")
            self._rg_hint.configure(text="(レポートでは不使用)")
            self._limit_entry.configure(state="disabled")
            self._limit_label.configure(fg="#555555")
            self._limit_hint.configure(text="(レポートでは不使用)")
        else:
            self._rg_combo.configure(state="normal")
            self._rg_label.configure(fg=TEXT_FG)
            self._rg_hint.configure(text="(指定推奨)")
            self._limit_entry.configure(state="normal")
            self._limit_label.configure(fg=TEXT_FG)
            self._limit_hint.configure(text="(既定: 300)")

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
        names = [t.get("template_name", "Unknown") for t in templates]
        self._template_combo.configure(values=names if names else ["(No templates)"])
        if names:
            self._template_var.set(names[0])
            self._on_template_selected()
        else:
            self._current_template = None
            self._clear_section_checks()
        # 保存済み指示もロード
        self._load_saved_instructions()

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
        for item in data:
            label = item.get("label", "")
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

    def _on_template_selected(self, _event: tk.Event | None = None) -> None:
        """テンプレート選択時にチェックボックスを更新。"""
        name = self._template_var.get()
        for t in self._templates_cache:
            if t.get("template_name") == name:
                self._current_template = t
                self._template_desc_var.set(t.get("description", ""))
                self._rebuild_section_checks(t)
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
        row, col = 0, 0
        for key, sec in sections.items():
            var = tk.BooleanVar(value=sec.get("enabled", True))
            self._section_vars[key] = var
            label = sec.get("label", key)
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
        import copy
        t = copy.deepcopy(self._current_template)
        sections = t.get("sections", {})
        for key, var in self._section_vars.items():
            if key in sections:
                sections[key]["enabled"] = var.get()
        return t

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
            "指示を保存",
            "チェックボックスに表示するラベル名:",
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
        self._log(f"指示を保存しました: {label}", "success")

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
            self._log("削除する指示をチェックしてください", "warning")
            return

        # 確認
        count = len(to_delete)
        if not messagebox.askyesno("指示を削除", f"チェック済みの {count} 件の指示を削除しますか？"):
            return

        # フィルタして保存
        data = [item for item in data if item.get("instruction", "") not in to_delete]
        instr_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        # UIリロード
        self._load_saved_instructions()
        self._log(f"{count} 件の指示を削除しました", "success")

    def _on_save_template(self) -> None:
        """現在のチェック状態を新しいテンプレートとして保存。"""
        t = self._get_current_template_with_overrides()
        if not t:
            return

        # frozen (PyInstaller) の同梱 templates は読み取り専用になり得るため、ユーザー領域を既定にする
        ensure_user_dirs()
        p = filedialog.asksaveasfilename(
            title="Save Template",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=str(user_templates_dir()) if user_templates_dir().is_dir() else str(Path.home() / "Documents"),
            initialfile=f"{t.get('report_type', 'custom')}-custom.json",
        )
        if p:
            from ai_reviewer import save_template
            t["template_name"] = Path(p).stem.split("-", 1)[-1].capitalize()
            # _pathは保存対象から除外
            t.pop("_path", None)
            save_template(p, t)
            self._log(f"テンプレート保存: {p}", "success")
            # リロード
            report_type = t.get("report_type", "security")
            self._load_templates_for_type(report_type)

    # ------------------------------------------------------------------ #
    # 出力フォルダ
    # ------------------------------------------------------------------ #

    def _on_browse_output_dir(self) -> None:
        d = filedialog.askdirectory(
            title="出力フォルダを選択",
            initialdir=self._output_dir_var.get(),
        )
        if d:
            self._output_dir_var.set(d)

    def _on_open_output_dir(self) -> None:
        d = self._output_dir_var.get()
        if d and Path(d).exists():
            _open_native(d)

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
        self._cancel_requested = True
        self._review_event.set()  # レビュー待ちも解除
        self._log("キャンセルを要求しました...", "warning")
        self._set_status("Cancelling...")
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
            self._log("Azure CLI: OK", "success")
            self._root.after(0, lambda: self._collect_btn.configure(state=tk.NORMAL))
        else:
            self._log("\u2191 上記を解決してから Refresh を押してください", "error")
            self._root.after(0, lambda: self._collect_btn.configure(state=tk.DISABLED))

        # Sub 候補ロード
        self._log("Subscription 候補を取得中...", "info")
        subs = list_subscriptions()
        self._subs_cache = subs
        if subs:
            values = ["(全サブスクリプション)"] + [f"{s['name']}  ({s['id']})" for s in subs]
            self._root.after(0, lambda: self._sub_combo.configure(values=values))
            self._log(f"  → {len(subs)} 件のサブスクリプションを検出", "success")

            # Sub が1件なら自動選択 + RG自動ロード
            if len(subs) == 1:
                auto_val = values[1]  # 実際のSub（全サブスクではない）
                self._root.after(0, lambda: self._sub_var.set(auto_val))
                self._log("  → サブスクリプションが1件のため自動選択", "info")
                sub_id = subs[0]["id"]
                self._bg_load_rgs(sub_id)
        else:
            self._log("  Subscription 候補を取得できませんでした（手入力で続行可）", "warning")

    def _on_sub_selected(self, _event: tk.Event | None = None) -> None:
        """Subscription 選択時に RG 候補をロード。"""
        sub_id = self._extract_sub_id()
        if not sub_id:
            # 全サブスク選択時はRGリストをクリア
            self._rgs_cache = []
            self._root.after(0, lambda: self._rg_combo.configure(values=[]))
            self._root.after(0, lambda: self._rg_var.set(""))
            self._log("全サブスクリプションが選択されました（RG指定推奨）", "info")
            return
        threading.Thread(target=self._bg_load_rgs, args=(sub_id,), daemon=True).start()

    def _bg_load_rgs(self, sub_id: str) -> None:
        self._log(f"RG 候補を取得中 (sub={sub_id[:8]}...)...", "info")
        rgs = list_resource_groups(sub_id)
        self._rgs_cache = rgs
        if rgs:
            values = ["(全体)"] + rgs
            self._root.after(0, lambda: self._rg_combo.configure(values=values))
            self._log(f"  → {len(rgs)} 件の RG を検出", "success")
        else:
            self._log("  RG 候補を取得できませんでした（手入力で続行可）", "warning")

    def _on_refresh(self) -> None:
        threading.Thread(target=self._bg_preflight, daemon=True).start()

    def _on_az_login(self) -> None:
        """az login をバックグラウンドで実行し、完了後に Refresh。"""
        def _do_login() -> None:
            self._log("az login を実行中... ブラウザが開きます", "info")
            self._root.after(0, lambda: self._login_btn.configure(state=tk.DISABLED))
            try:
                import subprocess, sys
                kwargs: dict = {
                    "capture_output": True, "text": True,
                    "timeout": 120, "encoding": "utf-8", "errors": "replace",
                }
                if sys.platform == "win32":
                    kwargs["shell"] = True
                    cmd: str | list[str] = "az login"
                else:
                    cmd = ["az", "login"]
                result = subprocess.run(cmd, **kwargs)
                if result.returncode == 0:
                    self._log("az login 成功！環境を再チェックします...", "success")
                    # Sub/RG をクリア
                    self._root.after(0, lambda: self._sub_var.set(""))
                    self._root.after(0, lambda: self._rg_var.set(""))
                    self._root.after(0, lambda: self._sub_combo.configure(values=[]))
                    self._root.after(0, lambda: self._rg_combo.configure(values=[]))
                    self._bg_preflight()
                else:
                    self._log(f"az login 失敗: {result.stderr[:200]}", "error")
            except Exception as e:
                self._log(f"az login エラー: {e}", "error")
            finally:
                self._root.after(0, lambda: self._login_btn.configure(state=tk.NORMAL))

        threading.Thread(target=_do_login, daemon=True).start()

    def _extract_sub_id(self) -> str | None:
        """Combobox の表示値からサブスクID部分を取り出す。"""
        raw = self._sub_var.get().strip()
        if not raw or raw == "(全サブスクリプション)":
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
        rg = None if (not rg_raw or rg_raw == "(全体)") else rg_raw
        view = self._view_var.get().strip()
        try:
            limit = int(self._limit_var.get().strip())
        except ValueError:
            limit = 300

        self._cancel_requested = False
        self._set_working(True)
        self._hide_review()

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
            self._set_status("Running az graph query...")
            self._log(f"az graph query を実行中... (view={view})", "info")

            collected_edges: list[Edge] = []
            if view == "network":
                nodes, collected_edges, meta = collect_network(subscription=sub, resource_group=rg, limit=limit)
                self._log(f"  → {len(nodes)} 件のネットワークリソース, {len(collected_edges)} 件の接続を取得", "success")
            else:
                nodes, meta = collect_inventory(subscription=sub, resource_group=rg, limit=limit)
                self._log(f"  → {len(nodes)} 件のリソースを取得", "success")

            if self._cancel_requested:
                self._log("キャンセルされました", "warning")
                return

            # type別サマリ
            summary = type_summary(nodes)
            for rtype, count in sorted(summary.items()):
                short = rtype.split("/")[-1] if "/" in rtype else rtype
                self._log(f"    {short}: {count}", "info")

            if limit <= len(nodes):
                self._log(f"  ⚠ 上限 {limit} に達しています。実際はもっとあるかもしれません。", "warning")

            # レビュー表示して Proceed/Cancel 待ち
            self._pending_nodes = nodes
            self._pending_meta = meta

            # --- AI レビュー（Copilot SDK） ---
            self._set_step("Step 2/5: AI Review")
            self._set_status("Copilot SDK で構成をレビュー中...")
            self._log("─" * 40, "accent")
            self._log("🤖 AI レビューを開始...", "info")

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
                )
            except Exception as e:
                self._log(f"AI レビューをスキップ: {e}", "warning")

            self._log("", "info")  # 改行
            self._log("─" * 40, "accent")

            if self._cancel_requested:
                self._log("キャンセルされました", "warning")
                return

            review_text = (
                f"取得結果: {len(nodes)} 件のリソース | "
                f"{len(summary)} 種類のtype | "
                f"Subscription: {sub or '(既定)'} | "
                f"RG: {rg or '(全体)'}"
            )
            self._show_review(review_text)
            self._set_step("Review")
            self._set_status("レビュー中 — Proceed または Cancel を押してください")

            # ブロッキング待ち（ワーカースレッド上）
            self._review_event.clear()
            self._review_event.wait()

            if not self._review_proceed or self._cancel_requested:
                self._log("キャンセルされました", "warning")
                self._set_status("Cancelled")
                return

            self._hide_review()

            # Step 2: 保存先決定（Output Dir設定済みなら自動、未設定ならダイアログ）
            initial_dir = self._output_dir_var.get().strip()
            default_name = f"env-{now_stamp()}.drawio"

            if initial_dir and Path(initial_dir).is_dir():
                # 自動保存
                out_path = Path(initial_dir) / default_name
                self._log(f"  自動保存: {out_path}", "info")
            else:
                # ダイアログ
                out_path_holder: list[str] = []
                done_event = threading.Event()

                def _ask_save() -> None:
                    p = filedialog.asksaveasfilename(
                        title="Save .drawio",
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
                    self._log("保存先が選択されませんでした", "warning")
                    self._set_status("Cancelled")
                    return
                out_path = Path(out_path_holder[0])

            # Step 3: Normalize
            self._set_step("Step 3/5: Normalize")
            self._set_status("Normalizing...")
            azure_to_cell_id = {n.azure_id: cell_id_for_azure_id(n.azure_id) for n in nodes}
            edges: list[Edge] = collected_edges

            # Step 4: Build XML
            self._set_step("Step 4/5: Build XML")
            self._set_status("Generating .drawio XML...")
            self._log(".drawio XML を生成中...")
            xml = build_drawio_xml(
                nodes=nodes, edges=edges,
                azure_to_cell_id=azure_to_cell_id,
                diagram_name=f"{view}-{now_stamp()}",
            )

            # Step 5: Save
            self._set_step("Step 5/5: Save")
            self._set_status("Saving files...")
            _write_text(out_path, xml)
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
            _write_json(out_dir / "env.json", env_payload)
            self._log(f"  → {out_dir / 'env.json'}", "success")

            _write_json(out_dir / "collect.log.json", {"tool": "az graph query", "meta": meta})

            # Done + Preview
            self._set_step("Done")
            self._log("完了!", "success")
            self._set_status(f"Done — {out_path}")

            self._last_out_path = out_path
            self._root.after(0, lambda: self._open_btn.configure(state=tk.NORMAL))

            # 履歴追加
            self._history.insert(0, {
                "path": str(out_path),
                "time": datetime.now().strftime("%H:%M:%S"),
                "count": str(len(nodes)),
            })
            self._history = self._history[:5]

            # Canvas プレビュー
            self._draw_preview(nodes, edges, azure_to_cell_id)

            # 自動オープン
            if out_path.exists():
                self._root.after(500, lambda p=out_path: self._open_file_with(p))

        except Exception as e:
            self._log(f"ERROR: {e}", "error")
            self._set_status("Error")
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
        self._cancel_requested = True
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
            self._set_status("ログをクリップボードにコピーしました")

    # ------------------------------------------------------------------ #
    # Open File
    # ------------------------------------------------------------------ #

    def _on_open_file(self) -> None:
        if self._last_out_path and self._last_out_path.exists():
            self._open_file_with(self._last_out_path)

    def _open_file_with(self, path: Path) -> None:
        """Open App 設定に応じてファイルを開く。"""
        choice = self._open_app_var.get()
        suffix = path.suffix.lower()
        is_drawio = suffix == ".drawio"

        if choice == "auto":
            if is_drawio:
                # Draw.io があればそれ、なければ VS Code、それもなければ OS既定
                dp = _detect_drawio_path()
                if dp:
                    subprocess.Popen([dp, str(path)])
                    return
                vp = _detect_vscode_path()
                if vp:
                    subprocess.Popen([vp, str(path)])
                    return
            _open_native(path)

        elif choice == "drawio":
            dp = _detect_drawio_path()
            if dp:
                subprocess.Popen([dp, str(path)])
            else:
                self._log("Draw.io が見つかりません。OS既定で開きます", "warning")
                _open_native(path)

        elif choice == "vscode":
            vp = _detect_vscode_path()
            if vp:
                subprocess.Popen([vp, str(path)])
            else:
                self._log("VS Code が見つかりません。OS既定で開きます", "warning")
                _open_native(path)

        else:  # "os"
            _open_native(path)

    # ------------------------------------------------------------------ #
    # レポート生成ワーカー (security-report / cost-report)
    # ------------------------------------------------------------------ #

    def _worker_report(self, sub: str | None, rg: str | None, limit: int, view: str) -> None:
        """Security / Cost レポート生成ワーカー。"""
        try:
            # テンプレートとカスタム指示をUIスレッドで取得
            template = self._get_current_template_with_overrides()
            custom_instruction = self._get_custom_instruction()

            if template:
                tname = template.get('template_name', '?')
                enabled_count = sum(1 for s in template.get('sections', {}).values() if s.get('enabled'))
                total_count = len(template.get('sections', {}))
                self._log(f"  Template: {tname} ({enabled_count}/{total_count} セクション)", "info")
            if custom_instruction:
                self._log(f"  追加指示: {custom_instruction[:80]}{'...' if len(custom_instruction) > 80 else ''}", "info")
            # Step 1: リソース収集
            self._set_step("Step 1/3: Collect")
            self._set_status("リソースを収集中...")
            self._log(f"az graph query を実行中... (view={view})", "info")

            nodes, meta = collect_inventory(subscription=sub, resource_group=rg, limit=limit)
            self._log(f"  → {len(nodes)} 件のリソースを取得", "success")

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

            if self._cancel_requested:
                return

            # Step 2: 追加データ収集 + AIレポート生成
            self._set_step("Step 2/3: AI Report")
            self._log("─" * 40, "accent")

            report_result: str | None = None

            if view == "security-report":
                self._set_status("セキュリティデータを収集中...")
                self._log("🔒 セキュリティデータを収集中...", "info")
                security_data = collect_security(sub)
                score = security_data.get("secure_score")
                if score:
                    self._log(f"  セキュアスコア: {score.get('current')} / {score.get('max')}", "info")
                assess = security_data.get("assessments_summary")
                if assess:
                    self._log(f"  評価: {assess.get('total')}件 (Healthy:{assess.get('healthy')}, Unhealthy:{assess.get('unhealthy')})", "info")

                self._log("🤖 AI セキュリティレポートを生成中...", "info")
                try:
                    from ai_reviewer import run_security_report
                    report_result = run_security_report(
                        security_data=security_data,
                        resource_text=resource_text,
                        template=template,
                        custom_instruction=custom_instruction,
                        on_delta=lambda d: self._log_append_delta(d),
                        on_status=lambda s: self._log(s, "info"),
                    )
                except Exception as e:
                    self._log(f"AI レポートエラー: {e}", "error")

            elif view == "cost-report":
                self._set_status("コストデータを収集中...")
                self._log("💰 コストデータを収集中...", "info")
                cost_data = collect_cost(sub)
                svc = cost_data.get("cost_by_service")
                if svc:
                    self._log(f"  サービス別コスト: {len(svc)}件", "info")
                rg_cost = cost_data.get("cost_by_rg")
                if rg_cost:
                    self._log(f"  RG別コスト: {len(rg_cost)}件", "info")

                self._log("📝 Advisor 推奨事項を収集中...", "info")
                advisor_data = collect_advisor(sub)
                adv_summary = advisor_data.get("summary", {})
                if adv_summary:
                    for cat, cnt in adv_summary.items():
                        self._log(f"    {cat}: {cnt}", "info")

                self._log("🤖 AI コストレポートを生成中...", "info")
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
                    )
                except Exception as e:
                    self._log(f"AI レポートエラー: {e}", "error")

            self._log("", "info")
            self._log("─" * 40, "accent")

            if self._cancel_requested:
                return

            if not report_result:
                self._log("レポート生成に失敗しました", "error")
                self._set_status("Failed")
                return

            # Step 3: 保存（Output Dir設定済みなら自動、未設定ならダイアログ）
            self._set_step("Step 3/3: Save")
            report_type = "security" if view == "security-report" else "cost"
            default_name = f"{report_type}-report-{now_stamp()}.md"
            initial_dir = self._output_dir_var.get().strip()

            if initial_dir and Path(initial_dir).is_dir():
                # 自動保存
                out_path = Path(initial_dir) / default_name
                self._log(f"  自動保存: {out_path}", "info")
            else:
                # ダイアログ
                out_path_holder: list[str] = []
                done_event = threading.Event()

                def _ask_save() -> None:
                    p = filedialog.asksaveasfilename(
                        title=f"Save {report_type} report",
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
                    self._log("保存先が選択されませんでした", "warning")
                    self._set_status("Cancelled")
                    return
                out_path = Path(out_path_holder[0])
            _write_text(out_path, report_result)
            self._last_out_path = out_path
            self._log(f"  → {out_path}", "success")

            # 追加出力形式
            if self._export_docx_var.get():
                try:
                    from exporter import md_to_docx
                    docx_path = out_path.with_suffix(".docx")
                    md_to_docx(report_result, docx_path)
                    self._log(f"  → {docx_path} (Word)", "success")
                except Exception as e:
                    self._log(f"  Word 出力エラー: {e}", "warning")

            if self._export_pdf_var.get():
                try:
                    from exporter import md_to_pdf
                    pdf_path = out_path.with_suffix(".pdf")
                    result = md_to_pdf(report_result, pdf_path)
                    if result:
                        self._log(f"  → {pdf_path} (PDF)", "success")
                    else:
                        self._log("  PDF 出力: Word/LibreOffice が見つかりません", "warning")
                except Exception as e:
                    self._log(f"  PDF 出力エラー: {e}", "warning")

            self._root.after(0, lambda: self._open_btn.configure(state=tk.NORMAL))
            self._set_status("完了!")
            self._log("完了!", "success")

            # 自動オープン
            if self._auto_open_var.get() and out_path.exists():
                self._root.after(500, lambda p=out_path: self._open_file_with(p))

        except Exception as e:
            self._log(f"エラー: {e}", "error")
            self._set_status(f"Error: {e}")
        finally:
            self._set_working(False)

    # ------------------------------------------------------------------ #
    # 起動
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        self._root.mainloop()


# ============================================================
# エントリポイント
# ============================================================

def main() -> None:
    app = App()
    app.run()


if __name__ == "__main__":
    main()
