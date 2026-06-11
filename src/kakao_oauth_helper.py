import argparse
import urllib.parse

import requests


AUTH_BASE = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


def print_auth_url(rest_api_key: str, redirect_uri: str) -> None:
    params = {
        "client_id": rest_api_key,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "talk_message",
    }
    print(f"{AUTH_BASE}?{urllib.parse.urlencode(params)}")


def exchange_code(rest_api_key: str, redirect_uri: str, code: str, client_secret: str | None) -> None:
    data = {
        "grant_type": "authorization_code",
        "client_id": rest_api_key,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    if client_secret:
        data["client_secret"] = client_secret

    response = requests.post(
        TOKEN_URL,
        data=data,
        timeout=20,
    )
    if not response.ok:
        print(response.text)
        response.raise_for_status()
    print(response.text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Kakao OAuth helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_url = subparsers.add_parser("auth-url")
    auth_url.add_argument("--rest-api-key", required=True)
    auth_url.add_argument("--redirect-uri", required=True)

    token = subparsers.add_parser("token")
    token.add_argument("--rest-api-key", required=True)
    token.add_argument("--client-secret")
    token.add_argument("--redirect-uri", required=True)
    token.add_argument("--code", required=True)

    args = parser.parse_args()

    if args.command == "auth-url":
        print_auth_url(args.rest_api_key, args.redirect_uri)
    elif args.command == "token":
        exchange_code(args.rest_api_key, args.redirect_uri, args.code, args.client_secret)


if __name__ == "__main__":
    main()
