param(
  [Parameter(Mandatory=$false)]
  [string]$SubscriptionId = "",

  [Parameter(Mandatory=$false)]
  [string]$ResourceGroup = "",

  [Parameter(Mandatory=$false)]
  [int]$Limit = 300,

  [Parameter(Mandatory=$false)]
  [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

function Ensure-OutDir([string]$dir) {
  if (-not $dir) {
    $dir = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "AzureOpsDashboard"
  }
  if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }
  return (Resolve-Path $dir).Path
}

function Now-Stamp() {
  return (Get-Date).ToString("yyyyMMdd-HHmmss")
}

function Run-Az([string[]]$args, [string]$outPath) {
  Write-Host ("[az] " + ($args -join " "))
  $json = & az @args 2>&1
  $exit = $LASTEXITCODE
  $json | Out-File -FilePath $outPath -Encoding utf8
  if ($exit -ne 0) {
    throw "az command failed (exit=$exit). See: $outPath"
  }
}

$out = Ensure-OutDir $OutDir
$stamp = Now-Stamp

if (-not $SubscriptionId) {
  $SubscriptionId = (& az account show --query id -o tsv).Trim()
}

if (-not $SubscriptionId) {
  throw "SubscriptionId is required (or run az login and ensure az account show works)."
}

$rgWhere = ""
if ($ResourceGroup) {
  $rgEsc = $ResourceGroup.Replace("'", "''")
  $rgWhere = "| where resourceGroup =~ '$rgEsc'"
}

# Inventory
$invQuery = @"
Resources
$rgWhere
| project id, name, type, resourceGroup, location
| order by type asc, name asc
| limit $Limit
"@.Trim()

$invPath = Join-Path $out "inventory-$stamp.json"
Run-Az @("graph","query","-q",$invQuery,"--subscriptions",$SubscriptionId,"--first","1000","--output","json") $invPath

# Network (subset)
$netTypes = @(
  "microsoft.network/virtualnetworks",
  "microsoft.network/networksecuritygroups",
  "microsoft.network/networkinterfaces",
  "microsoft.network/publicipaddresses",
  "microsoft.network/loadbalancers",
  "microsoft.network/applicationgateways",
  "microsoft.network/connections",
  "microsoft.network/networkwatchers",
  "microsoft.compute/virtualmachines"
)
$typeFilter = ($netTypes | ForEach-Object { "'$_'" }) -join ", "
$netQuery = @"
Resources
$rgWhere
| where type in~ ($typeFilter)
| project id, name, type, resourceGroup, location, properties
| order by type asc, name asc
| limit $Limit
"@.Trim()

$netPath = Join-Path $out "network-$stamp.json"
Run-Az @("graph","query","-q",$netQuery,"--subscriptions",$SubscriptionId,"--first","1000","--output","json") $netPath

# Security Center / Defender (REST)
$secureScores = Join-Path $out "security-secureScores-$stamp.json"
Run-Az @("rest","--method","GET","--uri","https://management.azure.com/subscriptions/$SubscriptionId/providers/Microsoft.Security/secureScores?api-version=2020-01-01","--output","json") $secureScores

$assessments = Join-Path $out "security-assessments-$stamp.json"
Run-Az @("rest","--method","GET","--uri","https://management.azure.com/subscriptions/$SubscriptionId/providers/Microsoft.Security/assessments?api-version=2021-06-01","--output","json") $assessments

$pricings = Join-Path $out "security-pricings-$stamp.json"
Run-Az @("rest","--method","GET","--uri","https://management.azure.com/subscriptions/$SubscriptionId/providers/Microsoft.Security/pricings?api-version=2024-01-01","--output","json") $pricings

# Cost Management (MonthToDate)
$costByServiceBody = @'
{
  "type": "Usage",
  "timeframe": "MonthToDate",
  "dataset": {
    "granularity": "None",
    "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
    "grouping": [{"name": "ServiceName", "type": "Dimension"}]
  }
}
'@

$costByService = Join-Path $out "cost-by-service-$stamp.json"
Run-Az @("rest","--method","POST","--uri","https://management.azure.com/subscriptions/$SubscriptionId/providers/Microsoft.CostManagement/query?api-version=2023-11-01","--body",$costByServiceBody,"--output","json") $costByService

$costByRgBody = @'
{
  "type": "Usage",
  "timeframe": "MonthToDate",
  "dataset": {
    "granularity": "None",
    "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
    "grouping": [{"name": "ResourceGroup", "type": "Dimension"}]
  }
}
'@

$costByRg = Join-Path $out "cost-by-rg-$stamp.json"
Run-Az @("rest","--method","POST","--uri","https://management.azure.com/subscriptions/$SubscriptionId/providers/Microsoft.CostManagement/query?api-version=2023-11-01","--body",$costByRgBody,"--output","json") $costByRg

# Advisor recommendations
$advisor = Join-Path $out "advisor-recommendations-$stamp.json"
Run-Az @("advisor","recommendation","list","--subscription",$SubscriptionId,"--output","json") $advisor

Write-Host "Done. Output folder: $out"