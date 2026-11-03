import os
from contextlib import contextmanager

import mysql.connector


def db_config():
    return {
        "host": os.environ.get("MYSQL_HOST", "localhost"),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", "Allen@mysql20"),
        "database": os.environ.get("MYSQL_DATABASE", "classroom"),
    }


def class_connection():
    cfg = db_config()
    try:
        return mysql.connector.connect(**cfg)
    except mysql.connector.Error as error:
        if error.errno == 1049:
            admin = mysql.connector.connect(
                host=cfg["host"],
                user=cfg["user"],
                password=cfg["password"],
            )
            cursor = admin.cursor()
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{cfg['database']}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cursor.close()
            admin.close()
            return mysql.connector.connect(**cfg)
        raise


@contextmanager
def db_cursor(dictionary=False):
    connection = class_connection()
    cursor = connection.cursor(dictionary=dictionary)
    try:
        yield connection, cursor
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()
