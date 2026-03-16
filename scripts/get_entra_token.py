"""
Entra ID アクセストークンを Device Code Flow で取得し、.env に書き込むスクリプト。

Usage:
    uv run python scripts/get_entra_token.py

Prerequisites:
    - .env に AZURE_TENANT_ID と AZURE_CLIENT_ID が設定済みであること
    - Entra ID の App Registration で Device Code Flow が有効であること
      (Azure Portal → App Registration → Authentication → Allow public client flows → ON)
"""

import pathlib
import re
import sys

import msal
from dotenv import load_dotenv

# .env から設定を読み込む
load_dotenv()

import os  # noqa: E402 (load_dotenv の後に import)

TENANT_ID = os.getenv("TEST_ENTRA_TENANT_ID")
CLIENT_ID = os.getenv("TEST_ENTRA_CLIENT_ID")
IDENTIFIER_URI = os.getenv("IDENTIFIER_URI")

if not TENANT_ID or not CLIENT_ID:
    print("ERROR: AZURE_TENANT_ID and AZURE_CLIENT_ID must be set in .env")
    sys.exit(1)

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = [f"{IDENTIFIER_URI}/access", "email"]


def main() -> None:
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print(f"ERROR: Failed to create device flow: {flow.get('error_description')}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(flow["message"])
    print("=" * 60 + "\n")

    result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        print(f"ERROR: {result.get('error')}: {result.get('error_description')}")
        sys.exit(1)

    token = result["access_token"]
    print("✓ Token acquired successfully.\n")

    # .env ファイルを更新
    env_path = pathlib.Path(".env")
    if env_path.exists():
        content = env_path.read_text()
        if "ENTRA_ACCESS_TOKEN" in content:
            content = re.sub(
                r"^ENTRA_ACCESS_TOKEN=.*$",
                f"ENTRA_ACCESS_TOKEN={token}",
                content,
                flags=re.MULTILINE,
            )
        else:
            content += f"\n# Integration test token (expires in ~1 hour)\nENTRA_ACCESS_TOKEN={token}\n"
        env_path.write_text(content)
        print("✓ ENTRA_ACCESS_TOKEN written to .env")
    else:
        print(f"ENTRA_ACCESS_TOKEN={token}")
        print("\n(No .env file found — copy the value above manually)")


if __name__ == "__main__":
    main()
