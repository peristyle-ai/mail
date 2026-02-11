import pytest
import uuid


class TestEndToEndWorkflow:
	"""End-to-end integration tests"""
	
	def test_complete_user_workflow(self, client, db):
		"""Test complete workflow: register -> login -> create email -> search -> delete"""
		
		# Generate unique email to avoid conflicts
		unique_email = f'workflow_{uuid.uuid4().hex[:8]}@example.com'
		
		# Step 1: Register
		register_response = client.post('/auth/register', json={
			'email': unique_email,
			'password': 'workflowpass123',
			'name': 'Workflow User'
		})
		assert register_response.status_code == 201
		user_id = register_response.get_json()['id']
		
		# Step 2: Login
		login_response = client.post('/auth/login', json={
			'email': unique_email,
			'password': 'workflowpass123'
		})
		assert login_response.status_code == 200
		login_data = login_response.get_json()
		assert 'token' in login_data
		token = login_data['token']
		headers = {'Authorization': f'Bearer {token}'}
		
		# Step 3: Create folder
		folder_response = client.post('/api/folders',
			headers=headers,
			json={'name': 'Work'}
		)
		assert folder_response.status_code == 201
		folder_id = folder_response.get_json()['id']
		
		# Step 4: Create multiple emails
		emails = []
		for i in range(3):
			email_response = client.post('/api/emails',
				headers=headers,
				json={
					'to': f'recipient{i}@example.com',
					'subject': f'Work Project {i}',
					'body': f'This is email {i} about the project',
					'folder_id': folder_id
				}
			)
			assert email_response.status_code == 201
			emails.append(email_response.get_json()['id'])
		
		# Step 5: Mark one as read
		read_response = client.post(f'/api/emails/{emails[0]}/read', headers=headers)
		assert read_response.status_code == 200
		
		# Step 6: Star another
		star_response = client.post(f'/api/emails/{emails[1]}/star', headers=headers)
		assert star_response.status_code == 200
		assert star_response.get_json()['is_starred'] == True
		
		# Step 7: Search for emails
		search_response = client.get('/api/search?q=project', headers=headers)
		assert search_response.status_code == 200
		search_data = search_response.get_json()
		assert len(search_data['emails']) == 3
		assert search_data['total'] == 3
		
		# Step 8: Search with filter (read only)
		search_read_response = client.get('/api/search?q=project&flag=read', headers=headers)
		assert search_read_response.status_code == 200
		read_emails = search_read_response.get_json()['emails']
		assert len(read_emails) == 1
		
		# Step 9: List all emails
		list_response = client.get('/api/emails', headers=headers)
		assert list_response.status_code == 200
		all_emails = list_response.get_json()
		assert len(all_emails) == 3
		
		# Step 10: Delete all emails
		for email_id in emails:
			delete_response = client.delete(f'/api/emails/{email_id}', headers=headers)
			assert delete_response.status_code == 200
		
		# Step 11: Verify deletion
		final_list = client.get('/api/emails', headers=headers)
		assert len(final_list.get_json()) == 0
	
	def test_attachment_workflow(self, client, db):
		"""Test complete attachment workflow"""
		import io
		
		# Generate unique email to avoid conflicts
		unique_email = f'attach_{uuid.uuid4().hex[:8]}@example.com'
		
		# Register and login
		client.post('/auth/register', json={
			'email': unique_email,
			'password': 'attachpass',
			'name': 'Attachment User'
		})
		login_response = client.post('/auth/login', json={
			'email': unique_email,
			'password': 'attachpass'
		})
		token = login_response.get_json()['token']
		headers = {'Authorization': f'Bearer {token}'}
		
		# Create email
		email_response = client.post('/api/emails',
			headers=headers,
			json={'to': 'test@example.com', 'subject': 'With Attachment', 'body': 'See attached'}
		)
		email_id = email_response.get_json()['id']
		
		# Upload attachment
		data = {'file': (io.BytesIO(b'file content here'), 'document.txt')}
		upload_response = client.post(f'/api/emails/{email_id}/attachments',
			headers=headers,
			data=data,
			content_type='multipart/form-data'
		)
		assert upload_response.status_code == 201
		attachment_id = upload_response.get_json()['id']
		
		# List attachments
		list_response = client.get(f'/api/emails/{email_id}/attachments', headers=headers)
		assert list_response.status_code == 200
		attachments = list_response.get_json()
		assert len(attachments) == 1
		
		# Delete attachment
		delete_response = client.delete(f'/api/attachments/{attachment_id}', headers=headers)
		assert delete_response.status_code == 200
		
		# Verify deletion
		list_response2 = client.get(f'/api/emails/{email_id}/attachments', headers=headers)
		assert len(list_response2.get_json()) == 0
	
	def test_cross_user_data_isolation(self, client, db):
		"""Test that users cannot access each other's data"""
		
		# Generate unique emails to avoid conflicts
		user1_email = f'user1_{uuid.uuid4().hex[:8]}@example.com'
		user2_email = f'user2_{uuid.uuid4().hex[:8]}@example.com'
		
		# Create User 1
		client.post('/auth/register', json={
			'email': user1_email,
			'password': 'pass1',
			'name': 'User One'
		})
		login1 = client.post('/auth/login', json={
			'email': user1_email,
			'password': 'pass1'
		})
		token1 = login1.get_json()['token']
		headers1 = {'Authorization': f'Bearer {token1}'}
		
		# Create User 2
		client.post('/auth/register', json={
			'email': user2_email,
			'password': 'pass2',
			'name': 'User Two'
		})
		login2 = client.post('/auth/login', json={
			'email': user2_email,
			'password': 'pass2'
		})
		token2 = login2.get_json()['token']
		headers2 = {'Authorization': f'Bearer {token2}'}
		
		# User 1 creates folder and email
		folder1 = client.post('/api/folders', headers=headers1, json={'name': 'Private'})
		folder1_id = folder1.get_json()['id']
		
		email1 = client.post('/api/emails', headers=headers1, json={
			'to': 'recipient@example.com',
			'subject': 'User1 Secret',
			'body': 'Confidential',
			'folder_id': folder1_id
		})
		email1_id = email1.get_json()['id']
		
		# User 2 creates folder and email
		folder2 = client.post('/api/folders', headers=headers2, json={'name': 'Personal'})
		folder2_id = folder2.get_json()['id']
		
		email2 = client.post('/api/emails', headers=headers2, json={
			'to': 'recipient@example.com',
			'subject': 'User2 Secret',
			'body': 'Private stuff',
			'folder_id': folder2_id
		})
		email2_id = email2.get_json()['id']
		
		# User 1 tries to access User 2's data
		assert client.get(f'/api/emails/{email2_id}', headers=headers1).status_code == 404
		assert client.get('/api/folders', headers=headers1).get_json()[0]['name'] == 'Private'
		
		# User 2 tries to access User 1's data
		assert client.get(f'/api/emails/{email1_id}', headers=headers2).status_code == 404
		assert client.get('/api/folders', headers=headers2).get_json()[0]['name'] == 'Personal'
		
		# Search isolation
		search1 = client.get('/api/search?q=secret', headers=headers1).get_json()
		assert len(search1['emails']) == 1
		assert 'User1' in search1['emails'][0]['subject']
		
		search2 = client.get('/api/search?q=secret', headers=headers2).get_json()
		assert len(search2['emails']) == 1
		assert 'User2' in search2['emails'][0]['subject']
