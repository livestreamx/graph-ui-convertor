# GitHub Merge Gate Setup (UI Checklist)

Use this after pushing workflow from `.github/workflows/ci.yml`.

## 1) Open branch protection

1. GitHub -> repository -> `Settings` -> `Branches`.
2. In `Branch protection rules`, add a rule for `main` (or your target protected branch).

## 2) Enable required PR checks

Turn on:

- `Require a pull request before merging`
- `Require status checks to pass before merging`
- `Require branches to be up to date before merging` (recommended)

In required checks select job `quality` from workflow `CI`
(can be shown as `quality` or `CI / quality` depending on UI).

## 3) Restrict direct pushes

Turn on:

- `Restrict who can push to matching branches` (select admins/service accounts only if needed)

## 4) Keep admin bypass

To allow admins to merge without successful CI:

- Keep `Do not allow bypassing the above settings` **disabled**.

This keeps CI mandatory for everyone except administrators.
