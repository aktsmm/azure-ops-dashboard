# Azure Env Builder Spec

- generated_at: 2026-02-20T07:07:36.778535
- python: 3.12.12
- platform: Windows-11-10.0.26200-SP0

## Input

```text
storageだけの検証環境
```

## Target

- subscription: 832c4080-181c-476b-9db0-b3ce9596d40a
- resource_group: brief
- location: japaneast
- what_if: True

## az commands

- az account show --query id -o tsv
- az group show --name brief -o json
- az deployment group what-if --name envb-20260220-070723 --resource-group brief --template-file main.bicep --parameters @main.parameters.json -o json
