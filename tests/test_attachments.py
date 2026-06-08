import pytest
import io
import os


class TestAttachments:
	"""Attachment upload/download tests"""
	
	def test_upload_attachment(self, client, auth_headers, db):
		"""Test uploading an attachment to an email"""
		# First create an email
		email_response = client.post('/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Email with Attachment',
				'body': 'See attached'
			}
		)
		email_id = email_response.get_json()['id']
		
		# Upload attachment
		data = {
			'file': (io.BytesIO(b'test file content'), 'test.txt')
		}
		response = client.post(f'/api/emails/{email_id}/attachments',
			headers=auth_headers,
			data=data,
			content_type='multipart/form-data'
		)
		assert response.status_code == 201
		data = response.get_json()
		assert 'id' in data
		assert data['filename'] == 'test.txt'
	
	def test_list_attachments(self, client, auth_headers, db):
		"""Test listing attachments for an email"""
		# Create email
		email_response = client.post('/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Email with Attachments',
				'body': 'See attached'
			}
		)
		email_id = email_response.get_json()['id']
		
		# Upload attachment
		data = {'file': (io.BytesIO(b'content'), 'doc.txt')}
		client.post(f'/api/emails/{email_id}/attachments',
			headers=auth_headers,
			data=data,
			content_type='multipart/form-data'
		)
		
		# List attachments
		response = client.get(f'/api/emails/{email_id}/attachments', headers=auth_headers)
		assert response.status_code == 200
		attachments = response.get_json()
		assert len(attachments) == 1
		assert attachments[0]['filename'] == 'doc.txt'
	
	def test_upload_without_file(self, client, auth_headers, db):
		"""Test uploading without file returns error"""
		email_response = client.post('/api/emails',
			headers=auth_headers,
			json={'to': 'test@example.com', 'subject': 'Test', 'body': 'Body'}
		)
		email_id = email_response.get_json()['id']
		
		response = client.post(f'/api/emails/{email_id}/attachments',
			headers=auth_headers,
			data={},
			content_type='multipart/form-data'
		)
		assert response.status_code == 400
		assert 'error' in response.get_json()
	
	def test_upload_disallowed_file_type(self, client, auth_headers, db):
		"""Test uploading disallowed file type returns error"""
		email_response = client.post('/api/emails',
			headers=auth_headers,
			json={'to': 'test@example.com', 'subject': 'Test', 'body': 'Body'}
		)
		email_id = email_response.get_json()['id']
		
		data = {'file': (io.BytesIO(b'executable content'), 'virus.exe')}
		response = client.post(f'/api/emails/{email_id}/attachments',
			headers=auth_headers,
			data=data,
			content_type='multipart/form-data'
		)
		assert response.status_code == 400
		assert 'error' in response.get_json()
	
	def test_delete_attachment(self, client, auth_headers, db):
		"""Test deleting an attachment"""
		# Create email and attachment
		email_response = client.post('/api/emails',
			headers=auth_headers,
			json={'to': 'test@example.com', 'subject': 'Test', 'body': 'Body'}
		)
		email_id = email_response.get_json()['id']
		
		data = {'file': (io.BytesIO(b'content'), 'delete_me.txt')}
		attach_response = client.post(f'/api/emails/{email_id}/attachments',
			headers=auth_headers,
			data=data,
			content_type='multipart/form-data'
		)
		attachment_id = attach_response.get_json()['id']
		
		# Delete attachment
		response = client.delete(f'/api/attachments/{attachment_id}', headers=auth_headers)
		assert response.status_code == 200
		assert response.get_json()['status'] == 'deleted'
		
		# Verify it's gone
		list_response = client.get(f'/api/emails/{email_id}/attachments', headers=auth_headers)
		attachments = list_response.get_json()
		assert len(attachments) == 0

	def test_upload_attachment_mirrors_to_local_inbox_copy(self, client, auth_headers, auth_headers_second_user, db):
		"""Uploading to a sent email should mirror the attachment to linked local inbox copies."""
		email_response = client.post('/api/emails',
			headers=auth_headers,
			json={'to': 'test2@example.com', 'subject': 'Mirror Attachments', 'body': 'See attached'}
		)
		sent_email_id = email_response.get_json()['id']

		data = {'file': (io.BytesIO(b'mirror content'), 'mirror.txt')}
		response = client.post(
			f'/api/emails/{sent_email_id}/attachments',
			headers=auth_headers,
			data=data,
			content_type='multipart/form-data'
		)
		assert response.status_code == 201

		conn = db()
		cursor = conn.cursor()
		cursor.execute(
			'''SELECT e.id, e.source_email_id
			   FROM emails e
			   JOIN folders f ON e.folder_id = f.id
			   WHERE e.subject = %s
			     AND e.recipient_id = (SELECT id FROM users WHERE email = %s)
			     AND f.name = %s''',
			('Mirror Attachments', 'test2@example.com', 'Inbox')
		)
		inbox_email = cursor.fetchone()
		cursor.close()
		conn.close()

		assert inbox_email['source_email_id'] == sent_email_id

		list_response = client.get(f"/api/emails/{inbox_email['id']}/attachments", headers=auth_headers_second_user)
		assert list_response.status_code == 200
		attachments = list_response.get_json()
		assert len(attachments) == 1
		assert attachments[0]['filename'] == 'mirror.txt'

	def test_delete_sent_attachment_keeps_mirrored_local_copy_downloadable(self, client, auth_headers, auth_headers_second_user, db):
		"""Deleting one mirrored attachment must not remove the shared file for other copies."""
		email_response = client.post('/api/emails',
			headers=auth_headers,
			json={'to': 'test2@example.com', 'subject': 'Shared Attachment', 'body': 'See attached'}
		)
		sent_email_id = email_response.get_json()['id']

		data = {'file': (io.BytesIO(b'shared content'), 'shared.txt')}
		upload_response = client.post(
			f'/api/emails/{sent_email_id}/attachments',
			headers=auth_headers,
			data=data,
			content_type='multipart/form-data'
		)
		assert upload_response.status_code == 201
		sent_attachment_id = upload_response.get_json()['id']

		conn = db()
		cursor = conn.cursor()
		cursor.execute(
			'''SELECT e.id AS email_id, a.id AS attachment_id, a.file_path
			   FROM emails e
			   JOIN attachments a ON a.email_id = e.id
			   WHERE e.source_email_id = %s''',
			(sent_email_id,)
		)
		mirrored = cursor.fetchone()
		cursor.close()
		conn.close()

		assert mirrored is not None
		assert os.path.exists(mirrored['file_path'])

		delete_response = client.delete(f"/api/attachments/{sent_attachment_id}", headers=auth_headers)
		assert delete_response.status_code == 200
		assert os.path.exists(mirrored['file_path'])

		download_response = client.get(f"/api/attachments/{mirrored['attachment_id']}", headers=auth_headers_second_user)
		assert download_response.status_code == 200
		assert download_response.data == b'shared content'


