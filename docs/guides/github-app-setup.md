# GitHub App setup

Code analysis reads repositories through a **GitHub App** you own. Until it is configured the dashboard shows
"GitHub App: Not configured"; nothing is faked. The platform never needs a personal access token.

## 1. Create the App
GitHub → Settings → Developer settings → GitHub Apps → *New GitHub App*.

| Field | Value |
|---|---|
| Webhook URL | `https://<your-gateway>/v1/github/webhook` |
| Webhook secret | a long random string (you will also set it as `GITHUB_WEBHOOK_SECRET`) |
| Setup URL (post-installation) | `https://<your-dashboard>/repositories` , tick *Redirect on update* |
| Repository permissions | Contents: **Read-only**, Metadata: **Read-only**, Pull requests: **Read-only** |
| Subscribe to events | `Push`, `Pull request`, `Installation`, `Installation repositories` |

Read-only permissions are enough: the platform downloads a tarball snapshot and never writes to your repository.
Generate a **private key** (.pem) on the App page.

## 2. Configure the gateway (environment only)
```
GITHUB_APP_ID=123456
GITHUB_APP_SLUG=your-app-slug
GITHUB_WEBHOOK_SECRET=<same secret as above>
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"   # or:
GITHUB_APP_PRIVATE_KEY_PATH=/run/secrets/github-app.pem
SCAN_WORKER_ENABLED=true          # or run the separate scan-worker container
```
Never commit the key. `GET /v1/workspaces/{id}/github/status` lists which variables are still missing (names only).

## 3. Install and connect
Dashboard → Repositories → *Install GitHub App* → pick repositories → return to the dashboard → *Sync*, then
*Connect* the repositories to analyse. Pushes to the default branch and pull-request updates queue scans automatically.

## Security notes
* The install `state` is single-use and expires after 10 minutes. One installation belongs to one workspace.
* Webhooks are verified with HMAC-SHA256 and deduplicated by delivery id.
* Snapshots are extracted with traversal/link/device/size guards and **scanned, never executed** (see `code-scanning.md`).
