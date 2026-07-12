---
title: Versioning
order: 2
---

# Versioning

Every document in Runbook tracks a version history. Versions are created manually — you control when a snapshot is taken.

## How It Works

- Each document starts at **v1**
- Clicking **New Version** uploads a replacement file, incrementing the version number
- The previous version is preserved and accessible from the **Versions** page
- Only the latest version is shown in search results and document lists

## Editing vs. Versioning

There are two distinct ways to change a document:

| Action | Creates a version? | Use when |
|--------|--------------------|----------|
| **Edit Content** (in-browser editor) | No | Making quick edits, fixing typos, updating sections |
| **New Version** (file upload) | Yes | Major revisions, replacing the entire document |

The in-browser editor writes directly to the file on disk. This is intentional — it keeps editing fast and avoids cluttering the version history with minor changes. Use **New Version** when you want to create a trackable milestone.

## Restoring Old Versions

From the **Versions** page, click **Restore** on any previous version. This creates a *new* version (e.g., v4) with the content from the old version — it does not delete or overwrite anything. The version chain is append-only.

## Version Storage

- All versions are kept indefinitely (no automatic pruning)
- Each version retains its own file on disk
- Old version files are not deleted when new versions are uploaded
