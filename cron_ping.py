import os
import sys
import urllib.request


def run(base_url, endpoint, cron_secret):
    """Wake the web service before POSTing a scheduled task."""
    health_req = urllib.request.Request(f"{base_url}/health", method="GET")
    with urllib.request.urlopen(health_req, timeout=90) as health_res:
        health_res.read()
    url = f"{base_url}{endpoint}"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={"X-Cron-Secret": cron_secret},
    )
    with urllib.request.urlopen(req, timeout=90) as res:
        print(f"{endpoint} -> {res.status}")
        print(res.read().decode("utf-8"))


def main():
    endpoint = sys.argv[1] if len(sys.argv) > 1 else "/health"
    base_url = os.environ.get("APP_PUBLIC_URL", "").rstrip("/")
    cron_secret = os.environ.get("CRON_SECRET", "")
    if not base_url:
        raise SystemExit("APP_PUBLIC_URL is not set")
    run(base_url, endpoint, cron_secret)


if __name__ == "__main__":
    main()
