#!/usr/bin/env python3
"""Local Email Skill — Mail server API client.

Reads config from environment variables. Supports --env flag or auto-detects
from CLAWBIE_ENV, ~/git/clawbie/.env, project .env, or ~/.env.

Environment variables (required):
    EMAIL_SERVER   — base URL of the mail server (e.g. http://localhost:5003)
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


def normalize_to_addresses(values: list[str] | None, default: str) -> list[str]:
	"""Normalize repeated and comma-separated --to values."""
	items = values or ([] if not default else [default])
	result = []
	for item in items:
		for address in item.split(','):
			address = address.strip()
			if address:
				result.append(address)
	return result


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


def _build_mime_with_attachments(
	from_addr: str,
	to_addrs: list[str],
	subject: str,
	body: str,
	attachments: list[Path] | None,
	html: str | None = None,
) -> bytes:
	"""Build a multipart/mixed MIME message for the /api/emails/mime endpoint.

	The mail server's /api/emails/mime endpoint expects a complete RFC 822
	message (multipart/mixed, headers + body) delivered as the `mime_content`
	JSON field. The server does NOT base64-decode the field — it expects the
	raw message bytes encoded as a JSON string (use latin-1 round-trip to
	preserve all 0x00-0xFF bytes through JSON's UTF-8 envelope).
	"""
	from email.mime.multipart import MIMEMultipart
	from email.mime.text import MIMEText
	from email.mime.application import MIMEApplication

	msg = MIMEMultipart()
	msg["From"] = from_addr
	# Use comma-joined form for multiple recipients in the To header
	msg["To"] = ", ".join(to_addrs)
	msg["Subject"] = subject

	if html is not None:
		# multipart/alternative: text + html
		alt = MIMEMultipart("alternative")
		alt.attach(MIMEText(body, "plain", "utf-8"))
		alt.attach(MIMEText(html, "html", "utf-8"))
		msg.attach(alt)
	else:
		msg.attach(MIMEText(body, "plain", "utf-8"))

	for path in attachments or []:
		data = path.read_bytes()
		subtype = "octet-stream"
		if path.suffix.lower() == ".pdf":
			subtype = "pdf"
		elif path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif"):
			subtype = path.suffix.lower().lstrip(".")
		att = MIMEApplication(data, _subtype=subtype, Name=path.name)
		att.add_header("Content-Disposition", "attachment", filename=path.name)
		msg.attach(att)

	return msg.as_bytes()


def cmd_send(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	to_addresses = normalize_to_addresses(args.to, env.get("EMAIL_TO", ""))
	if not to_addresses:
		raise SystemExit("Error: --to is required when EMAIL_TO is not set")

	attachments = [Path(p) for p in (args.attachment or [])]
	missing = [str(p) for p in attachments if not p.exists()]
	if missing:
		raise SystemExit(f"Error: attachment file(s) not found: {', '.join(missing)}")

	# If attachments are present, route to /api/emails/mime (the only endpoint
	# that supports attachments). Otherwise use the simpler /api/emails endpoint.
	if attachments:
		from_addr = args.from_addr or env["EMAIL_ADDRESS"]
		raw_mime = _build_mime_with_attachments(
			from_addr=from_addr,
			to_addrs=to_addresses,
			subject=args.subject,
			body=args.body,
			attachments=attachments,
			html=args.html,
		)
		# Critical: encode the raw bytes as a JSON string. JSON is UTF-8, so
		# latin-1 round-trips 1:1 with bytes (every byte 0x00-0xFF maps to a
		# valid code point). Do NOT base64 — the server does not base64-decode.
		mime_str = raw_mime.decode("latin-1")
		to_payload = to_addresses[0] if len(to_addresses) == 1 else to_addresses
		payload = request_json(
			f"{env['EMAIL_SERVER'].rstrip('/')}/api/emails/mime",
			method="POST",
			token=token,
			payload={
				"to": to_payload,
				"from": from_addr,
				"subject": args.subject,
				"mime_content": mime_str,
			},
		)
	else:
		to_payload = to_addresses[0] if len(to_addresses) == 1 else to_addresses
		payload = request_json(
			f"{env['EMAIL_SERVER'].rstrip('/')}/api/emails",
			method="POST",
			token=token,
			payload={"to": to_payload, "subject": args.subject, "body": args.body},
		)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_send_mime(args: argparse.Namespace, env: dict[str, str]) -> None:
	"""Send a prebuilt MIME message from a file via /api/emails/mime.

	The file must be a complete RFC 822 message (headers + body). The server
	parses it directly — do NOT base64 encode. The Content-Type of the file
	does not matter; only the file contents are read.
	"""
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	mime_path = Path(args.mime_file)
	if not mime_path.exists():
		raise SystemExit(f"Error: MIME file not found: {mime_path}")
	raw = mime_path.read_bytes()
	# Subject and recipients are still required by the server even when
	# mime_content is provided (server uses them for envelope/sender metadata).
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/emails/mime",
		method="POST",
		token=token,
		payload={
			"to": [args.to] if isinstance(args.to, str) else args.to,
			"from": args.from_addr or env["EMAIL_ADDRESS"],
			"subject": args.subject,
			"mime_content": raw.decode("latin-1"),
		},
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


def cmd_domains(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/domains",
		token=token,
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_domain_get(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/domains/{args.domain}",
		token=token,
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_domain_set_relay(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = {
		"relay_provider": args.provider,
		"relay_host": args.host,
		"relay_port": args.port,
		"relay_username": args.username,
		"relay_password": args.password,
		"relay_from_address": args.from_address,
	}
	response = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/domains/{args.domain}/relay",
		method="PUT",
		token=token,
		payload=payload,
	)
	print(json.dumps(response, indent=2, ensure_ascii=False))


def cmd_domain_verify_relay(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/domains/{args.domain}/relay/verify",
		method="POST",
		token=token,
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_domain_delete_relay(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/domains/{args.domain}/relay",
		method="DELETE",
		token=token,
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_domain_set_webhook_secret(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/domains/{args.domain}/webhook-secret",
		method="PUT",
		token=token,
		payload={"webhook_secret": args.secret},
	)
	print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_domain_rotate_webhook_secret(args: argparse.Namespace, env: dict[str, str]) -> None:
	require_env_vars(env, "EMAIL_SERVER", "EMAIL_ADDRESS", "EMAIL_PASSWORD")
	token = login(env["EMAIL_SERVER"], env["EMAIL_ADDRESS"], env["EMAIL_PASSWORD"])
	payload = request_json(
		f"{env['EMAIL_SERVER'].rstrip('/')}/api/domains/{args.domain}/webhook-secret/rotate",
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

	p = sub.add_parser("send", help="Send an email (use --attachment to send a MIME message with files)")
	p.add_argument("--to", metavar="ADDR", action="append", default=None, help="Recipient; repeat or comma-separate for multiple")
	p.add_argument("--from-addr", metavar="ADDR", dest="from_addr", default=None, help="Sender address (defaults to EMAIL_ADDRESS). Required only when using --attachment.")
	p.add_argument("--subject", required=True, help="Subject line")
	p.add_argument("--body", required=True, help="Email body (plain text)")
	p.add_argument("--html", default=None, help="Optional HTML body; when provided the email is sent as multipart/alternative (text + html)")
	p.add_argument("--attachment", metavar="PATH", dest="attachment", action="append", default=None, help="Path to a file to attach; repeat for multiple. Forces MIME send via /api/emails/mime.")
	p.set_defaults(func=cmd_send)

	p = sub.add_parser("send-mime", help="Send a prebuilt RFC 822 MIME message from a file")
	p.add_argument("--to", metavar="ADDR", required=True, help="Recipient address")
	p.add_argument("--from-addr", metavar="ADDR", dest="from_addr", default=None, help="Sender address (defaults to EMAIL_ADDRESS)")
	p.add_argument("--subject", required=True, help="Subject line (used for envelope metadata; not added to the MIME body)")
	p.add_argument("--mime-file", required=True, metavar="PATH", help="Path to a complete RFC 822 / multipart MIME file")
	p.set_defaults(func=cmd_send_mime)

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

	p = sub.add_parser("domains", help="List configured domains")
	p.set_defaults(func=cmd_domains)

	p = sub.add_parser("domain-get", help="Get one domain configuration")
	p.add_argument("--domain", required=True, help="Domain name")
	p.set_defaults(func=cmd_domain_get)

	p = sub.add_parser("domain-set-relay", help="Set relay config for a domain")
	p.add_argument("--domain", required=True, help="Domain name")
	p.add_argument("--provider", required=True, help="Relay provider (smtp2go, sendgrid, smtp)")
	p.add_argument("--host", default=None, help="Relay host (default provider host if supported)")
	p.add_argument("--port", type=int, default=None, help="Relay port")
	p.add_argument("--username", required=True, help="Relay SMTP username")
	p.add_argument("--password", required=True, help="Relay SMTP password")
	p.add_argument("--from-address", default=None, help="Verified from address for this domain")
	p.set_defaults(func=cmd_domain_set_relay)

	p = sub.add_parser("domain-verify-relay", help="Verify relay config for a domain")
	p.add_argument("--domain", required=True, help="Domain name")
	p.set_defaults(func=cmd_domain_verify_relay)

	p = sub.add_parser("domain-delete-relay", help="Remove relay config from a domain")
	p.add_argument("--domain", required=True, help="Domain name")
	p.set_defaults(func=cmd_domain_delete_relay)

	p = sub.add_parser("domain-set-webhook-secret", help="Set webhook secret for a domain")
	p.add_argument("--domain", required=True, help="Domain name")
	p.add_argument("--secret", required=True, help="Plaintext webhook secret")
	p.set_defaults(func=cmd_domain_set_webhook_secret)

	p = sub.add_parser("domain-rotate-webhook-secret", help="Rotate webhook secret for a domain")
	p.add_argument("--domain", required=True, help="Domain name")
	p.set_defaults(func=cmd_domain_rotate_webhook_secret)

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
