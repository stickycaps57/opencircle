CREATE TABLE `address` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `country` varchar(255) NOT NULL,
  `province` varchar(255) NOT NULL,
  `city` varchar(255) NOT NULL,
  `barangay` varchar(255) NOT NULL,
  `house_building_number` varchar(255) NOT NULL,
  `country_code` varchar(100) NOT NULL,
  `province_code` varchar(100) NOT NULL,
  `city_code` varchar(100) NOT NULL,
  `barangay_code` varchar(100) NOT NULL,
  `created_date` datetime NOT NULL DEFAULT current_timestamp(),
  `last_modified_date` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

CREATE TABLE `resource` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `directory` varchar(300) NOT NULL,
  `filename` varchar(100) NOT NULL,
  `created_date` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

CREATE TABLE `role` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `created_date` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

CREATE TABLE `account` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `uuid` char(32) NOT NULL,
  `email` varchar(255) NOT NULL,
  `username` varchar(100) NOT NULL,
  `password` varchar(255) NOT NULL,
  `role_id` int(11) NOT NULL,
  `created_date` datetime NOT NULL DEFAULT current_timestamp(),
  `last_modified_date` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  `totp_secret` varchar(255) DEFAULT NULL COMMENT 'TOTP secret key for 2FA',
  `two_factor_enabled` tinyint(1) NOT NULL DEFAULT 0 COMMENT 'Whether 2FA is enabled for this account',
  `backup_codes` text DEFAULT NULL COMMENT 'JSON array of backup codes for 2FA recovery',
  `email_otp_code` varchar(10) DEFAULT NULL,
  `email_otp_expires` datetime DEFAULT NULL,
  `email_verified` tinyint(1) DEFAULT 0,
  `otp_attempts` int(11) DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `account_email_IDX` (`email`) USING BTREE,
  UNIQUE KEY `account_uuid_IDX` (`uuid`) USING BTREE,
  UNIQUE KEY `account_username` (`username`),
  KEY `role_id` (`role_id`),
  KEY `account_email_password_IDX` (`email`,`password`) USING BTREE,
  KEY `account_username_IDX` (`username`,`password`) USING BTREE,
  KEY `idx_account_email_otp` (`email`,`email_otp_code`,`email_otp_expires`),
  KEY `idx_account_email_verified` (`email_verified`),
  CONSTRAINT `account_ibfk_1` FOREIGN KEY (`role_id`) REFERENCES `role` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

CREATE TABLE `organization` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `account_id` bigint(20) NOT NULL,
  `name` varchar(255) NOT NULL,
  `logo` bigint(20) DEFAULT NULL,
  `category` varchar(100) DEFAULT NULL,
  `description` text DEFAULT NULL,
  `created_date` datetime NOT NULL DEFAULT current_timestamp(),
  `last_modified_date` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `organization_account_FK` (`account_id`),
  KEY `organization_resource_FK` (`logo`),
  CONSTRAINT `organization_account_FK` FOREIGN KEY (`account_id`) REFERENCES `account` (`id`) ON DELETE CASCADE,
  CONSTRAINT `organization_resource_FK` FOREIGN KEY (`logo`) REFERENCES `resource` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

CREATE TABLE `post` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `author` bigint(20) NOT NULL,
  `image` text DEFAULT NULL,
  `description` text NOT NULL,
  `created_date` datetime NOT NULL DEFAULT current_timestamp(),
  `last_modified_date` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `post_account_FK` (`author`),
  CONSTRAINT `post_account_FK` FOREIGN KEY (`author`) REFERENCES `account` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

