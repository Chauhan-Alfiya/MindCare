SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";

-- mindcare -- 
-- ROLES TABLE
CREATE TABLE roles (
    role_id INT AUTO_INCREMENT PRIMARY KEY,
    role VARCHAR(50) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT INTO roles(role)
VALUES
('ADMIN'),
('STUDENT'),
('COUNSELLOR');

-- USERS TABLE
CREATE TABLE users (

    user_id INT AUTO_INCREMENT,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role_id INT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_deleted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity_date DATETIME DEFAULT NULL,
    last_password_change DATETIME DEFAULT NULL,
    deleted_at DATETIME DEFAULT NULL,
    reset_token VARCHAR(255) DEFAULT NULL,
    reset_expires DATETIME DEFAULT NULL,
    otp_code VARCHAR(10) DEFAULT NULL,
    otp_expires DATETIME DEFAULT NULL,
    PRIMARY KEY(user_id),
    
    FOREIGN KEY(role_id)
    REFERENCES roles(role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO users
(username,email,password,role_id)
VALUES
(
'Admin',
'admin@mindcare.com',
'scrypt:32768:8:1$jRN6qi5FiG2A8tTV$8b810b28bafa0447ad890ad4b894d762a83d4abe2d7b38198c0857b9ce3617f321c3b0101d281a621a263806d1ab6f474e784b88d2cd64e42caeb3f98f43eade',
(SELECT role_id FROM roles WHERE role='ADMIN')
);

-- STUDENT DETAILS
CREATE TABLE student_details(
    user_id INT,
    class ENUM('11th','12th') NOT NULL,
    stream ENUM(
        'Science',
        'Commerce',
        'Arts'
    ) NOT NULL,
    PRIMARY KEY(user_id),
    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ASSESSMENTS
CREATE TABLE assessments(
    assessment_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    assessment_type ENUM(
        'PHQ-9',
        'GAD-7',
        'MindCare Quick Assessment'
    ) NOT NULL,
    score INT NOT NULL,
    risk_level VARCHAR(50),
    recommendation TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id)
    REFERENCES users(user_id)
    ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE counsellor_details(
    user_id INT,
    qualification VARCHAR(100) NOT NULL,
    specialization VARCHAR(100) NOT NULL,
    experience INT DEFAULT 0,
    PRIMARY KEY(user_id),
    FOREIGN KEY(user_id)
    REFERENCES users(user_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- CHAT SUPPORT

CREATE TABLE chat_support(
    chat_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    message TEXT NOT NULL,
    bot_reply TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id)
    REFERENCES users(user_id)
    ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE appointments(
    appointment_id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,
    counsellor_id INT NOT NULL,

    appointment_date DATE NOT NULL,
    appointment_time TIME NOT NULL,

    reason TEXT,

    student_message TEXT,
    counsellor_message TEXT,

    meeting_link VARCHAR(255),

    status ENUM(
        'Pending',
        'Approved',
        'Completed',
        'Cancelled'
    ) DEFAULT 'Pending',

    completed_at DATETIME DEFAULT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(user_id)
    REFERENCES users(user_id)
    ON DELETE CASCADE,

    FOREIGN KEY(counsellor_id)
    REFERENCES users(user_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- WELLNESS RESOURCES

CREATE TABLE wellness_resources(
    resource_id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    category VARCHAR(100),
    description TEXT,
    language VARCHAR(50),
    file_path VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- WELLNESS TRACKER

CREATE TABLE wellness_tracker(
    tracker_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    mood ENUM(
        'Happy',
        'Calm',
        'Sad',
        'Stressed',
        'Anxious'
    ),
    stress_level INT,
    sleep_hours DECIMAL(3,1),
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id)
    REFERENCES users(user_id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- COUNSELLOR CHAT
CREATE TABLE counsellor_chat (
    chat_id INT AUTO_INCREMENT PRIMARY KEY,

    student_id INT NOT NULL,
    counsellor_id INT NOT NULL,

    sender_role ENUM('STUDENT', 'COUNSELLOR') NOT NULL,

    message TEXT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (student_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    FOREIGN KEY (counsellor_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE counsellor_chat
ADD COLUMN chat_status ENUM('Active', 'Completed')
DEFAULT 'Active';

COMMIT;