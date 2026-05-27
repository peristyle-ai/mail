#!/usr/bin/env python3
"""Local Email Skill — Mail server API client.

Reads config from environment variables. Supports --env flag or auto-detects
from CLAWBIE_ENV, ~/git/clawbie/.env, project .env, or ~/.env.

Environment variables (required):
    EMAIL_SERVER   — base URL of the mail server (e.g. http://192.168.4.41:5003)
    EMAIL_ADDRESS  — email account to authenticate as
    EMAIL_PASSWORD — account password

Environment variables (optional):
    EMAIL_TO       — default recipient for send command
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def find_env_file() -> Path | None:
	"""Search for .env in standard locations, in order of priority."""
	locations = [
		Path(os.environ.get("CLAWBIE_ENV", "")),
		Path.home() / "git" / "clawbie" / ".env",
		Path(__file__).resolve().parents[3] / ".env",
		Path.home() / ".env",
		Path(".env"),
	]
	for path in locations:
		if path.exists() and path.is_file():
			return path
	return None


def load_env(env_path: Path | None) -> dict[str, str]:
	"""Load environment variables from a .env file."""
	env: dict[str, str] = {}
	if env_path and env_path.exists():
		for line in env_path.read_text().splitlines():
			line = line.strip()
			if not line or line.startswith("#") or "=" not in line:
				continue
			key, _, value = line.partition("=")
			env[key.strip()] = value.strip().strip('"').strip("'")
	for key in ["EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_TO"]:
		if key not in env:
			env[key] = os.environ.get(key, "")
	return env


def require_env_vars(env: dict[str, str], *keys: str) -> None:
	"""Exit with a helpful message if any required var is missing."""
	missing = [k for k in keys if not env.get(k)]
	if missing:
		print(
			f"Error: missing required environment variables: {', '.join(missing)}",
			file=sys.stderr,
		)
		print(
			f"Set them in your .env file or as shell environment variables.",
			file=sys.stderr,
		)
		sys.exit(1)


def request_json(
	url: str,
	*,
	method: str = "GET",
	payload: dict[str, Any] | None = None,
	token: str | None = None,
) -> Any:
	"""Make an HTTP request and return parsed JSON."""
	headers: dict[str, str] = {}
	data: bytes | None = None
	if payload is not None:
		headers["Content-Type"] = "application/json"
		data = json.dumps(payload).encode("utf-8")
	if token:
		headers["Authorization"] = f"Bearer {token}"
	req = Request(url, data=data, headers=headers, method=method)
	with urlopen(req, timeout=20) as response:
		body = response.read().decode("utf-8")
	return json.loads(body) if body else None


def login(base_url: str, email: str, password: str) -> str:
	"""Authenticate and return a session token."""
	data = request_json(
		f"{base_url.rstrip('/')}/auth/login",
		method="POST",
		payload={"email": email, "password": password},
	)
	token = data.get("token") if isinstance(data, dict) else None
	if not token:
		raise SystemExit("Login succeeded but no token was returned")
	return token


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_login(args: argparse.Namespace, env: dict[str, str]) -> None:
	email = env["EMAIL_ADDRESS"]
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], email, env["EMAIL_PASSWORD"])
	print(json.dumps({"login_ok": True, "email": email, "token_prefix": token[:10]}, indent=2))


def cmd_list(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	params = []
	if args.folder:
		params.append(f"folder={args.folder}")
	if args.limit:
		params.append(f"limit={args.limit}")
	qs = f"?{'&'.join(params)}" if params else ""
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/emails{qs}",
		token=token,
	)
	items = payload if isinstance(payload, list) else (
		payload.get("emails") or payload.get("items") or payload.get("data") or []
	)
	if not isinstance(items, list):
		items = []
	print(json.dumps(items[:args.limit], indent=2, ensure_ascii=False))


def cmd_read(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/emails/{args.id}",
		token=token,
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_search(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	query = urlencode({"q": args.query})
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/search?{query}",
		token=token,
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_send(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	to = args.to or env.get("EMAIL_TO", "")
	if not to:
		raise SystemExit("Error: --to is required when EMAIL_TO is not set")
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/emails",
		method="POST",
		token=token,
		payload={"to": to, "subject": args.subject, "body": args.body},
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_status(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/emails/{args.id}/delivery-status",
		token=token,
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_move(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/emails/{args.id}/move",
		method="POST",
		token=token,
		payload={"folder_id": args.folder_id},
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_folders(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/folders",
		token=token,
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_delete(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/emails/{args.id}",
		method="DELETE",
		token=token,
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_read_mark(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/emails/{args.id}/read",
		method="POST",
		token=token,
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_star(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/emails/{args.id}/star",
		method="POST",
		token=token,
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


# ── CLI parser ───────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description="Local Email Skill — Mail server API client"
	)
	parser.add_argument(
		"--env",
		metavar="PATH",
		default=None,
		help="Path to .env file (default: auto-detect)",
	)
	sub = parser.add_subparsers(dest="command", required=True)

	p = sub.add_parser("list", help="List mailbox contents")
	p.add_argument("--limit", type=int, default=20)
	p.add_argument("--folder", default=None, help="Filter by folder name (e.g. Inbox, Sent)")
	p.set_defaults(func=cmd_list)

	p = sub.add_parser("read", help="Read a specific email by ID")
	p.add_argument("--id", required=True, type=int, help="Email ID")
	p.set_defaults(func=cmd_read)

	p = sub.add_parser("search", help="Search mailbox")
	p.add_argument("--query", required=True, help="Search query")
	p.set_defaults(func=cmd_search)

	p = sub.add_parser("send", help="Send an email")
	p.add_argument("--to", metavar="ADDR", default=None, help="Recipient (default: EMAIL_TO from env)")
	p.add_argument("--subject", required=True, help="Subject line")
	p.add_argument("--body", required=True, help="Email body")
	p.set_defaults(func=cmd_send)

	p = sub.add_parser("status", help="Check delivery status of a sent email")
	p.add_argument("--id", required=True, type=int, help="Email ID")
	p.set_defaults(func=cmd_status)

	p = sub.add_parser("move", help="Move an email to a different folder")
	p.add_argument("--id", required=True, type=int, help="Email ID")
	p.add_argument("--folder-id", required=True, type=int, help="Target folder ID")
	p.set_defaults(func=cmd_move)

	p = sub.add_parser("folders", help="List all folders")
	p.set_defaults(func=cmd_folders)

	p = sub.add_parser("delete", help="Delete an email")
	p.add_argument("--id", required=True, type=int, help="Email ID")
	p.set_defaults(func=cmd_delete)

	p = sub.add_parser("mark-read", help="Mark email as read")
	p.add_argument("--id", required=True, type=int, help="Email ID")
	p.set_defaults(func=cmd_read_mark)

	p = sub.add_parser("star", help="Toggle starred status")
	p.add_argument("--id", required=True, type=int, help="Email ID")
	p.set_defaults(func=cmd_star)

	p = sub.add_parser("login", help="Test mailbox authentication")
	p.set_defaults(func=cmd_login)

	return parser


# ── Entrypoint ───────────────────────────────────────────────────────────────

def main() -> None:
	parser = build_parser()
	args = parser.parse_args()

	env_path = Path(args.env) if args.env else find_env_file()
	if env_path:
		print(f"Loading config from: {env_path}", file=sys.stderr)
	else:
		print("No .env file found — using shell environment variables.", file=sys.stderr)

	env = load_env(env_path) if env_path else os.environ.copy()
	args.func(args, env)


if __name__ == "__main__":
	main()