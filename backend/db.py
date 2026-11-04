
import os
from contextlib import contextmanager

import mysql.connector


def db_config():
    cfg = {
        "host": os.environ.get("MYSQL_HOST", "localhost"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
        "database": os.environ.get("MYSQL_DATABASE", "classroom"),
    }

    ssl_ca = os.environ.get("MYSQL_SSL_CA")

    if ssl_ca:
        cfg.update({
            "ssl_ca": ssl_ca,
            "ssl_verify_cert": True,
            "ssl_verify_identity": True,
        })

    return cfg


def class_connection():
    cfg = db_config()

    try:
        return mysql.connector.connect(**cfg)

    except mysql.connector.Error as error:
        if error.errno == 1049:
            admin_cfg = {
                "host": cfg["host"],
                "port": cfg["port"],
                "user": cfg["user"],
                "password": cfg["password"],
            }

            if "ssl_ca" in cfg:
                admin_cfg.update({
                    "ssl_ca": cfg["ssl_ca"],
                    "ssl_verify_cert": True,
                    "ssl_verify_identity": True,
                })

            admin = mysql.connector.connect(**admin_cfg)
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
