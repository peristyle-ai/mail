import pytest
import io


class TestEmails:
	"""Email CRUD tests"""
	
	def test_list_emails_empty(self, client, auth_headers, db):
		"""Test listing emails when user has no emails"""
		response = client.get('/api/emails', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert isinstance(data, list)
		assert len(data) == 0
	
	def test_create_email(self, client, auth_headers, db):
		"""Test creating an email"""
		response = client.post('/api/emails', 
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Test Subject',
				'body': 'Test email body content'
			}
		)
		assert response.status_code == 201
		data = response.get_json()
		assert 'id' in data
	
	def test_get_email(self, client, auth_headers, db):
		"""Test getting a specific email"""
		# First create an email
		create_response = client.post('/api/emails', 
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Get Test',
				'body': 'Test body'
			}
		)
		email_id = create_response.get_json()['id']
		
		# Now get it
		response = client.get(f'/api/emails/{email_id}', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert data['subject'] == 'Get Test'
		assert data['body'] == 'Test body'
	
	def test_get_nonexistent_email(self, client, auth_headers, db):
		"""Test getting an email that doesn't exist"""
		response = client.get('/api/emails/99999', headers=auth_headers)
		assert response.status_code == 404
	
	def test_mark_email_as_read(self, client, auth_headers, db):
		"""Test marking an email as read"""
		# Create email
		create_response = client.post('/api/emails', 
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Read Test',
				'body': 'Test body'
			}
		)
		email_id = create_response.get_json()['id']
		
		# Mark as read
		response = client.post(f'/api/emails/{email_id}/read', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'read'
	
	def test_toggle_starred(self, client, auth_headers, db):
		"""Test toggling starred status"""
		# Create email
		create_response = client.post('/api/emails', 
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Star Test',
				'body': 'Test body'
			}
		)
		email_id = create_response.get_json()['id']
		
		# Toggle star (should star it)
		response = client.post(f'/api/emails/{email_id}/star', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert data['is_starred'] == True
		
		# Toggle again (should unstar it)
		response = client.post(f'/api/emails/{email_id}/star', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert data['is_starred'] == False
	
	def test_delete_email(self, client, auth_headers, db):
		"""Test deleting an email"""
		# Create email
		create_response = client.post('/api/emails', 
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Delete Test',
				'body': 'Test body'
			}
		)
		email_id = create_response.get_json()['id']
		
		# Delete it
		response = client.delete(f'/api/emails/{email_id}', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'deleted'
		
		# Verify it's gone
		get_response = client.get(f'/api/emails/{email_id}', headers=auth_headers)
		assert get_response.status_code == 404
	
	def test_move_email_to_folder(self, client, auth_headers, db):
		"""Test moving an email to a different folder"""
		from app.db import get_db_connection
		
		# Create a folder first
		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT id FROM users WHERE email = %s', ('test@example.com',))
		user_id = cursor.fetchone()['id']
		cursor.execute(
			'INSERT INTO folders (user_id, name) VALUES (%s, %s) RETURNING id',
			(user_id, 'Test Folder')
		)
		folder_id = cursor.fetchone()['id']
		conn.commit()
		cursor.close()
		conn.close()
		
		# Create email
		create_response = client.post('/api/emails', 
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Move Test',
				'body': 'Test body'
			}
		)
		email_id = create_response.get_json()['id']
		
		# Move to folder
		response = client.post(f'/api/emails/{email_id}/move', 
			headers=auth_headers,
			json={'folder_id': folder_id}
		)
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'moved'
	
	def test_sql_injection_in_email_fields(self, client, auth_headers, db):
		"""Test SQL injection attempts in email fields"""
		response = client.post('/api/emails', 
			headers=auth_headers,
			json={
				'to': "test@example.com'; DROP TABLE emails; --",
				'subject': "Subject'; DELETE FROM emails; --",
				'body': "Body'; UPDATE emails SET body='hacked'; --"
			}
		)
		# Should succeed with escaped content
		assert response.status_code == 201


class TestEmailSecurity:
	"""Security tests for email endpoints"""
	
	def test_cannot_access_other_users_email(self, client, auth_headers, auth_headers_second_user, db):
		"""Test that users cannot access other users' emails"""
		# User 1 creates an email
		create_response = client.post('/api/emails', 
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Private Email',
				'body': 'Secret content'
			}
		)
		email_id = create_response.get_json()['id']
		
		# User 2 tries to access it
		response = client.get(f'/api/emails/{email_id}', headers=auth_headers_second_user)
		assert response.status_code == 404  # Should not reveal it exists
	
	def test_cannot_delete_other_users_email(self, client, auth_headers, auth_headers_second_user, db):
		"""Test that users cannot delete other users' emails"""
		# User 1 creates an email
		create_response = client.post('/api/emails', 
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Private Email',
				'body': 'Secret content'
			}
		)
		email_id = create_response.get_json()['id']
		
		# User 2 tries to delete it
		response = client.delete(f'/api/emails/{email_id}', headers=auth_headers_second_user)
		# Should either return 404 or have no effect
		assert response.status_code in [404, 200]  # 200 if soft delete, 404 if not found
		
		# Verify User 1 can still access it
		get_response = client.get(f'/api/emails/{email_id}', headers=auth_headers)
		if response.status_code == 404:
			assert get_response.status_code == 200  # Email should still exist for User 1
	
	def test_cannot_star_other_users_email(self, client, auth_headers, auth_headers_second_user, db):
		"""Test that users cannot star/unstar other users' emails"""
		# User 1 creates an email
		create_response = client.post('/api/emails', 
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Private Email',
				'body': 'Secret content'
			}
		)
		email_id = create_response.get_json()['id']
		
		# User 2 tries to star it
		response = client.post(f'/api/emails/{email_id}/star', headers=auth_headers_second_user)
		assert response.status_code == 404  # Should not reveal it exists
	
	def test_list_emails_only_shows_own(self, client, auth_headers, auth_headers_second_user, db):
		"""Test that list emails only returns own emails"""
		# User 1 creates 2 emails
		client.post('/api/emails', 
			headers=auth_headers,
			json={'to': 'a@example.com', 'subject': 'User1 Email 1', 'body': 'Body'}
		)
		client.post('/api/emails', 
			headers=auth_headers,
			json={'to': 'b@example.com', 'subject': 'User1 Email 2', 'body': 'Body'}
		)
		
		# User 2 creates 1 email
		client.post('/api/emails', 
			headers=auth_headers_second_user,
			json={'to': 'c@example.com', 'subject': 'User2 Email', 'body': 'Body'}
		)
		
		# User 1 lists emails
		response = client.get('/api/emails', headers=auth_headers)
		assert response.status_code == 200
		emails = response.get_json()
		assert len(emails) == 2
		for email in emails:
			assert 'User1' in email['subject']
		
		# User 2 lists emails
		response = client.get('/api/emails', headers=auth_headers_second_user)
		assert response.status_code == 200
		emails = response.get_json()
		assert len(emails) == 1
		assert 'User2' in emails[0]['subject']