class TestAttachmentSecurity:
	"""Security tests for attachments"""
	
	def test_cannot_access_other_users_attachments(self, client, auth_headers, auth_headers_second_user, db):
		"""Test users cannot download other users' attachments"""
		# User 1 creates email and attachment
		email_response = client.post('/api/emails',
			headers=auth_headers,
			json={'to': 'test@example.com', 'subject': 'Secret', 'body': 'Body'}
		)
		email_id = email_response.get_json()['id']
		
		data = {'file': (io.BytesIO(b'secret content'), 'secret.txt')}
		attach_response = client.post(f'/api/emails/{email_id}/attachments',
			headers=auth_headers,
			data=data,
			content_type='multipart/form-data'
		)
		attachment_id = attach_response.get_json()['id']
		
		# User 2 tries to access it
		response = client.get(f'/api/attachments/{attachment_id}', headers=auth_headers_second_user)
		assert response.status_code == 404
	
	def test_cannot_delete_other_users_attachments(self, client, auth_headers, auth_headers_second_user, db):
		"""Test users cannot delete other users' attachments"""
		# User 1 creates email and attachment
		email_response = client.post('/api/emails',
			headers=auth_headers,
			json={'to': 'test@example.com', 'subject': 'Secret', 'body': 'Body'}
		)
		email_id = email_response.get_json()['id']
		
		data = {'file': (io.BytesIO(b'secret content'), 'secret.txt')}
		attach_response = client.post(f'/api/emails/{email_id}/attachments',
			headers=auth_headers,
			data=data,
			content_type='multipart/form-data'
		)
		attachment_id = attach_response.get_json()['id']
		
		# User 2 tries to delete it
		response = client.delete(f'/api/attachments/{attachment_id}', headers=auth_headers_second_user)
		assert response.status_code == 404
		
		# Verify User 1 can still access it
		list_response = client.get(f'/api/emails/{email_id}/attachments', headers=auth_headers)
		attachments = list_response.get_json()
		assert len(attachments) == 1
	
	def test_cannot_upload_to_other_users_email(self, client, auth_headers, auth_headers_second_user, db):
		"""Test users cannot upload attachments to other users' emails"""
		# User 2 creates email
		email_response = client.post('/api/emails',
			headers=auth_headers_second_user,
			json={'to': 'test@example.com', 'subject': 'User2 Email', 'body': 'Body'}
		)
		email_id = email_response.get_json()['id']
		
		# User 1 tries to upload to User 2's email
		data = {'file': (io.BytesIO(b'malicious content'), 'hack.txt')}
		response = client.post(f'/api/emails/{email_id}/attachments',
			headers=auth_headers,
			data=data,
			content_type='multipart/form-data'
		)
		# Should fail or be unauthorized
		assert response.status_code in [403, 404, 401]
	
	def test_sql_injection_in_filename(self, client, auth_headers, db):
		"""Test SQL injection attempts in filename"""
		email_response = client.post('/api/emails',
			headers=auth_headers,
			json={'to': 'test@example.com', 'subject': 'Test', 'body': 'Body'}
		)
		email_id = email_response.get_json()['id']
		
		data = {'file': (io.BytesIO(b'content'), "test'; DROP TABLE attachments; --.txt")}
		response = client.post(f'/api/emails/{email_id}/attachments',
			headers=auth_headers,
			data=data,
			content_type='multipart/form-data'
		)
		# Should handle safely (either accept with escaped name or reject)
		assert response.status_code in [201, 400]
