from flask import Blueprint, request, jsonify
from ..db import get_db_connection
from app.utils.auth import token_required
from app.services.search_service import search as do_search, SearchResult

bp = Blueprint('search', __name__)


def format_email_response(email_dict):
	"""Format email dict for API response, mapping body_html to html."""
	result = dict(email_dict)
	if 'body_html' in result:
		result['html'] = result.pop('body_html')
	return result


def _hydrate_emails(email_ids):
	"""Fetch full email rows for the given IDs, preserving input order."""
	if not email_ids:
		return [], {}
	conn = get_db_connection()
	cursor = conn.cursor()
	# Use ANY(%s) for the IN clause.
	cursor.execute(
		'''SELECT e.*, f.name AS folder_name, f.user_id AS folder_user_id
		   FROM emails e
		   LEFT JOIN folders f ON f.id = e.folder_id
		   WHERE e.id = ANY(%s)''',
		(email_ids,),
	)
	rows = cursor.fetchall()
	cursor.close()
	conn.close()
	by_id = {r['id']: r for r in rows}
	ordered = [by_id[i] for i in email_ids if i in by_id]
	return ordered, by_id


@bp.route('/api/search', methods=['GET'])
@token_required
def search_emails():
	"""
	Search emails with filters and hybrid semantic + keyword ranking.
	---
	tags:
	  - Search
	security:
	  - Bearer: []
	parameters:
	  - in: query
	    name: q
	    type: string
	    description: Free-text query.
	  - in: query
	    name: mode
	    type: string
	    enum: [hybrid, subject, chunks, keyword]
	    default: hybrid
	    description: |
	      Search mode. hybrid (default) combines subject + chunk cosine
	      similarity with trigram keyword match. subject uses only
	      subject_embedding (fast, always works). chunks uses only
	      email_chunks (only finds emails with body chunks — default
	      Processed/Sent). keyword does plain ILIKE on subject + body
	      (no embedding call — fastest, no semantic signal).
	  - in: query
	    name: folder_id
	    type: integer
	    description: Filter by folder ID
	  - in: query
	    name: flag
	    type: string
	    enum: [read, unread, starred]
	    description: Filter by email flag
	  - in: query
	    name: page
	    type: integer
	    default: 1
	    description: Page number for pagination
	  - in: query
	    name: limit
	    type: integer
	    default: 20
	    description: Number of results per page
	responses:
	  200:
	    description: Search results
	    schema:
	      type: object
	      properties:
	        emails:
	          type: array
	          items:
	            type: object
	        snippets:
	          type: object
	          description: |
	            Map of email_id -> matching chunk snippet (only set when the
	            result came from the chunks index; null for subject-only
	            matches).
	        scores:
	          type: object
	          description: Map of email_id -> combined relevance score.
	        total:
	          type: integer
	          description: |
	            Number of distinct emails in this page (capped by limit;
	            for full counts, switch to mode=keyword which counts).
	        mode:
	          type: string
	          description: Effective mode used (may be 'keyword' if the
	            embedding server was unreachable).
	        page:
	          type: integer
	        limit:
	          type: integer
	  401:
	    description: Unauthorized
	"""
	q = request.args.get('q', '')
	mode = request.args.get('mode', 'hybrid')
	if mode not in ('hybrid', 'subject', 'chunks', 'keyword'):
		return jsonify({'error': 'mode must be one of hybrid|subject|chunks|keyword'}), 400
	folder_id = request.args.get('folder_id', type=int)
	flag = request.args.get('flag')
	page = request.args.get('page', 1, type=int)
	limit = request.args.get('limit', 20, type=int)

	user_id = request.current_user['id']

	if not q.strip():
		# Empty query — return the user's recent emails (no ranking).
		# Preserves the legacy `GET /api/search` no-q behavior.
		conn = get_db_connection()
		cursor = conn.cursor()
		params = [user_id]
		sql = '''SELECT e.id, e.subject, e.body, e.body_html, e.headers,
		               e.created_at, e.is_read, e.is_starred, e.folder_id,
		               e.sender_id, e.recipient_id, e.source_email_id,
		               e.message_id, e.in_reply_to, e.references_chain,
		               e.thread_id, e.subject_normalized
		          FROM emails e
		          JOIN folders f ON e.folder_id = f.id
		          WHERE f.user_id = %s'''
		if folder_id:
			sql += ' AND e.folder_id = %s'
			params.append(folder_id)
		if flag == 'read':
			sql += ' AND e.is_read = TRUE'
		elif flag == 'unread':
			sql += ' AND e.is_read = FALSE'
		elif flag == 'starred':
			sql += ' AND e.is_starred = TRUE'
		sql += ' ORDER BY e.created_at DESC LIMIT %s OFFSET %s'
		params.extend([limit, (page - 1) * limit])
		cursor.execute(sql, params)
		emails = cursor.fetchall()
		cursor.execute('SELECT COUNT(*) AS n FROM emails e JOIN folders f ON e.folder_id = f.id WHERE f.user_id = %s', [user_id])
		total = cursor.fetchone()['n']
		cursor.close()
		conn.close()
		return jsonify({
			'emails': [format_email_response(dict(e)) for e in emails],
			'snippets': {},
			'scores': {},
			'total': total,
			'page': page,
			'limit': limit,
			'mode': 'list',
		})

	# Run the hybrid / subject / chunks / keyword search.
	result: SearchResult = do_search(
		user_id=user_id,
		query=q,
		mode=mode,
		folder_id=folder_id,
		flag=flag,
		page=page,
		limit=limit,
	)
	# Hydrate the email rows for the hits (in score order).
	emails_ordered, by_id = _hydrate_emails([h.email_id for h in result.hits])
	emails_out = [format_email_response(dict(e)) for e in emails_ordered]
	# Attach snippets/scores keyed by email_id.
	snippets = {}
	scores = {}
	for h in result.hits:
		if h.snippet:
			snippets[h.email_id] = h.snippet
		scores[h.email_id] = round(h.score, 6)
	# `result.total` comes from the search service (mirrors the same
	# criteria the page actually matches — semantic + trigram + ILIKE
	# per mode). Falls back to None on count error; the route still
	# returns the page even if total is unknown.
	total = result.total if result.total is not None else len(emails_out)
	return jsonify({
		'emails': emails_out,
		'snippets': snippets,
		'scores': scores,
		'total': total,
		'page': page,
		'limit': limit,
		'mode': result.mode,
	})