CREATE TABLE `session` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `account_uuid` char(32) NOT NULL,
  `session_token` varchar(255) NOT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  `expires_at` datetime NOT NULL,
  `ip_address` varchar(45) DEFAULT NULL,
  `user_agent` varchar(512) DEFAULT NULL,
  `last_activity` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `session_token` (`session_token`),
  KEY `session_account_FK` (`account_uuid`),
  CONSTRAINT `session_account_FK` FOREIGN KEY (`account_uuid`) REFERENCES `account` (`uuid`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

CREATE TABLE `user` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `account_id` bigint(20) NOT NULL,
  `first_name` varchar(255) NOT NULL,
  `last_name` varchar(255) NOT NULL,
  `bio` text DEFAULT NULL,
  `profile_picture` bigint(20) DEFAULT NULL,
  `created_date` datetime NOT NULL DEFAULT current_timestamp(),
  `last_modified_date` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `user_resource_FK` (`profile_picture`),
  KEY `user_account_FK` (`account_id`),
  CONSTRAINT `user_account_FK` FOREIGN KEY (`account_id`) REFERENCES `account` (`id`) ON DELETE CASCADE,
  CONSTRAINT `user_resource_FK` FOREIGN KEY (`profile_picture`) REFERENCES `resource` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

CREATE TABLE `event` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `organization_id` bigint(20) NOT NULL,
  `title` varchar(255) NOT NULL,
  `event_date` datetime NOT NULL,
  `address_id` bigint(20) NOT NULL,
  `description` text NOT NULL,
  `image` bigint(20) DEFAULT NULL,
  `created_date` datetime NOT NULL DEFAULT current_timestamp(),
  `last_modified_date` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `event_organization_FK` (`organization_id`),
  KEY `event_resource_FK` (`image`),
  KEY `event_address_FK` (`address_id`),
  CONSTRAINT `event_address_FK` FOREIGN KEY (`address_id`) REFERENCES `address` (`id`),
  CONSTRAINT `event_organization_FK` FOREIGN KEY (`organization_id`) REFERENCES `organization` (`id`) ON DELETE CASCADE,
  CONSTRAINT `event_resource_FK` FOREIGN KEY (`image`) REFERENCES `resource` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

CREATE TABLE `membership` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `organization_id` bigint(20) NOT NULL,
  `user_id` bigint(20) NOT NULL,
  `status` enum('pending','approved','rejected','left') NOT NULL DEFAULT 'pending',
  `created_date` datetime NOT NULL DEFAULT current_timestamp(),
  `last_modified_date` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `membership_unique` (`organization_id`,`user_id`),
  KEY `membership_user_FK` (`user_id`),
  CONSTRAINT `membership_organization_FK` FOREIGN KEY (`organization_id`) REFERENCES `organization` (`id`) ON DELETE CASCADE,
  CONSTRAINT `membership_user_FK` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

CREATE TABLE `rsvp` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `event_id` bigint(20) NOT NULL,
  `attendee` bigint(20) NOT NULL,
  `status` enum('joined','rejected','pending') NOT NULL DEFAULT 'pending',
  `created_date` datetime DEFAULT current_timestamp(),
  `last_modified_date` datetime DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `rsvp_account_id_IDX` (`attendee`,`event_id`) USING BTREE,
  KEY `rsvp_event_FK` (`event_id`),
  CONSTRAINT `rsvp_account_FK` FOREIGN KEY (`attendee`) REFERENCES `account` (`id`) ON DELETE CASCADE,
  CONSTRAINT `rsvp_event_FK` FOREIGN KEY (`event_id`) REFERENCES `event` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

CREATE TABLE `comment` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `event_id` bigint(20) DEFAULT NULL,
  `post_id` bigint(20) DEFAULT NULL,
  `author` bigint(20) NOT NULL,
  `message` text NOT NULL,
  `created_date` datetime NOT NULL DEFAULT current_timestamp(),
  `last_modified_date` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `comments_account_FK` (`author`),
  KEY `comments_event_FK` (`event_id`),
  KEY `comments_post_FK` (`post_id`),
  CONSTRAINT `comments_account_FK` FOREIGN KEY (`author`) REFERENCES `account` (`id`) ON DELETE CASCADE,
  CONSTRAINT `comments_event_FK` FOREIGN KEY (`event_id`) REFERENCES `event` (`id`) ON DELETE CASCADE,
  CONSTRAINT `comments_post_FK` FOREIGN KEY (`post_id`) REFERENCES `post` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

insert
	into
	role (name)
values ('user'),
('organization');

CREATE TABLE `shares` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `account_uuid` char(32) NOT NULL,
  `content_id` bigint(20) NOT NULL,
  `content_type` smallint(6) NOT NULL,
  `comment` text DEFAULT NULL,
  `date_created` datetime NOT NULL DEFAULT current_timestamp(),
  `last_modified_date` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `shares_account_uuid_IDX` (`account_uuid`,`content_id`,`content_type`) USING BTREE,
  CONSTRAINT `shares_account_FK` FOREIGN KEY (`account_uuid`) REFERENCES `account` (`uuid`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;

CREATE TABLE `notification` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `recipient_id` bigint(20) NOT NULL,
  `type` enum('organization_membership_accepted','rsvp_accepted','new_post','event_update','new_membership_request','new_rsvp_request') NOT NULL,
  `title` varchar(255) NOT NULL,
  `message` text NOT NULL,
  `is_read` tinyint(1) NOT NULL DEFAULT 0,
  `related_entity_id` bigint(20) DEFAULT NULL,
  `related_entity_type` enum('organization','event','post','rsvp','user') DEFAULT NULL,
  `created_date` datetime NOT NULL DEFAULT current_timestamp(),
  `read_date` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `notification_recipient_FK` (`recipient_id`),
  KEY `notification_recipient_read_IDX` (`recipient_id`,`is_read`) USING BTREE,
  KEY `notification_created_date_IDX` (`created_date`) USING BTREE,
  CONSTRAINT `notification_recipient_FK` FOREIGN KEY (`recipient_id`) REFERENCES `account` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf32 COLLATE=utf32_bin;