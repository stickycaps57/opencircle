from fastapi import APIRouter, HTTPException, Query, Path
from fastapi import Request
from utils.session_utils import get_account_uuid_from_session
from utils.notification_service import NotificationService, NotificationResponse
from lib.database import Database
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional

router = APIRouter(
    prefix="/notification",
    tags=["Notification Management"],
)

db = Database()
table = db.tables


@router.get("/", tags=["Get User Notifications"])
async def get_user_notifications(
    request: Request,
    unread_only: bool = Query(False, description="Get only unread notifications"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of notifications to return"),
):
    """Get notifications for the authenticated user."""
    # Get session_token from cookie
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Use utility function to get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)
    
    session = db.session
    notification_service = NotificationService()
    
    try:
        # Get account_id from uuid
        account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        account_id = account.id

        # Get notifications using the service
        notifications = notification_service.get_user_notifications(
            user_account_id=account_id,
            unread_only=unread_only,
            limit=limit
        )

        return {
            "notifications": notifications,
            "count": len(notifications),
            "unread_only": unread_only,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
        notification_service.close()


@router.get("/count/unread", tags=["Get Unread Notification Count"])
async def get_unread_notification_count(request: Request):
    """Get the count of unread notifications for the authenticated user."""
    # Get session_token from cookie
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Use utility function to get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)
    
    session = db.session
    notification_service = NotificationService()
    
    try:
        # Get account_id from uuid
        account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        account_id = account.id

        # Get unread count using the service
        unread_count = notification_service.get_unread_count(user_account_id=account_id)

        return {"unread_count": unread_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
        notification_service.close()


@router.put("/{notification_id}/read", tags=["Mark Notification as Read"])
async def mark_notification_as_read(
    notification_id: int = Path(..., description="ID of the notification to mark as read"),
    request: Request = None,
):
    """Mark a specific notification as read."""
    # Get session_token from cookie
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Use utility function to get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)
    
    session = db.session
    notification_service = NotificationService()
    
    try:
        # Get account_id from uuid
        account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        account_id = account.id

        # Mark notification as read using the service
        success = notification_service.mark_notification_as_read(
            notification_id=notification_id,
            user_account_id=account_id
        )

        if not success:
            raise HTTPException(
                status_code=404,
                detail="Notification not found or not owned by user"
            )

        return {"message": "Notification marked as read"}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
        notification_service.close()


@router.put("/read-all", tags=["Mark All Notifications as Read"])
async def mark_all_notifications_as_read(request: Request):
    """Mark all notifications for the authenticated user as read."""
    # Get session_token from cookie
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Use utility function to get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)
    
    session = db.session
    notification_service = NotificationService()
    
    try:
        # Get account_id from uuid
        account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        account_id = account.id

        # Mark all notifications as read using the service
        success = notification_service.mark_all_notifications_as_read(
            user_account_id=account_id
        )

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to mark notifications as read"
            )

        return {"message": "All notifications marked as read"}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
        notification_service.close()


@router.delete("/{notification_id}", tags=["Delete Notification"])
async def delete_notification(
    notification_id: int = Path(..., description="ID of the notification to delete"),
    request: Request = None,
):
    """Delete a specific notification."""
    # Get session_token from cookie
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Use utility function to get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)
    
    session = db.session
    notification_service = NotificationService()
    
    try:
        # Get account_id from uuid
        account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        account_id = account.id

        # Delete notification using the service
        success = notification_service.delete_notification(
            notification_id=notification_id,
            user_account_id=account_id
        )

        if not success:
            raise HTTPException(
                status_code=404,
                detail="Notification not found or not owned by user"
            )

        return {"message": "Notification deleted successfully"}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
        notification_service.close()
