from backend.db import class_connection


STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(255) NOT NULL UNIQUE,
        password VARCHAR(255) NOT NULL,
        role VARCHAR(50) NOT NULL,
        section VARCHAR(100) NULL,
        fullname VARCHAR(255) NULL,
        email VARCHAR(255) NULL,
        contact VARCHAR(80) NULL,
        photo_path VARCHAR(500) NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS subjects (
        id INT AUTO_INCREMENT PRIMARY KEY,
        subject_name VARCHAR(150) NOT NULL,
        section VARCHAR(100) DEFAULT 'All Sections',
        teacher_id INT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS student_enrollment_types (
        student_id INT PRIMARY KEY,
        enrollment_type VARCHAR(20) NOT NULL DEFAULT 'Regular'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS student_subject_assignments (
        student_id INT NOT NULL,
        subject_id INT NOT NULL,
        PRIMARY KEY (student_id, subject_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS announcements (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        description TEXT,
        attachment_path VARCHAR(500),
        section VARCHAR(100),
        subject VARCHAR(150),
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS modules (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        description TEXT,
        filename VARCHAR(255),
        filepath VARCHAR(500),
        module_type VARCHAR(20),
        url VARCHAR(500),
        section VARCHAR(100),
        subject VARCHAR(150),
        uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activities (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        description TEXT,
        due_date DATETIME,
        attachment_path VARCHAR(500),
        resource_url VARCHAR(500),
        section VARCHAR(100),
        subject VARCHAR(150)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS submissions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        activity_id INT NOT NULL,
        student_id INT NOT NULL,
        answer_text TEXT,
        file_path VARCHAR(500),
        submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_activity_student (activity_id, student_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS submission_history (
        id INT AUTO_INCREMENT PRIMARY KEY,
        submission_id INT,
        activity_id INT,
        student_id INT,
        answer_text TEXT,
        file_path VARCHAR(500)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance_sessions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(150) NOT NULL,
        section VARCHAR(100) DEFAULT 'All Sections',
        attendance_date DATE NOT NULL,
        deadline DATETIME NOT NULL,
        created_by INT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance_records (
        id INT AUTO_INCREMENT PRIMARY KEY,
        attendance_id INT NOT NULL,
        student_id INT NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'Present',
        marked_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_attendance_student (attendance_id, student_id)
    )
    """,
]

COLUMN_CHECKS = [
    ("users", "fullname", "VARCHAR(255) NULL"),
    ("users", "email", "VARCHAR(255) NULL"),
    ("users", "contact", "VARCHAR(80) NULL"),
    ("users", "photo_path", "VARCHAR(500) NULL"),
    ("users", "section", "VARCHAR(100) NULL"),
    ("modules", "description", "TEXT NULL"),
    ("modules", "subject", "VARCHAR(150) NULL"),
    ("modules", "url", "VARCHAR(500) NULL"),
    ("modules", "module_type", "VARCHAR(20) NULL"),
    ("modules", "section", "VARCHAR(100) NULL"),
    ("activities", "subject", "VARCHAR(150) NULL"),
    ("activities", "resource_url", "VARCHAR(500) NULL"),
    ("activities", "attachment_path", "VARCHAR(500) NULL"),
    ("activities", "section", "VARCHAR(100) NULL"),
    ("announcements", "subject", "VARCHAR(150) NULL"),
    ("announcements", "attachment_path", "VARCHAR(500) NULL"),
]


def ensure_schema():
    connection = class_connection()
    cursor = connection.cursor()
    try:
        for statement in STATEMENTS:
            cursor.execute(statement)
        for table, column, definition in COLUMN_CHECKS:
            cursor.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (column,))
            if not cursor.fetchone():
                cursor.execute(
                    f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}"
                )
        connection.commit()
    finally:
        cursor.close()
        connection.close()
