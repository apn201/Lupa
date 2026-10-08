# Deploy Lupa behind Apache — prompt for OpenClaw

Copy everything below the line into OpenClaw, running on the target server. Change `HOST` if the
demo should live somewhere other than `lupa.helppox.com`. The prompt contains no secrets on
purpose: the `.env` values are filled in by hand at step 6.

---

You are deploying a small Python web app called Lupa on this Linux server, behind the Apache that
already runs here. Work carefully: this server hosts other sites, so change nothing that belongs
to them. Stop and report instead of guessing whenever a step fails or something looks different
from what this prompt expects.

**Target**
- HOST: `lupa.helppox.com` (a new subdomain; its own Apache vhost)
- Repo: `git@github.com:apn201/Lupa.git` (private; read access through a deploy key)
- Install dir: `/opt/lupa`, owned by a new system user `lupa`
- App port: `127.0.0.1:8710` (local only; Apache proxies to it)
- Templates in the repo: `deploy/lupa.service`, `deploy/apache-lupa.conf`

**Steps**

1. **Look first.** Report: OS and version, `apache2 -v` (or `httpd -v`), enabled Apache modules,
   existing vhosts (`apache2ctl -S`), whether port 8710 is free (`ss -ltnp`), the Python versions
   available, and whether `HOST` resolves to this server's public IP (`dig +short HOST` vs
   `curl -s https://ifconfig.me`). If DNS does not point here, stop and tell me which A record to create.

2. **Python 3.12+.** If `python3.12` (or newer) is not installed, install `uv`
   (`curl -LsSf https://astral.sh/uv/install.sh | sh`) and use `uv python install 3.12`.
   Do not replace or upgrade the system Python.

3. **User and directory.** `sudo useradd --system --home /opt/lupa --shell /usr/sbin/nologin lupa`,
   create `/opt/lupa`, owned by `lupa`.

4. **Deploy key.** As user `lupa`, create `~/.ssh/id_ed25519` (no passphrase) and print the public
   key. Stop and ask me to add it as a **read-only** deploy key at
   https://github.com/apn201/Lupa/settings/keys. Continue when I confirm. Then clone the repo into
   `/opt/lupa` (`git clone git@github.com:apn201/Lupa.git /opt/lupa`, accepting GitHub's host key).

5. **Install.** In `/opt/lupa` as `lupa`: create `.venv` with Python 3.12+, then
   `.venv/bin/pip install -e ".[mcp]"`. Create `/opt/lupa/var` owned by `lupa`.

6. **Secrets.** Copy `.env.example` to `/opt/lupa/.env`, owner `lupa`, mode `600`. Set
   `LUPA_DB=/opt/lupa/var/lupa.db`, `LLM_MAX_CALLS_PER_HOUR=30`, `LLM_MAX_CALLS_PER_DAY=300`.
   Then stop and ask me to fill in `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`,
   `LUPA_TEST_CARD_*`, `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` myself (I will edit the file
   over SSH). Never print, log, echo or commit the contents of `.env`.

7. **Seed the ledger.** As `lupa`: `.venv/bin/python -m lupa import`. Expect a line like
   `N companies can take money from you.`

8. **Service.** Install `deploy/lupa.service` to `/etc/systemd/system/lupa.service`,
   `systemctl daemon-reload`, `enable --now lupa`. Check `curl -s http://127.0.0.1:8710/paypal/status`
   returns JSON with `"enabled": true`.

9. **Apache.** Install `deploy/apache-lupa.conf` as a new site, replacing `lupa.example.com` with
   `HOST`. Enable only the modules it needs (`proxy proxy_http headers ssl rewrite`) if they are
   not already enabled. `apache2ctl configtest` must say `Syntax OK` before any reload; if it does
   not, revert your file and stop. Then `systemctl reload apache2` (reload, not restart).

10. **TLS.** `certbot --apache -d HOST` (install certbot if missing; choose redirect HTTP to
    HTTPS). Do not touch other sites' certificates.

11. **Verify from outside** and report each result:
    - `curl -s https://HOST/` returns the HTML page titled `Lupa`
    - `curl -s https://HOST/proposed/v1/me/payment-permissions | head -c 300` contains `"marker":"◇"`
    - `curl -s https://HOST/paypal/status` shows `"enabled": true`
    - `curl -s -o /dev/null -w '%{http_code}' https://HOST/docs` is `200`
    - `systemctl status lupa --no-pager` is active, and `journalctl -u lupa -n 20` has no tracebacks

12. **Updating later** (write this as `/opt/lupa/deploy/update.sh`, owned by root, mode 755):
    `sudo -u lupa git -C /opt/lupa pull --ff-only && sudo -u lupa /opt/lupa/.venv/bin/pip install -e "/opt/lupa[mcp]" && systemctl restart lupa`.

**Finish** with a short report: the URL, what you changed outside `/opt/lupa` (files and modules),
and anything you skipped and why. Then remind me to register `https://HOST/paypal/webhook` as a
webhook in the PayPal Developer Dashboard (sandbox app) and put its id in `PAYPAL_WEBHOOK_ID`.

**Do not**: open port 8710 in the firewall, run the app as root, change other vhosts, restart
Apache when a reload is enough, or put secrets in any file other than `/opt/lupa/.env`.
