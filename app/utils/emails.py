from flask import request, jsonify
from app.db import get_db_connection

def get_email_recipients(email_id, recipient_type=None):
	conn = get_db_connection()
	cursor = conn.cursor()
	if recipient_type:
		cursor.execute('SELECT * FROM email_recipients WHERE email_id = %s AND recipient_type = %s', (email_id, recipient_type))
	else:
		cursor.execute('SELECT * FROM email_recipients WHERE email_id = %s', (email_id,))
	recipients = cursor.fetchall()
	cursor.close()
	conn.close()
	return recipients

def add_email_recipients(email_id, user_ids, recipient_type):
	conn = get_db_connection()
	cursor = conn.cursor()
	for user_id in user_ids:
		cursor.execute('INSERT INTO email_recipients (email_id, user_id, recipient_type) VALUES (%s, %s, %s)', (email_id, user_id, recipient_type))
	conn.commit()
	cursor.close()
	conn.close()
