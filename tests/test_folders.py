import pytest


class TestFolders:
	"""Folder management tests"""
	
	def test_list_folders(self, client, auth_headers, db):
		"""Test listing folders"""
		response = client.get('/api/folders', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert isinstance(data, list)
	
	def test_create_folder(self, client, auth_headers, db):
		"""Test creating a folder"""
		response = client.post('/api/folders',
			headers=auth_headers,
			json={'name': 'My Folder'}
		)
		assert response.status_code == 201
		data = response.get_json()
		assert 'id' in data
		
		# Verify it appears in list
		response = client.get('/api/folders', headers=auth_headers)
		folders = response.get_json()
		folder_names = [f['name'] for f in folders]
		assert 'My Folder' in folder_names
	
	def test_create_folder_with_parent(self, client, auth_headers, db):
		"""Test creating a nested folder"""
		from app.db import get_db_connection
		
		# First create parent folder
		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT id FROM users WHERE email = %s', ('test@example.com',))
		user_id = cursor.fetchone()['id']
		cursor.execute(
			'INSERT INTO folders (user_id, name) VALUES (%s, %s) RETURNING id',
			(user_id, 'Parent Folder')
		)
		parent_id = cursor.fetchone()['id']
		conn.commit()
		cursor.close()
		conn.close()
		
		# Create child folder
		response = client.post('/api/folders',
			headers=auth_headers,
			json={'name': 'Child Folder', 'parent_id': parent_id}
		)
		assert response.status_code == 201
		data = response.get_json()
		assert 'id' in data


class TestFolderSecurity:
	"""Security tests for folder endpoints"""
	
	def test_cannot_access_other_users_folders(self, client, auth_headers, auth_headers_second_user, db):
		"""Test that users cannot see other users' folders"""
		# User 1 creates a folder
		client.post('/api/folders',
			headers=auth_headers,
			json={'name': 'Private Folder'}
		)
		
		# User 2 lists folders
		response = client.get('/api/folders', headers=auth_headers_second_user)
		folders = response.get_json()
		folder_names = [f['name'] for f in folders]
		assert 'Private Folder' not in folder_names
	
	def test_cannot_create_folder_for_other_user(self, client, auth_headers, auth_headers_second_user, db):
		"""Test that folder creation is scoped to authenticated user only"""
		from app.db import get_db_connection
		
		# Get User 2's ID
		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT id FROM users WHERE email = %s', ('test2@example.com',))
		user2_id = cursor.fetchone()['id']
		cursor.close()
		conn.close()
		
		# User 1 creates a folder (should be for User 1, not User 2)
		response = client.post('/api/folders',
			headers=auth_headers,
			json={'name': 'User1 Folder'}
		)
		assert response.status_code == 201
		
		# Verify User 2 doesn't see it
		response = client.get('/api/folders', headers=auth_headers_second_user)
		folders = response.get_json()
		folder_names = [f['name'] for f in folders]
		assert 'User1 Folder' not in folder_names
