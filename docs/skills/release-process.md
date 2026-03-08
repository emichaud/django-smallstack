# Skill: Release Process

How to version, release, and publish SmallStack.

## Versioning

SmallStack uses **Semantic Versioning** (semver): `MAJOR.MINOR.PATCH`

| Level | When to Bump | Example |
|-------|-------------|---------|
| **PATCH** (0.7.0 → 0.7.1) | Bug fixes, doc updates, small improvements | Default for most releases |
| **MINOR** (0.7.1 → 0.8.0) | New features, new commands, new apps | Backwards-compatible additions |
| **MAJOR** (0.8.0 → 1.0.0) | Breaking changes, removed features | Changes that require downstream migration |

### Version Locations

Version must be updated in **three** places:

| File | Field | Example |
|------|-------|---------|
| `pyproject.toml` | `version = "X.Y.Z"` | `version = "0.7.1"` |
| `apps/help/smallstack/_config.yaml` | `version: "X.Y.Z"` | `version: "0.7.1"` |
| `README.md` | Coverage/version badges | Update badge URLs if needed |

## Pre-Release Checklist

Before any release, verify:

```bash
# 1. All tests pass
make test

# 2. Lint is clean
make lint

# 3. Coverage is acceptable (update badge if changed significantly)
make coverage

# 4. Dev server runs without errors
make run
```

## Release Steps

### 1. Ensure Main is Clean

```bash
git checkout main
git status                          # Should be clean
```

If on a feature branch, merge first:

```bash
git checkout main
git merge feature/my-feature
git branch -d feature/my-feature
```

### 2. Bump Version

Update the three version locations (see table above).

### 3. Commit the Release

```bash
git add pyproject.toml apps/help/smallstack/_config.yaml README.md uv.lock
git commit -m "v0.7.1: <release summary>"
```

Release commit messages follow the pattern: `vX.Y.Z: <1-2 sentence summary>`

Examples:
- `v0.7.1: Documentation improvements, Docker Compose V2, and test coverage integration`
- `v0.8.0: Add activity tracking dashboard with auto-pruning and staff views`

### 4. Push to GitHub

```bash
git push origin main
```

### 5. Create GitHub Release

```bash
gh release create v0.7.1 \
  --title "v0.7.1" \
  --notes "$(cat <<'EOF'
## What's New

- **Feature**: Brief description
- **Fix**: Brief description
- **Docs**: Brief description

## Stats

- X tests, Y% code coverage
- All lint checks passing

## Upgrade

Pull the latest from upstream:
\`\`\`bash
git pull origin main
make migrate
\`\`\`
EOF
)"
```

## Post-Release: Downstream Integration

After pushing a release, update downstream projects:

```bash
# In each downstream project (smallstack_web, opshugger, etc.)
cd ../smallstack_web
git pull upstream main              # Pull SmallStack updates
# Resolve any merge conflicts
make migrate                        # Run new migrations
make test                           # Verify nothing broke
git add -A && git commit -m "chore: Pull upstream SmallStack v0.7.1"
git push origin main
```

For downstream projects with deployment:
```bash
kamal deploy                        # or docker compose up -d --build
```

See `docs/skills/integration-workflow.md` for detailed downstream integration steps.

## Automation Opportunities

Future improvements:
- GitHub Actions CI to run tests + lint on every push
- Automated coverage badge via Codecov or similar
- Changelog generation from commit messages
- Pre-release hooks to verify version consistency
