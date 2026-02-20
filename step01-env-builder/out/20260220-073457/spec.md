# Azure Env Builder Spec

- generated_at: 2026-02-20T07:35:32.840336
- python: 3.12.12
- platform: Windows-11-10.0.26200-SP0

## Input

```text
storageだけの検証環境
```

## Target

- subscription: 832c4080-181c-476b-9db0-b3ce9596d40a
- resource_group: envb-20260220-073450
- location: japaneast
- what_if: True

## az commands

- az account show --query id -o tsv
- az group show --name envb-20260220-073450 -o json
- az deployment group what-if --name envb-20260220-073457 --resource-group envb-20260220-073450 --template-file main.bicep --parameters @main.parameters.json -o json
