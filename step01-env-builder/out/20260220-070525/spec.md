# Azure Env Builder Spec

- generated_at: 2026-02-20T07:05:25.430657
- python: 3.12.12
- platform: Windows-11-10.0.26200-SP0

## Input

```text
storageだけの検証環境
```

## Target

- subscription: (az default)
- resource_group: brief
- location: japaneast
- what_if: True

## az commands

- az account show --query id -o tsv
- az group show --name brief -o json
