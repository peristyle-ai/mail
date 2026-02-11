import logging
import psycopg2

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def connect_to_database(user="postgres", database="mail_server", host="localhost"):

    password = '1234'

    conn = psycopg2.connect(database=database, 
		user=user,
		password=password, 
		host=host, 
		port="5432")

    return conn
    
def qwen3_postgres_fetch(sql, params=None):
    """
    Fetch data from PostgreSQL database with support for parameterized queries.
    
    Args:
        sql (str): SQL query string
        params (dict, optional): Parameters to substitute in the SQL query
        
    Returns:
        list: List of rows fetched from the database
    """
    conn = None
    rows = []

    try:
        conn = connect_to_database()
        cur = conn.cursor()
        
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
            
        rows = cur.fetchall()
        conn.commit()
 
        cur.close()
    except (psycopg2.DatabaseError) as error:
        logging.error(f' error: {error}, full SQL: {sql}, params: {params}')
    finally:
        if conn is not None:
            conn.close()

    return rows
