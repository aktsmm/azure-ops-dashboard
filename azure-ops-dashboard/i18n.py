"""Step10: 国際化（i18n）モジュール

日本語/英語の UI 文字列を管理する。
用法:
    from i18n import t, set_language, get_language
    label = t("app.subtitle")   # 現在の言語で返す
    set_language("en")           # 切り替え
"""

from __future__ import annotations

from typing import Any

# ============================================================
# 翻訳辞書
# ============================================================

_STRINGS: dict[str, dict[str, str]] = {
    # --- アプリ全般 ---
    "app.title":                {"ja": "Azure Ops Dashboard",           "en": "Azure Ops Dashboard"},
    "app.subtitle":             {"ja": "Azure環境を読み取って Draw.io 図 / レポートを生成",
                                 "en": "Read Azure environment & generate Draw.io diagrams / reports"},

    # --- フォームラベル ---
    "label.view":               {"ja": "View:",                         "en": "View:"},
    "label.subscription":       {"ja": "Subscription:",                 "en": "Subscription:"},
    "label.resource_group":     {"ja": "Resource Group:",               "en": "Resource Group:"},
    "label.max_nodes":          {"ja": "Max Nodes:",                    "en": "Max Nodes:"},
    "label.output_dir":         {"ja": "Output Dir:",                   "en": "Output Dir:"},
    "label.open_with":          {"ja": "Open with:",                    "en": "Open with:"},
    "label.template":           {"ja": "Template:",                     "en": "Template:"},
    "label.extra_instructions": {"ja": "追加指示:",                     "en": "Instructions:"},
    "label.free_input":         {"ja": "自由入力:",                     "en": "Free input:"},
    "label.export_format":      {"ja": "出力形式:",                     "en": "Export format:"},
    "label.language":           {"ja": "Language:",                     "en": "Language:"},
    "label.model":              {"ja": "Model:",                        "en": "Model:"},
    "label.diff_not_found":     {"ja": "差分ファイルなし",                "en": "No diff file"},

    # --- ヒント ---
    "hint.optional":            {"ja": "(任意)",                        "en": "(optional)"},
    "hint.recommended":         {"ja": "(指定推奨)",                    "en": "(recommended)"},
    "hint.default_300":         {"ja": "(既定: 300)",                   "en": "(default: 300)"},
    "hint.not_used_report":     {"ja": "(レポートでは不使用)",         "en": "(not used for reports)"},
    "hint.all_subscriptions":   {"ja": "(全サブスクリプション)",       "en": "(all subscriptions)"},
    "hint.all_rgs":             {"ja": "(全体)",                        "en": "(all)"},
    "hint.drawio_detected":     {"ja": "✅ Draw.io 検出",              "en": "✅ Draw.io detected"},
    "hint.drawio_not_found":    {"ja": "⚠️ Draw.io 未検出",            "en": "⚠️ Draw.io not found"},
    "hint.no_templates":        {"ja": "(テンプレートなし)",           "en": "(No templates)"},
    "hint.loading_models":      {"ja": "(モデル取得中)",               "en": "(Loading models)"},

    # --- View 説明 ---
    "view.inventory":           {"ja": ".drawio 図生成",               "en": ".drawio diagram"},
    "view.network":             {"ja": ".drawio ネットワーク図",       "en": ".drawio network diagram"},
    "view.security_report":     {"ja": "🛡️ セキュリティレポート (.md)","en": "🛡️ Security report (.md)"},
    "view.cost_report":         {"ja": "💰 コストレポート (.md)",      "en": "💰 Cost report (.md)"},

    # --- ボタン ---
    "btn.collect":              {"ja": "▶ Collect",                     "en": "▶ Collect"},
    "btn.generate_report":      {"ja": "▶ Generate Report",            "en": "▶ Generate Report"},
    "btn.cancel":               {"ja": "✖ Cancel",                     "en": "✖ Cancel"},
    "btn.refresh":              {"ja": "🔄 Refresh",                   "en": "🔄 Refresh"},
    "btn.open_file":            {"ja": "Open File",                     "en": "Open File"},
    "btn.open_diff":            {"ja": "差分を表示",                      "en": "Show Diff"},
    "btn.copy_log":             {"ja": "Copy Log",                      "en": "Copy Log"},
    "btn.clear_log":            {"ja": "Clear",                         "en": "Clear"},
    "btn.az_login":             {"ja": "🔑 az login",                  "en": "🔑 az login"},
    "btn.sp_login":             {"ja": "🔐 SP login",                  "en": "🔐 SP login"},
    "btn.proceed":              {"ja": "  ✔ Proceed — 生成する  ",    "en": "  ✔ Proceed — Generate  "},
    "btn.cancel_review":        {"ja": "  ✖ Cancel  ",                 "en": "  ✖ Cancel  "},
    "btn.save_template":        {"ja": "💾 Save as…",                  "en": "💾 Save as…"},
    "btn.import_template":      {"ja": "📥 Import",                    "en": "📥 Import"},
    "btn.save_instruction":     {"ja": "💾 記憶",                      "en": "💾 Save"},
    "btn.delete_instruction":   {"ja": "🗑 削除",                      "en": "🗑 Delete"},
    "btn.auto_open":            {"ja": "生成後に自動で開く",           "en": "Auto-open after generation"},

    # --- ステータス / ステップ ---
    "status.ready":             {"ja": "Ready",                         "en": "Ready"},
    "status.cancelling":        {"ja": "Cancelling...",                 "en": "Cancelling..."},
    "status.cancelled":         {"ja": "Cancelled",                     "en": "Cancelled"},
    "status.error":             {"ja": "Error",                         "en": "Error"},
    "status.done":              {"ja": "完了!",                         "en": "Done!"},
    "status.failed":            {"ja": "Failed",                        "en": "Failed"},
    "status.running_query":     {"ja": "Running az graph query...",     "en": "Running az graph query..."},
    "status.reviewing":         {"ja": "Copilot SDK で構成をレビュー中...",
                                 "en": "Reviewing with Copilot SDK..."},
    "status.review_prompt":     {"ja": "レビュー中 — Proceed または Cancel を押してください",
                                 "en": "Reviewing — Press Proceed or Cancel"},
        "status.report_review_prompt": {"ja": "レポート確認 — Proceed で保存 / Cancel で破棄",
                                     "en": "Review report — Proceed to save / Cancel to discard"},
    "status.normalizing":       {"ja": "Normalizing...",                "en": "Normalizing..."},
    "status.generating_xml":    {"ja": "Generating .drawio XML...",     "en": "Generating .drawio XML..."},
    "status.saving":            {"ja": "Saving files...",               "en": "Saving files..."},
    "status.collecting":        {"ja": "リソースを収集中...",          "en": "Collecting resources..."},
    "status.collecting_sec":    {"ja": "セキュリティデータを収集中...",
                                 "en": "Collecting security data..."},
    "status.collecting_cost":   {"ja": "コストデータを収集中...",      "en": "Collecting cost data..."},
    "status.log_copied":        {"ja": "ログをクリップボードにコピーしました",
                                 "en": "Log copied to clipboard"},

    # --- ログメッセージ ---
    "log.cancel_requested":     {"ja": "キャンセルを要求しました...",  "en": "Cancellation requested..."},
    "log.cancelled":            {"ja": "キャンセルされました",         "en": "Cancelled"},
    "log.azure_cli_ok":         {"ja": "Azure CLI: OK",                 "en": "Azure CLI: OK"},
    "log.fix_above":            {"ja": "↑ 上記を解決してから Refresh を押してください",
                                 "en": "↑ Fix the above issues and press Refresh"},
    "log.loading_subs":         {"ja": "Subscription 候補を取得中...",  "en": "Loading subscriptions..."},
    "log.loading_models":       {"ja": "利用可能モデルを取得中...",     "en": "Loading available models..."},
    "log.model_fallback":       {"ja": "モデル一覧取得タイムアウト（既定モデルを使用）", "en": "Model list timeout (using default model)"},
    "log.svg_export_skip":      {"ja": "SVG変換スキップ（Draw.io CLIが見つかりません）", "en": "SVG export skipped (Draw.io CLI not found)"},
    "log.diff_generated":       {"ja": "差分レポート生成: {path}",       "en": "Diff report generated: {path}"},
    "log.subs_found":           {"ja": "  → {count} 件のサブスクリプションを検出",
                                 "en": "  → Found {count} subscription(s)"},
    "log.auto_selected_sub":    {"ja": "  → サブスクリプションが1件のため自動選択",
                                 "en": "  → Auto-selected (only 1 subscription)"},
    "log.subs_failed":          {"ja": "  Subscription 候補を取得できませんでした（手入力で続行可）",
                                 "en": "  Could not load subscriptions (manual input OK)"},
    "log.all_subs_selected":    {"ja": "全サブスクリプションが選択されました（RG指定推奨）",
                                 "en": "All subscriptions selected (specifying RG recommended)"},
    "log.loading_rgs":          {"ja": "RG 候補を取得中 (sub={sub})...",
                                 "en": "Loading RGs (sub={sub})..."},
    "log.rgs_found":            {"ja": "  → {count} 件の RG を検出",
                                 "en": "  → Found {count} RG(s)"},
    "log.rgs_failed":           {"ja": "  RG 候補を取得できませんでした（手入力で続行可）",
                                 "en": "  Could not load RGs (manual input OK)"},
    "log.az_login_running":     {"ja": "az login を実行中... ブラウザが開きます",
                                 "en": "Running az login... browser will open"},
    "log.az_login_success":     {"ja": "az login 成功！環境を再チェックします...",
                                 "en": "az login succeeded! Re-checking environment..."},
    "log.az_login_failed":      {"ja": "az login 失敗: {err}",         "en": "az login failed: {err}"},
    "log.az_login_error":       {"ja": "az login エラー: {err}",       "en": "az login error: {err}"},
    "log.query_running":        {"ja": "az graph query を実行中... (view={view})",
                                 "en": "Running az graph query... (view={view})"},
    "log.resources_found":      {"ja": "  → {count} 件のリソースを取得",
                                 "en": "  → Fetched {count} resource(s)"},
    "log.net_resources_found":  {"ja": "  → {nodes} 件のネットワークリソース, {edges} 件の接続を取得",
                                 "en": "  → Fetched {nodes} network resource(s), {edges} connection(s)"},
    "log.limit_reached":        {"ja": "  ⚠ 上限 {limit} に達しています。実際はもっとあるかもしれません。",
                                 "en": "  ⚠ Limit of {limit} reached. More resources may exist."},
    "log.ai_review_start":      {"ja": "🤖 AI レビューを開始...",     "en": "🤖 Starting AI review..."},
    "log.ai_review_skip":       {"ja": "AI レビューをスキップ: {err}", "en": "AI review skipped: {err}"},
    "log.generating_xml":       {"ja": ".drawio XML を生成中...",      "en": "Generating .drawio XML..."},
    "log.auto_save":            {"ja": "  自動保存: {path}",           "en": "  Auto-saved: {path}"},
    "log.save_not_selected":    {"ja": "保存先が選択されませんでした", "en": "No save destination selected"},
    "log.done":                 {"ja": "完了!",                         "en": "Done!"},
    "log.template_info":        {"ja": "  Template: {name} ({enabled}/{total} セクション)",
                                 "en": "  Template: {name} ({enabled}/{total} sections)"},
    "log.custom_instr_info":    {"ja": "  追加指示: {text}",           "en": "  Instructions: {text}"},
    "log.sec_collecting":       {"ja": "🔒 セキュリティデータを収集中...",
                                 "en": "🔒 Collecting security data..."},
    "log.sec_score":            {"ja": "  セキュアスコア: {current} / {max}",
                                 "en": "  Secure Score: {current} / {max}"},
    "log.sec_assess":           {"ja": "  評価: {total}件 (Healthy:{healthy}, Unhealthy:{unhealthy})",
                                 "en": "  Assessments: {total} (Healthy:{healthy}, Unhealthy:{unhealthy})"},
    "log.sec_ai_gen":           {"ja": "🤖 AI セキュリティレポートを生成中...",
                                 "en": "🤖 Generating AI security report..."},
    "log.cost_collecting":      {"ja": "💰 コストデータを収集中...",   "en": "💰 Collecting cost data..."},
    "log.cost_by_svc":          {"ja": "  サービス別コスト: {count}件",
                                 "en": "  Cost by service: {count} entries"},
    "log.cost_by_rg":           {"ja": "  RG別コスト: {count}件",      "en": "  Cost by RG: {count} entries"},
    "log.advisor_collecting":   {"ja": "📝 Advisor 推奨事項を収集中...",
                                 "en": "📝 Collecting Advisor recommendations..."},
    "log.cost_ai_gen":          {"ja": "🤖 AI コストレポートを生成中...",
                                 "en": "🤖 Generating AI cost report..."},
    "log.ai_report_error":      {"ja": "AI レポートエラー: {err}",     "en": "AI report error: {err}"},
    "log.report_failed":        {"ja": "レポート生成に失敗しました",   "en": "Report generation failed"},
    "log.word_output":          {"ja": "  → {path} (Word)",            "en": "  → {path} (Word)"},
    "log.word_error":           {"ja": "  Word 出力エラー: {err}",     "en": "  Word export error: {err}"},
    "log.pdf_output":           {"ja": "  → {path} (PDF)",             "en": "  → {path} (PDF)"},
    "log.pdf_not_found":        {"ja": "  PDF 出力: Word/LibreOffice が見つかりません",
                                 "en": "  PDF: Word/LibreOffice not found"},
    "log.pdf_error":            {"ja": "  PDF 出力エラー: {err}",      "en": "  PDF export error: {err}"},
    "log.drawio_not_found":     {"ja": "Draw.io が見つかりません。OS既定で開きます",
                                 "en": "Draw.io not found. Opening with OS default"},
    "log.vscode_not_found":     {"ja": "VS Code が見つかりません。OS既定で開きます",
                                 "en": "VS Code not found. Opening with OS default"},

    # --- 保存済み指示 ---
    "instr.saved":              {"ja": "指示を保存しました: {label}",  "en": "Instruction saved: {label}"},
    "instr.check_to_delete":    {"ja": "削除する指示をチェックしてください",
                                 "en": "Check the instructions to delete"},
    "instr.deleted":            {"ja": "{count} 件の指示を削除しました",
                                 "en": "Deleted {count} instruction(s)"},
    "instr.template_saved":     {"ja": "テンプレート保存: {path}",     "en": "Template saved: {path}"},

    # --- ダイアログ ---
    "dlg.save_instruction":     {"ja": "指示を保存",                   "en": "Save Instruction"},
    "dlg.label_prompt":         {"ja": "チェックボックスに表示するラベル名:",
                                 "en": "Label for the checkbox:"},
    "dlg.delete_instruction":   {"ja": "指示を削除",                   "en": "Delete Instructions"},
    "dlg.delete_confirm":       {"ja": "チェック済みの {count} 件の指示を削除しますか？",
                                 "en": "Delete {count} checked instruction(s)?"},
    "dlg.save_drawio":          {"ja": "Save .drawio",                  "en": "Save .drawio"},
    "dlg.save_report":          {"ja": "Save {type} report",            "en": "Save {type} report"},
    "dlg.save_template":        {"ja": "Save Template",                 "en": "Save Template"},
    "dlg.template_name_prompt": {"ja": "テンプレート名を入力:",           "en": "Enter template name:"},
    "dlg.import_template":      {"ja": "テンプレートJSONを選択",         "en": "Select template JSON"},
    "dlg.sp_login":             {"ja": "Service Principal Login",        "en": "Service Principal Login"},
    "label.client_id":          {"ja": "Client ID (App ID)",             "en": "Client ID (App ID)"},
    "label.tenant_id":          {"ja": "Tenant ID",                      "en": "Tenant ID"},
    "label.client_secret":      {"ja": "Client Secret",                  "en": "Client Secret"},
    "btn.login":                {"ja": "Login",                          "en": "Login"},
    "btn.cancel_small":         {"ja": "Cancel",                         "en": "Cancel"},
    "log.sp_login_running":     {"ja": "SP で az login 実行中...",        "en": "Running az login with SP..."},
    "log.sp_login_success":     {"ja": "SP ログイン成功",                "en": "SP login succeeded"},
    "log.sp_login_failed":      {"ja": "SP ログイン失敗: {err}",         "en": "SP login failed: {err}"},
    "log.sp_login_missing":     {"ja": "Client ID / Tenant ID / Secret を入力してください", "en": "Please enter Client ID / Tenant ID / Secret"},
    "instr.template_imported":  {"ja": "テンプレートインポート: {path}", "en": "Template imported: {path}"},
    "dlg.select_output_dir":    {"ja": "出力フォルダを選択",           "en": "Select output folder"},

    # --- AI プロンプト言語切替指示（system prompt に追加） ---
    "ai.output_language":       {"ja": "日本語の Markdown 形式で出力してください。",
                                 "en": "Output in English Markdown format."},
}


