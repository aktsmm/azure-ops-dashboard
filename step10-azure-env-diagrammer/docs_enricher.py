"""Step10: Microsoft Docs エンリッチャー

レポート生成前に Microsoft Learn から関連ドキュメントを取得し、
プロンプトに埋め込む参照情報を生成する。

方式:
  1. 静的リファレンスマップ（リソースタイプ → 公式ドキュメント URL）
  2. Microsoft Learn 検索 API（補助。ヒットすれば追加）
  - ネットワーク到達不可 / タイムアウト時はフォールバック（静的マップのみ）
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from i18n import get_language


@dataclass(frozen=True)
class DocReference:
    title: str
    url: str
    description: str


def _docs_locale() -> str:
    return "en-us" if get_language() == "en" else "ja-jp"


def _azure_base() -> str:
    return f"https://learn.microsoft.com/{_docs_locale()}/azure"


# ============================================================
# 静的リファレンスマップ（高品質・オフライン対応）
# ============================================================


def _security_refs() -> list[DocReference]:
    base = _azure_base()
    if get_language() == "en":
        return [
            DocReference(
                "Azure security best practices",
                f"{base}/security/best-practices-and-patterns",
                "Core Azure security principles and best practices",
            ),
            DocReference(
                "Microsoft Defender for Cloud overview",
                f"{base}/defender-for-cloud/defender-for-cloud-introduction",
                "Cloud security posture management (CSPM) and workload protection",
            ),
            DocReference(
                "Network security groups (NSGs)",
                f"{base}/virtual-network/network-security-groups-overview",
                "Filter network traffic using NSGs",
            ),
            DocReference(
                "Azure Private Link and Private Endpoints",
                f"{base}/private-link/private-link-overview",
                "Private connectivity to Azure services",
            ),
            DocReference(
                "Azure Key Vault best practices",
                f"{base}/key-vault/general/best-practices",
                "Manage secrets, keys, and certificates",
            ),
        ]
    return [
        DocReference(
            "Azure セキュリティのベスト プラクティス",
            f"{base}/security/best-practices-and-patterns",
            "Azure セキュリティの基本原則とベストプラクティス一覧",
        ),
        DocReference(
            "Microsoft Defender for Cloud の概要",
            f"{base}/defender-for-cloud/defender-for-cloud-introduction",
            "クラウドセキュリティ態勢管理 (CSPM) とワークロード保護",
        ),
        DocReference(
            "ネットワーク セキュリティ グループ (NSG)",
            f"{base}/virtual-network/network-security-groups-overview",
            "NSG によるネットワークトラフィックのフィルタリング",
        ),
        DocReference(
            "Azure Private Link と Private Endpoint",
            f"{base}/private-link/private-link-overview",
            "Azure サービスへのプライベート接続",
        ),
        DocReference(
            "Azure Key Vault のベスト プラクティス",
            f"{base}/key-vault/general/best-practices",
            "シークレット、キー、証明書の管理",
        ),
    ]


def _cost_refs() -> list[DocReference]:
    base = _azure_base()
    if get_language() == "en":
        return [
            DocReference(
                "Azure Cost Management best practices",
                f"{base}/cost-management-billing/costs/best-practices-cost-management",
                "Best practices for monitoring, analyzing, and optimizing costs",
            ),
            DocReference(
                "Azure Advisor cost recommendations",
                f"{base}/advisor/advisor-cost-recommendations",
                "Advisor recommendations for cost optimization",
            ),
            DocReference(
                "Azure pricing calculator",
                "https://azure.microsoft.com/en-us/pricing/calculator/",
                "Cost estimation tool for Azure services",
            ),
            DocReference(
                "Save with Azure Reservations",
                f"{base}/cost-management-billing/reservations/save-compute-costs-reservations",
                "Reduce costs with reserved instances",
            ),
        ]
    return [
        DocReference(
            "Azure Cost Management のベスト プラクティス",
            f"{base}/cost-management-billing/costs/best-practices-cost-management",
            "コストの監視、分析、最適化のベストプラクティス",
        ),
        DocReference(
            "Azure Advisor のコスト推奨事項",
            f"{base}/advisor/advisor-cost-recommendations",
            "Advisor によるコスト最適化の推奨事項",
        ),
        DocReference(
            "Azure の料金計算ツール",
            "https://azure.microsoft.com/ja-jp/pricing/calculator/",
            "Azure サービスの見積もりツール",
        ),
        DocReference(
            "Azure 予約による割引",
            f"{base}/cost-management-billing/reservations/save-compute-costs-reservations",
            "予約インスタンスによるコスト削減",
        ),
    ]


def _resource_type_refs() -> dict[str, DocReference]:
    base = _azure_base()
    if get_language() == "en":
        return {
            "microsoft.compute/virtualmachines": DocReference(
                "Virtual Machines overview",
                f"{base}/virtual-machines/overview",
                "Overview and guidance for Azure VMs",
            ),
            "microsoft.network/virtualnetworks": DocReference(
                "Azure Virtual Network overview",
                f"{base}/virtual-network/virtual-networks-overview",
                "Design and secure VNets",
            ),
            "microsoft.storage/storageaccounts": DocReference(
                "Security recommendations for Blob storage",
                f"{base}/storage/blobs/security-recommendations",
                "Security best practices for storage accounts",
            ),
            "microsoft.sql/servers": DocReference(
                "Security in Azure SQL Database",
                f"{base}/azure-sql/database/security-overview",
                "Security features overview for SQL Database",
            ),
            "microsoft.web/sites": DocReference(
                "App Service security",
                f"{base}/app-service/overview-security",
                "Security guidance for App Service",
            ),
            "microsoft.containerservice/managedclusters": DocReference(
                "AKS security concepts",
                f"{base}/aks/concepts-security",
                "Security concepts for Azure Kubernetes Service",
            ),
            "microsoft.keyvault/vaults": DocReference(
                "Key Vault best practices",
                f"{base}/key-vault/general/best-practices",
                "Best practices for Key Vault usage",
            ),
            "microsoft.network/applicationgateways": DocReference(
                "Application Gateway overview",
                f"{base}/application-gateway/overview",
                "L7 load balancer and WAF",
            ),
            "microsoft.network/loadbalancers": DocReference(
                "Azure Load Balancer overview",
                f"{base}/load-balancer/load-balancer-overview",
                "Design guidance for L4 load balancing",
            ),
        }
    return {
        "microsoft.compute/virtualmachines": DocReference(
            "仮想マシンのベスト プラクティス",
            f"{base}/virtual-machines/overview",
            "Azure VM の概要とベストプラクティス",
        ),
        "microsoft.network/virtualnetworks": DocReference(
            "Azure Virtual Network の概要",
            f"{base}/virtual-network/virtual-networks-overview",
            "VNet の設計とセキュリティ",
        ),
        "microsoft.storage/storageaccounts": DocReference(
            "Azure Storage のセキュリティ推奨事項",
            f"{base}/storage/blobs/security-recommendations",
            "ストレージアカウントのセキュリティベストプラクティス",
        ),
        "microsoft.sql/servers": DocReference(
            "Azure SQL Database のセキュリティ",
            f"{base}/azure-sql/database/security-overview",
            "SQL Database のセキュリティ機能の概要",
        ),
        "microsoft.web/sites": DocReference(
            "App Service のセキュリティ",
            f"{base}/app-service/overview-security",
            "App Service のセキュリティに関する推奨事項",
        ),
        "microsoft.containerservice/managedclusters": DocReference(
            "AKS セキュリティのベスト プラクティス",
            f"{base}/aks/concepts-security",
            "Azure Kubernetes Service のセキュリティ概念",
        ),
        "microsoft.keyvault/vaults": DocReference(
            "Key Vault のベスト プラクティス",
            f"{base}/key-vault/general/best-practices",
            "Key Vault の使用に関するベストプラクティス",
        ),
        "microsoft.network/applicationgateways": DocReference(
            "Application Gateway の概要",
            f"{base}/application-gateway/overview",
            "L7 ロードバランサーと WAF",
        ),
        "microsoft.network/loadbalancers": DocReference(
            "Azure Load Balancer の概要",
            f"{base}/load-balancer/load-balancer-overview",
            "L4 ロードバランサーの設計",
        ),
    }


# ============================================================
# Learn 検索 API（補助）
# ============================================================

_SEARCH_URL = "https://learn.microsoft.com/api/search"
_TIMEOUT = 8  # sec


def search_docs(
    query: str,
    locale: str = "ja-jp",
    top: int = 5,
    on_status: Optional[Callable[[str], None]] = None,
) -> list[DocReference]:
    """Microsoft Learn を検索し、関連ドキュメント参照を返す。

    失敗時は空リストを返す（例外は投げない）。
    """
    log = on_status or (lambda s: None)

    params = urllib.parse.urlencode({
        "search": query,
        "locale": locale,
        "$top": top,
    })
    url = f"{_SEARCH_URL}?{params}"

    try:
        log(f"Microsoft Docs 検索中: {query[:60]}...")
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        log(f"Microsoft Docs 検索スキップ（{type(e).__name__}: {e}）")
        return []

    results: list[DocReference] = []
    for item in data.get("results", []):
        title = item.get("title", "").strip()
        item_url = item.get("url", "").strip()
        desc = item.get("description", "").strip()
        if title and item_url:
            if item_url.startswith("/"):
                item_url = f"https://learn.microsoft.com{item_url}"
            # Azure ドキュメントのみ採用
            if "/azure/" in item_url or "/defender" in item_url:
                results.append(DocReference(title=title, url=item_url, description=desc))

    log(f"Microsoft Docs: {len(results)} 件取得")
    return results


def build_reference_block(refs: list[DocReference]) -> str:
    """DocReference リストからプロンプトに埋め込む Markdown ブロックを生成。"""
    if not refs:
        return ""

    if get_language() == "en":
        lines = [
            "",
            "## References: Microsoft official documentation",
            "",
            "Use the following official documentation as references for recommendations and best practices.",
            "Add Learn URLs as footnotes whenever possible.",
            "",
        ]
    else:
        lines = [
            "",
            "## 参考: Microsoft 公式ドキュメント",
            "",
            "以下の公式ドキュメントを参照し、推奨事項やベストプラクティスに基づいたコメントを含めてください。",
            "各推奨事項には可能な限り該当ドキュメントの URL を脚注として付けてください。",
            "",
        ]
    for i, ref in enumerate(refs, 1):
        lines.append(f"{i}. [{ref.title}]({ref.url})")
        if ref.description:
            lines.append(f"   — {ref.description[:120]}")
    lines.append("")
    return "\n".join(lines)


# ============================================================
# レポート種別ごとのクエリ/参照生成
# ============================================================

def security_search_queries(resource_types: list[str] | None = None) -> list[str]:
    """セキュリティレポート向けの検索クエリを生成。"""
    base = [
        "Azure security best practices Microsoft Defender for Cloud",
    ]
    if resource_types:
        type_keywords = set()
        for rt in resource_types[:10]:
            short = rt.split("/")[-1].lower()
            type_keywords.add(f"Azure {short} security best practices")
        base.extend(list(type_keywords)[:3])
    return base


def cost_search_queries(resource_types: list[str] | None = None) -> list[str]:
    """コストレポート向けの検索クエリを生成。"""
    base = [
        "Azure cost optimization best practices",
    ]
    if resource_types:
        type_keywords = set()
        for rt in resource_types[:10]:
            short = rt.split("/")[-1].lower()
            type_keywords.add(f"Azure {short} pricing optimization")
        base.extend(list(type_keywords)[:3])
    return base


def enrich_with_docs(
    queries: list[str],
    report_type: str = "security",
    resource_types: list[str] | None = None,
    locale: str = "ja-jp",
    max_refs: int = 10,
    on_status: Optional[Callable[[str], None]] = None,
) -> str:
    """静的マップ + API 検索で参照ブロックを生成。"""
    log = on_status or (lambda s: None)
    seen_urls: set[str] = set()
    all_refs: list[DocReference] = []

    # locale の既定は現在のUI言語
    locale = "en-us" if get_language() == "en" else "ja-jp"

    # 1. 静的リファレンス（常に利用可能）
    static_refs = _security_refs() if report_type == "security" else _cost_refs()
    for ref in static_refs:
        if ref.url not in seen_urls and len(all_refs) < max_refs:
            all_refs.append(ref)
            seen_urls.add(ref.url)

    # 2. リソースタイプ固有の参照
    if resource_types:
        rmap = _resource_type_refs()
        for rt in resource_types:
            rt_lower = rt.lower()
            if rt_lower in rmap:
                ref = rmap[rt_lower]
                if ref.url not in seen_urls and len(all_refs) < max_refs:
                    all_refs.append(ref)
                    seen_urls.add(ref.url)

    # 3. API 検索（補助 — 失敗しても静的リファレンスがある）
    for q in queries[:2]:  # API コールは最大2回に制限
        api_refs = search_docs(q, locale=locale, top=3, on_status=log)
        for ref in api_refs:
            if ref.url not in seen_urls and len(all_refs) < max_refs:
                all_refs.append(ref)
                seen_urls.add(ref.url)

    log(f"公式ドキュメント参照: {len(all_refs)} 件をプロンプトに追加")
    return build_reference_block(all_refs)
