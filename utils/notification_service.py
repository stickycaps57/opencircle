from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from lib.database import Database
from sqlalchemy import insert, update, select
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel


class NotificationType(str, Enum):
    ORGANIZATION_MEMBERSHIP_ACCEPTED = "organization_membership_accepted"
    RSVP_ACCEPTED = "rsvp_accepted"
    NEW_POST = "new_post"
    EVENT_UPDATE = "event_update"
    NEW_MEMBERSHIP_REQUEST = "new_membership_request"
    NEW_RSVP_REQUEST = "new_rsvp_request"


class RelatedEntityType(str, Enum):
    ORGANIZATION = "organization"
    EVENT = "event"
    POST = "post"
    RSVP = "rsvp"
    USER = "user"


class NotificationCreate(BaseModel):
    recipient_id: int
    type: NotificationType
    title: str
    message: str
    related_entity_id: Optional[int] = None
    related_entity_type: Optional[RelatedEntityType] = None


class NotificationResponse(BaseModel):
    id: int
    recipient_id: int
    type: str
    title: str
    message: str
    is_read: bool
    related_entity_id: Optional[int]
    related_entity_type: Optional[str]
    created_date: datetime
    read_date: Optional[datetime]


class NotificationService:
    def __init__(self):
        self.db = Database()
        self.table = self.db.tables
        self.session = self.db.session

    def create_notification(
        self,
        recipient_id: int,
        notification_type: NotificationType,
        title: str,
        message: str,
        related_entity_id: Optional[int] = None,
        related_entity_type: Optional[RelatedEntityType] = None,
    ) -> bool:
        """Create a new notification for a user."""
        try:
            stmt = insert(self.table["notification"]).values(
                recipient_id=recipient_id,
                type=notification_type,
                title=title,
                message=message,
                related_entity_id=related_entity_id,
                related_entity_type=related_entity_type,
            )
            self.session.execute(stmt)
            self.session.commit()
            return True
        except SQLAlchemyError as e:
            self.session.rollback()
            print(f"Error creating notification: {e}")
            return False
        except Exception as e:
            self.session.rollback()
            print(f"Unexpected error creating notification: {e}")
            return False

    def notify_organization_membership_accepted(
        self, user_account_id: int, organization_id: int, organization_name: str
    ) -> bool:
        """Notify user when their organization membership is accepted."""
        title = "Membership Approved!"
        message = f"Congratulations! Your membership to {organization_name} has been approved."

        return self.create_notification(
            recipient_id=user_account_id,
            notification_type=NotificationType.ORGANIZATION_MEMBERSHIP_ACCEPTED,
            title=title,
            message=message,
            related_entity_id=organization_id,
            related_entity_type=RelatedEntityType.ORGANIZATION,
        )

    def notify_rsvp_accepted(
        self, user_account_id: int, event_id: int, event_title: str
    ) -> bool:
        """Notify user when their RSVP to an event is accepted."""
        title = "RSVP Accepted!"
        message = f"Your RSVP to '{event_title}' has been accepted. See you there!"

        return self.create_notification(
            recipient_id=user_account_id,
            notification_type=NotificationType.RSVP_ACCEPTED,
            title=title,
            message=message,
            related_entity_id=event_id,
            related_entity_type=RelatedEntityType.EVENT,
        )

    def notify_organization_members_new_post(
        self, organization_id: int, post_id: int, organization_name: str, post_preview: str
    ) -> bool:
        """Notify all organization members about a new post."""
        try:
            # Get all approved members of the organization
            members_query = (
                self.session.query(
                    self.table["user"].c.account_id
                )
                .join(
                    self.table["membership"],
                    self.table["user"].c.id == self.table["membership"].c.user_id
                )
                .filter(
                    self.table["membership"].c.organization_id == organization_id,
                    self.table["membership"].c.status == "approved"
                )
                .all()
            )

            if not members_query:
                return True  # No members to notify, but not an error

            title = f"New Post from {organization_name}"
            message = f"Check out the latest update: {post_preview[:100]}{'...' if len(post_preview) > 100 else ''}"

            # Create notifications for all members
            success_count = 0
            for member in members_query:
                if self.create_notification(
                    recipient_id=member.account_id,
                    notification_type=NotificationType.NEW_POST,
                    title=title,
                    message=message,
                    related_entity_id=post_id,
                    related_entity_type=RelatedEntityType.POST,
                ):
                    success_count += 1

            return success_count > 0

        except SQLAlchemyError as e:
            print(f"Error notifying members about new post: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error notifying members about new post: {e}")
            return False

    def notify_organization_members_new_event(
        self, organization_id: int, event_id: int, organization_name: str, event_title: str, event_date: str
    ) -> bool:
        """Notify all organization members about a new event."""
        try:
            # Get all approved members of the organization
            members_query = (
                self.session.query(
                    self.table["user"].c.account_id
                )
                .join(
                    self.table["membership"],
                    self.table["user"].c.id == self.table["membership"].c.user_id
                )
                .filter(
                    self.table["membership"].c.organization_id == organization_id,
                    self.table["membership"].c.status == "approved"
                )
                .all()
            )

            if not members_query:
                return True  # No members to notify, but not an error

            title = f"New Event: {event_title}"
            message = f"{organization_name} has created a new event '{event_title}' on {event_date}. Don't miss out!"

            # Create notifications for all members
            success_count = 0
            for member in members_query:
                if self.create_notification(
                    recipient_id=member.account_id,
                    notification_type=NotificationType.EVENT_UPDATE,
                    title=title,
                    message=message,
                    related_entity_id=event_id,
                    related_entity_type=RelatedEntityType.EVENT,
                ):
                    success_count += 1

            return success_count > 0

        except SQLAlchemyError as e:
            print(f"Error notifying members about new event: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error notifying members about new event: {e}")
            return False

    def notify_organization_new_membership_request(
        self, organization_account_id: int, user_name: str, user_account_id: int
    ) -> bool:
        """Notify organization when a new membership request is received."""
        title = "New Membership Request"
        message = f"You have received a new membership request from {user_name}."

        return self.create_notification(
            recipient_id=organization_account_id,
            notification_type=NotificationType.NEW_MEMBERSHIP_REQUEST,
            title=title,
            message=message,
            related_entity_id=user_account_id,  # Using user_account_id for easier reference
            related_entity_type=RelatedEntityType.USER,
        )

    def notify_organization_new_rsvp_request(
        self, organization_account_id: int, user_name: str, event_id: int, event_title: str
    ) -> bool:
        """Notify organization when a new RSVP request is received for their event."""
        title = "New RSVP Request"
        message = f"{user_name} has requested to RSVP for your event '{event_title}'."

        return self.create_notification(
            recipient_id=organization_account_id,
            notification_type=NotificationType.NEW_RSVP_REQUEST,
            title=title,
            message=message,
            related_entity_id=event_id,
            related_entity_type=RelatedEntityType.EVENT,
        )

    def get_user_notifications(
        self, user_account_id: int, unread_only: bool = False, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get notifications for a user."""
        try:
            query = self.session.query(self.table["notification"]).filter(
                self.table["notification"].c.recipient_id == user_account_id
            )

            if unread_only:
                query = query.filter(self.table["notification"].c.is_read == False)

            notifications = (
                query.order_by(self.table["notification"].c.created_date.desc())
                .limit(limit)
                .all()
            )

            return [
                {
                    "id": notification.id,
                    "recipient_id": notification.recipient_id,
                    "type": notification.type,
                    "title": notification.title,
                    "message": notification.message,
                    "is_read": notification.is_read,
                    "related_entity_id": notification.related_entity_id,
                    "related_entity_type": notification.related_entity_type,
                    "created_date": notification.created_date,
                    "read_date": notification.read_date,
                }
                for notification in notifications
            ]

        except SQLAlchemyError as e:
            print(f"Error getting user notifications: {e}")
            return []
        except Exception as e:
            print(f"Unexpected error getting user notifications: {e}")
            return []

    def mark_notification_as_read(self, notification_id: int, user_account_id: int) -> bool:
        """Mark a specific notification as read."""
        try:
            stmt = (
                update(self.table["notification"])
                .where(
                    self.table["notification"].c.id == notification_id,
                    self.table["notification"].c.recipient_id == user_account_id,
                )
                .values(is_read=True, read_date=datetime.now())
            )
            result = self.session.execute(stmt)
            self.session.commit()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            self.session.rollback()
            print(f"Error marking notification as read: {e}")
            return False
        except Exception as e:
            self.session.rollback()
            print(f"Unexpected error marking notification as read: {e}")
            return False

    def mark_all_notifications_as_read(self, user_account_id: int) -> bool:
        """Mark all notifications for a user as read."""
        try:
            stmt = (
                update(self.table["notification"])
                .where(
                    self.table["notification"].c.recipient_id == user_account_id,
                    self.table["notification"].c.is_read == False,
                )
                .values(is_read=True, read_date=datetime.now())
            )
            self.session.execute(stmt)
            self.session.commit()
            return True
        except SQLAlchemyError as e:
            self.session.rollback()
            print(f"Error marking all notifications as read: {e}")
            return False
        except Exception as e:
            self.session.rollback()
            print(f"Unexpected error marking all notifications as read: {e}")
            return False

    def get_unread_count(self, user_account_id: int) -> int:
        """Get the count of unread notifications for a user."""
        try:
            count = (
                self.session.query(self.table["notification"])
                .filter(
                    self.table["notification"].c.recipient_id == user_account_id,
                    self.table["notification"].c.is_read == False,
                )
                .count()
            )
            return count
        except SQLAlchemyError as e:
            print(f"Error getting unread count: {e}")
            return 0
        except Exception as e:
            print(f"Unexpected error getting unread count: {e}")
            return 0

    def delete_notification(self, notification_id: int, user_account_id: int) -> bool:
        """Delete a specific notification for a user."""
        try:
            stmt = self.table["notification"].delete().where(
                self.table["notification"].c.id == notification_id,
                self.table["notification"].c.recipient_id == user_account_id,
            )
            result = self.session.execute(stmt)
            self.session.commit()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            self.session.rollback()
            print(f"Error deleting notification: {e}")
            return False
        except Exception as e:
            self.session.rollback()
            print(f"Unexpected error deleting notification: {e}")
            return False

    def close(self):
        """Close the database session."""
        self.session.close()
