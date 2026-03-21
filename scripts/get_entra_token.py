"""
Entra ID アクセストークンを Device Code Flow で取得し、.env に書き込むスクリプト。

Usage:
    uv run python scripts/get_entra_token.py [--version {1,2}]

Options:
    --version {1,2}   Token version to acquire (default: 2).
                      v2 → saved as ENTRA_ACCESS_TOKEN
                      v1 → saved as ENTRA_ACCESS_TOKEN_V1

Prerequisites:
    - .env に AZURE_TENANT_ID と AZURE_CLIENT_ID が設定済みであること
    - Entra ID の App Registration で Device Code Flow が有効であること
      (Azure Portal → App Registration → Authentication → Allow public client flows → ON)
"""

import argparse
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
TEST_IDENTIFIER_URI = os.getenv("TEST_IDENTIFIER_URI")
TEST_IDENTIFIER_URI_V1 = os.getenv("TEST_IDENTIFIER_URI_V1")

if not TENANT_ID or not CLIENT_ID:
    print("ERROR: AZURE_TENANT_ID and AZURE_CLIENT_ID must be set in .env")
    sys.exit(1)

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = [f"{TEST_IDENTIFIER_URI}/access", "email"]
SCOPES_V1 = [f"{TEST_IDENTIFIER_URI_V1}/access", "email"]

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Acquire an Entra ID access token via Device Code Flow and write it to .env."
    )
    parser.add_argument(
        "--version",
        choices=["1", "2"],
        default="2",
        help="Entra ID token version to acquire (default: 2)",
    )
    args = parser.parse_args()

    env_key = "ENTRA_ACCESS_TOKEN" if args.version == "2" else "ENTRA_ACCESS_TOKEN_V1"

    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)

    if args.version == "1":
        flow = app.initiate_device_flow(scopes=SCOPES_V1)
    else:
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
        if env_key in content:
            content = re.sub(
                rf"^{env_key}=.*$",
                f"{env_key}={token}",
                content,
                flags=re.MULTILINE,
            )
        else:
            content += f"\n# Integration test token (expires in ~1 hour)\n{env_key}={token}\n"
        env_path.write_text(content)
        print(f"✓ {env_key} written to .env")
    else:
        print(f"{env_key}={token}")
        print("\n(No .env file found — copy the value above manually)")


if __name__ == "__main__":
    main()
