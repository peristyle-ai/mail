import pytest


class TestSearch:
	"""Search functionality tests"""
	
	def test_search_basic(self, client, auth_headers, db):
		"""Test basic search functionality"""
		# Create some emails
		client.post('/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Important Meeting Tomorrow',
				'body': 'We need to discuss the project'
			}
		)
		client.post('/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Lunch Plans',
				'body': 'Meeting for lunch today'
			}
		)
		
		# Search for "meeting"
		response = client.get('/api/search?q=meeting', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert 'emails' in data
		assert len(data['emails']) == 2
		assert data['total'] == 2
	
	def test_search_no_results(self, client, auth_headers, db):
		"""Test search with no matching results"""
		response = client.get('/api/search?q=nonexistent', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert len(data['emails']) == 0
		assert data['total'] == 0
	
	def test_search_with_folder_filter(self, client, auth_headers, db):
		"""Test search with folder filter"""
		from app.db import get_db_connection
		
		# Create folder
		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT id FROM users WHERE email = %s', ('test@example.com',))
		user_id = cursor.fetchone()['id']
		cursor.execute(
			'INSERT INTO folders (user_id, name) VALUES (%s, %s) RETURNING id',
			(user_id, 'Work')
		)
		folder_id = cursor.fetchone()['id']
		conn.commit()
		cursor.close()
		conn.close()
		
		# Create email in folder
		client.post('/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Work Project',
				'body': 'About the project',
				'folder_id': folder_id
			}
		)
		
		# Create email without folder
		client.post('/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Personal Project',
				'body': 'About personal stuff'
			}
		)
		
		# Search in work folder only
		response = client.get(f'/api/search?q=project&folder_id={folder_id}', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert len(data['emails']) == 1
		assert data['emails'][0]['subject'] == 'Work Project'
	
	def test_search_with_read_flag(self, client, auth_headers, db):
		"""Test search with read/unread flag filter"""
		# Create and mark one as read
		response = client.post('/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Read Email',
				'body': 'This has been read'
			}
		)
		email_id = response.get_json()['id']
		client.post(f'/api/emails/{email_id}/read', headers=auth_headers)
		
		# Create unread email
		client.post('/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Unread Email',
				'body': 'This is unread'
			}
		)
		
		# Search for read emails
		response = client.get('/api/search?q=email&flag=read', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert len(data['emails']) == 1
		assert data['emails'][0]['subject'] == 'Read Email'
		
		# Search for unread emails
		response = client.get('/api/search?q=email&flag=unread', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert len(data['emails']) == 1
		assert data['emails'][0]['subject'] == 'Unread Email'
	
	def test_search_with_starred_flag(self, client, auth_headers, db):
		"""Test search with starred flag filter"""
		# Create and star one
		response = client.post('/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Starred Email',
				'body': 'This is important'
			}
		)
		email_id = response.get_json()['id']
		client.post(f'/api/emails/{email_id}/star', headers=auth_headers)
		
		# Create unstarred email
		client.post('/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'Normal Email',
				'body': 'This is normal'
			}
		)
		
		# Search for starred emails
		response = client.get('/api/search?q=email&flag=starred', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert len(data['emails']) == 1
		assert data['emails'][0]['subject'] == 'Starred Email'
	
	def test_search_pagination(self, client, auth_headers, db):
		"""Test search pagination"""
		# Create 5 emails
		for i in range(5):
			client.post('/api/emails',
				headers=auth_headers,
				json={
					'to': 'recipient@example.com',
					'subject': f'Email {i}',
					'body': 'Test body'
				}
			)
		
		# Get page 1 with limit 2
		response = client.get('/api/search?q=email&page=1&limit=2', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert len(data['emails']) == 2
		assert data['page'] == 1
		assert data['limit'] == 2
		assert data['total'] == 5
		
		# Get page 2 with limit 2
		response = client.get('/api/search?q=email&page=2&limit=2', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert len(data['emails']) == 2
		assert data['page'] == 2
	
	def test_search_isolation(self, client, auth_headers, auth_headers_second_user, db):
		"""Test search only returns current user's emails"""
		# User 1 creates email
		client.post('/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'User1 Secret',
				'body': 'Secret content'
			}
		)
		
		# User 2 creates email
		client.post('/api/emails',
			headers=auth_headers_second_user,
			json={
				'to': 'recipient@example.com',
				'subject': 'User2 Secret',
				'body': 'Secret content'
			}
		)
		
		# User 1 searches for "secret"
		response = client.get('/api/search?q=secret', headers=auth_headers)
		data = response.get_json()
		assert len(data['emails']) == 1
		assert 'User1' in data['emails'][0]['subject']
		
		# User 2 searches for "secret"
		response = client.get('/api/search?q=secret', headers=auth_headers_second_user)
		data = response.get_json()
		assert len(data['emails']) == 1
		assert 'User2' in data['emails'][0]['subject']
	
	def test_search_sql_injection(self, client, auth_headers, db):
		"""Test SQL injection in search query"""
		response = client.get('/api/search?q=test\'; DROP TABLE emails; --', headers=auth_headers)
		# Should succeed without executing injection
		assert response.status_code == 200
		data = response.get_json()
		assert 'emails' in data