# ============================================================
# ランタイム
# ============================================================

_current_lang: str = "ja"
_listeners: list = []
_PERSIST_KEY = "language"


def get_language() -> str:
    """現在の言語コード ('ja' | 'en') を返す。"""
    return _current_lang


def set_language(lang: str, *, persist: bool = True) -> None:
    """言語を切り替え、リスナーに通知する。persist=True で settings.json に保存。"""
    global _current_lang
    if lang not in ("ja", "en"):
        lang = "ja"
    _current_lang = lang
    if persist:
        _save_language(lang)
    for cb in _listeners:
        try:
            cb(lang)
        except Exception:
            pass


def on_language_changed(callback: Any) -> None:
    """言語変更時のコールバックを登録。"""
    _listeners.append(callback)


def load_saved_language() -> None:
    """起動時に settings.json から言語設定を復元する。"""
    try:
        from app_paths import load_setting
        lang = load_setting(_PERSIST_KEY, "ja")
        set_language(lang, persist=False)
    except Exception:
        pass


def _save_language(lang: str) -> None:
    """settings.json に言語設定を保存する。"""
    try:
        from app_paths import save_setting
        save_setting(_PERSIST_KEY, lang)
    except Exception:
        pass


def t(key: str, **kwargs: Any) -> str:
    """翻訳キーから現在の言語の文字列を取得する。

    Args:
        key: 翻訳キー (例: "btn.collect")
        **kwargs: 文字列フォーマット引数 (例: count=5)

    Returns:
        翻訳済み文字列。キーが見つからなければキーそのものを返す。
    """
    entry = _STRINGS.get(key)
    if not entry:
        return key
    text = entry.get(_current_lang, entry.get("ja", key))
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text
