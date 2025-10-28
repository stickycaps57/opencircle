from fastapi import APIRouter, HTTPException, Query, Cookie
from lib.database import Database
from sqlalchemy import select, func, and_
from sqlalchemy.exc import SQLAlchemyError
from utils.session_utils import get_account_uuid_from_session
from datetime import datetime
from typing import Optional

router = APIRouter(
    prefix="/report",
    tags=["Analytics and Reporting"],
)

db = Database()
table = db.tables


@router.get("/event-respondents", tags=["Event Analytics"])
async def get_event_respondents_analytics(
    session_token: str = Cookie(None, alias="session_token"),
    event_id: Optional[int] = Query(None, description="Filter by specific event ID"),
    start_date: Optional[datetime] = Query(None, description="Filter RSVPs modified after this date (YYYY-MM-DD HH:MM:SS)"),
    end_date: Optional[datetime] = Query(None, description="Filter RSVPs modified before this date (YYYY-MM-DD HH:MM:SS)"),
):
    """
    Get RSVP analytics for events owned by the organization.
    Returns counts of joined, rejected, and pending responses per event.
    Supports date filtering based on RSVP last_modified_date.
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    try:
        # Get organization details from account
        org = (
            session.query(table["organization"])
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        organization_id = org.id

        # Build the base query for events owned by this organization
        events_query = (
            select(
                table["event"].c.id.label("event_id"),
                table["event"].c.title,
                table["event"].c.event_date,
                table["event"].c.created_date.label("event_created_date"),
            )
            .where(table["event"].c.organization_id == organization_id)
        )
        
        # Filter by specific event if provided
        if event_id:
            events_query = events_query.where(table["event"].c.id == event_id)

        events_result = session.execute(events_query).fetchall()
        
        if not events_result:
            return {"events": []}

        events_analytics = []
        
        for event in events_result:
            event_dict = event._mapping
            
            # Build RSVP query with date filters
            rsvp_conditions = [table["rsvp"].c.event_id == event_dict["event_id"]]
            
            if start_date:
                rsvp_conditions.append(table["rsvp"].c.last_modified_date >= start_date)
            if end_date:
                rsvp_conditions.append(table["rsvp"].c.last_modified_date <= end_date)
            
            # Get RSVP counts by status
            rsvp_stats_query = (
                select(
                    table["rsvp"].c.status,
                    func.count(table["rsvp"].c.id).label("count")
                )
                .where(and_(*rsvp_conditions))
                .group_by(table["rsvp"].c.status)
            )
            
            rsvp_stats_result = session.execute(rsvp_stats_query).fetchall()
            
            # Initialize counts
            stats = {
                "joined": 0,
                "rejected": 0,
                "pending": 0,
                "total": 0
            }
            
            # Populate actual counts
            for stat in rsvp_stats_result:
                stat_dict = stat._mapping
                stats[stat_dict["status"]] = stat_dict["count"]
                stats["total"] += stat_dict["count"]
            
            # Get total unique attendees (for additional insight)
            total_attendees_query = (
                select(func.count(func.distinct(table["rsvp"].c.attendee)))
                .where(and_(*rsvp_conditions))
            )
            total_attendees = session.execute(total_attendees_query).scalar() or 0
            
            events_analytics.append({
                "event_id": event_dict["event_id"],
                "event_title": event_dict["title"],
                "event_date": event_dict["event_date"],
                "event_created_date": event_dict["event_created_date"],
                "rsvp_statistics": stats,
                "unique_attendees": total_attendees,
                "response_rate": round((stats["total"] / max(total_attendees, 1)) * 100, 2) if total_attendees > 0 else 0
            })

        return {
            "organization_id": organization_id,
            "organization_name": org.name,
            "total_events": len(events_analytics),
            "date_filter": {
                "start_date": start_date,
                "end_date": end_date
            },
            "events": events_analytics
        }

    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/event-respondents-summary", tags=["Event Analytics"])
async def get_event_respondents_summary(
    session_token: str = Cookie(None, alias="session_token"),
    start_date: Optional[datetime] = Query(None, description="Filter RSVPs modified after this date (YYYY-MM-DD HH:MM:SS)"),
    end_date: Optional[datetime] = Query(None, description="Filter RSVPs modified before this date (YYYY-MM-DD HH:MM:SS)"),
):
    """
    Get aggregated RSVP summary across all events owned by the organization.
    Returns total counts and percentages for joined, rejected, and pending responses.
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    try:
        # Get organization details from account
        org = (
            session.query(table["organization"])
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        organization_id = org.id

        # Build conditions for date filtering
        rsvp_conditions = [
            table["event"].c.organization_id == organization_id
        ]
        
        if start_date:
            rsvp_conditions.append(table["rsvp"].c.last_modified_date >= start_date)
        if end_date:
            rsvp_conditions.append(table["rsvp"].c.last_modified_date <= end_date)

        # Get aggregated RSVP statistics across all events
        summary_query = (
            select(
                table["rsvp"].c.status,
                func.count(table["rsvp"].c.id).label("count")
            )
            .select_from(
                table["rsvp"]
                .join(table["event"], table["rsvp"].c.event_id == table["event"].c.id)
            )
            .where(and_(*rsvp_conditions))
            .group_by(table["rsvp"].c.status)
        )
        
        summary_result = session.execute(summary_query).fetchall()
        
        # Initialize summary stats
        summary_stats = {
            "joined": 0,
            "rejected": 0,
            "pending": 0,
            "total": 0
        }
        
        # Populate actual counts
        for stat in summary_result:
            stat_dict = stat._mapping
            summary_stats[stat_dict["status"]] = stat_dict["count"]
            summary_stats["total"] += stat_dict["count"]
        
        # Calculate percentages
        total = summary_stats["total"]
        percentages = {
            "joined_percentage": round((summary_stats["joined"] / max(total, 1)) * 100, 2),
            "rejected_percentage": round((summary_stats["rejected"] / max(total, 1)) * 100, 2),
            "pending_percentage": round((summary_stats["pending"] / max(total, 1)) * 100, 2)
        }

        # Get total number of events
        events_count_query = (
            select(func.count(table["event"].c.id))
            .where(table["event"].c.organization_id == organization_id)
        )
        total_events = session.execute(events_count_query).scalar() or 0

        # Get total unique attendees across all events
        unique_attendees_query = (
            select(func.count(func.distinct(table["rsvp"].c.attendee)))
            .select_from(
                table["rsvp"]
                .join(table["event"], table["rsvp"].c.event_id == table["event"].c.id)
            )
            .where(and_(*rsvp_conditions))
        )
        unique_attendees = session.execute(unique_attendees_query).scalar() or 0

        return {
            "organization_id": organization_id,
            "organization_name": org.name,
            "date_filter": {
                "start_date": start_date,
                "end_date": end_date
            },
            "summary": {
                "total_events": total_events,
                "unique_attendees": unique_attendees,
                "rsvp_counts": summary_stats,
                "rsvp_percentages": percentages,
                "average_rsvps_per_event": round(summary_stats["total"] / max(total_events, 1), 2)
            }
        }

    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/event-respondents-details", tags=["Event Analytics"])
async def get_event_respondents_details(
    event_id: int = Query(..., description="Event ID to get detailed respondent information"),
    session_token: str = Cookie(None, alias="session_token"),
    status_filter: Optional[str] = Query(None, description="Filter by RSVP status: joined, rejected, or pending"),
    start_date: Optional[datetime] = Query(None, description="Filter RSVPs modified after this date (YYYY-MM-DD HH:MM:SS)"),
    end_date: Optional[datetime] = Query(None, description="Filter RSVPs modified before this date (YYYY-MM-DD HH:MM:SS)"),
):
    """
    Get detailed respondent information for a specific event.
    Returns individual RSVP records with user details.
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    try:
        # Verify the organization owns this event
        event_org_query = (
            select(
                table["event"].c.id,
                table["event"].c.title,
                table["event"].c.event_date,
                table["organization"].c.id.label("org_id"),
                table["organization"].c.name.label("org_name")
            )
            .select_from(
                table["event"]
                .join(table["organization"], table["event"].c.organization_id == table["organization"].c.id)
                .join(table["account"], table["organization"].c.account_id == table["account"].c.id)
            )
            .where(
                and_(
                    table["event"].c.id == event_id,
                    table["account"].c.uuid == account_uuid
                )
            )
        )
        
        event_result = session.execute(event_org_query).first()
        if not event_result:
            raise HTTPException(status_code=404, detail="Event not found or access denied")
        
        event_data = event_result._mapping

        # Build conditions for RSVP filtering
        rsvp_conditions = [table["rsvp"].c.event_id == event_id]
        
        if status_filter and status_filter in ['joined', 'rejected', 'pending']:
            rsvp_conditions.append(table["rsvp"].c.status == status_filter)
        
        if start_date:
            rsvp_conditions.append(table["rsvp"].c.last_modified_date >= start_date)
        if end_date:
            rsvp_conditions.append(table["rsvp"].c.last_modified_date <= end_date)

        # Get detailed RSVP information with user details
        rsvp_details_query = (
            select(
                table["rsvp"].c.id.label("rsvp_id"),
                table["rsvp"].c.status,
                table["rsvp"].c.created_date.label("rsvp_created_date"),
                table["rsvp"].c.last_modified_date.label("rsvp_modified_date"),
                table["account"].c.id.label("account_id"),
                table["account"].c.uuid.label("account_uuid"),
                table["account"].c.email,
                table["user"].c.first_name,
                table["user"].c.last_name,
                table["user"].c.bio,
                table["user"].c.profile_picture,
                table["resource"].c.directory.label("profile_picture_directory"),
                table["resource"].c.filename.label("profile_picture_filename"),
            )
            .select_from(
                table["rsvp"]
                .join(table["account"], table["rsvp"].c.attendee == table["account"].c.id)
                .outerjoin(table["user"], table["account"].c.id == table["user"].c.account_id)
                .outerjoin(table["resource"], table["user"].c.profile_picture == table["resource"].c.id)
            )
            .where(and_(*rsvp_conditions))
            .order_by(table["rsvp"].c.last_modified_date.desc())
        )
        
        rsvp_details_result = session.execute(rsvp_details_query).fetchall()
        
        respondents = []
        for rsvp in rsvp_details_result:
            rsvp_dict = rsvp._mapping
            
            respondents.append({
                "rsvp_id": rsvp_dict["rsvp_id"],
                "status": rsvp_dict["status"],
                "rsvp_created_date": rsvp_dict["rsvp_created_date"],
                "rsvp_modified_date": rsvp_dict["rsvp_modified_date"],
                "attendee": {
                    "account_id": rsvp_dict["account_id"],
                    "account_uuid": rsvp_dict["account_uuid"],
                    "email": rsvp_dict["email"],
                    "first_name": rsvp_dict["first_name"],
                    "last_name": rsvp_dict["last_name"],
                    "bio": rsvp_dict["bio"],
                    "profile_picture": {
                        "id": rsvp_dict["profile_picture"],
                        "directory": rsvp_dict["profile_picture_directory"],
                        "filename": rsvp_dict["profile_picture_filename"],
                    } if rsvp_dict["profile_picture"] else None
                }
            })

        return {
            "event": {
                "id": event_data["id"],
                "title": event_data["title"],
                "event_date": event_data["event_date"],
                "organization_id": event_data["org_id"],
                "organization_name": event_data["org_name"]
            },
            "filters": {
                "status_filter": status_filter,
                "start_date": start_date,
                "end_date": end_date
            },
            "total_respondents": len(respondents),
            "respondents": respondents
        }

    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/membership-analytics", tags=["Membership Analytics"])
async def get_membership_analytics(
    session_token: str = Cookie(None, alias="session_token"),
    start_date: Optional[datetime] = Query(None, description="Filter memberships modified after this date (YYYY-MM-DD HH:MM:SS)"),
    end_date: Optional[datetime] = Query(None, description="Filter memberships modified before this date (YYYY-MM-DD HH:MM:SS)"),
    status_filter: Optional[str] = Query(None, description="Filter by membership status: pending, approved, rejected, left"),
):
    """
    Get membership analytics for the organization.
    Returns counts of pending, approved, rejected, and left memberships.
    Supports date filtering based on membership last_modified_date.
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    try:
        # Get organization details from account
        org = (
            session.query(table["organization"])
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        organization_id = org.id

        # Build conditions for membership filtering
        membership_conditions = [
            table["membership"].c.organization_id == organization_id
        ]
        
        if start_date:
            membership_conditions.append(table["membership"].c.last_modified_date >= start_date)
        if end_date:
            membership_conditions.append(table["membership"].c.last_modified_date <= end_date)
        if status_filter and status_filter in ['pending', 'approved', 'rejected', 'left']:
            membership_conditions.append(table["membership"].c.status == status_filter)

        # Get membership counts by status
        membership_stats_query = (
            select(
                table["membership"].c.status,
                func.count(table["membership"].c.id).label("count")
            )
            .where(and_(*membership_conditions))
            .group_by(table["membership"].c.status)
        )
        
        membership_stats_result = session.execute(membership_stats_query).fetchall()
        
        # Initialize membership stats
        membership_stats = {
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "left": 0,
            "total": 0
        }
        
        # Populate actual counts
        for stat in membership_stats_result:
            stat_dict = stat._mapping
            membership_stats[stat_dict["status"]] = stat_dict["count"]
            membership_stats["total"] += stat_dict["count"]
        
        # Calculate percentages
        total = membership_stats["total"]
        percentages = {
            "pending_percentage": round((membership_stats["pending"] / max(total, 1)) * 100, 2),
            "approved_percentage": round((membership_stats["approved"] / max(total, 1)) * 100, 2),
            "rejected_percentage": round((membership_stats["rejected"] / max(total, 1)) * 100, 2),
            "left_percentage": round((membership_stats["left"] / max(total, 1)) * 100, 2)
        }

        # Get active members count (approved status only)
        active_members_query = (
            select(func.count(table["membership"].c.id))
            .where(
                table["membership"].c.organization_id == organization_id,
                table["membership"].c.status == "approved"
            )
        )
        active_members_count = session.execute(active_members_query).scalar() or 0

        # Get membership applications in the last 30 days (for trend analysis)
        from datetime import timedelta
        thirty_days_ago = datetime.now() - timedelta(days=30)
        
        recent_applications_query = (
            select(func.count(table["membership"].c.id))
            .where(
                table["membership"].c.organization_id == organization_id,
                table["membership"].c.created_date >= thirty_days_ago
            )
        )
        recent_applications = session.execute(recent_applications_query).scalar() or 0

        # Get retention rate (approved vs left)
        total_ever_approved_query = (
            select(func.count(table["membership"].c.id))
            .where(
                table["membership"].c.organization_id == organization_id,
                table["membership"].c.status.in_(["approved", "left"])
            )
        )
        total_ever_approved = session.execute(total_ever_approved_query).scalar() or 0
        
        retention_rate = round((active_members_count / max(total_ever_approved, 1)) * 100, 2) if total_ever_approved > 0 else 0

        return {
            "organization_id": organization_id,
            "organization_name": org.name,
            "date_filter": {
                "start_date": start_date,
                "end_date": end_date,
                "status_filter": status_filter
            },
            "membership_analytics": {
                "status_counts": membership_stats,
                "status_percentages": percentages,
                "active_members": active_members_count,
                "recent_applications_30_days": recent_applications,
                "retention_rate_percentage": retention_rate,
                "conversion_rate_percentage": round((membership_stats["approved"] / max(membership_stats["total"], 1)) * 100, 2) if membership_stats["total"] > 0 else 0
            }
        }

    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/membership-details", tags=["Membership Analytics"])
async def get_membership_details(
    session_token: str = Cookie(None, alias="session_token"),
    status_filter: Optional[str] = Query(None, description="Filter by membership status: pending, approved, rejected, left"),
    start_date: Optional[datetime] = Query(None, description="Filter memberships modified after this date (YYYY-MM-DD HH:MM:SS)"),
    end_date: Optional[datetime] = Query(None, description="Filter memberships modified before this date (YYYY-MM-DD HH:MM:SS)"),
    limit: Optional[int] = Query(100, description="Maximum number of records to return (default: 100)"),
):
    """
    Get detailed membership information for the organization.
    Returns individual membership records with user details.
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    try:
        # Get organization details from account
        org = (
            session.query(table["organization"])
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        organization_id = org.id

        # Build conditions for membership filtering
        membership_conditions = [
            table["membership"].c.organization_id == organization_id
        ]
        
        if start_date:
            membership_conditions.append(table["membership"].c.last_modified_date >= start_date)
        if end_date:
            membership_conditions.append(table["membership"].c.last_modified_date <= end_date)
        if status_filter and status_filter in ['pending', 'approved', 'rejected', 'left']:
            membership_conditions.append(table["membership"].c.status == status_filter)

        # Get detailed membership information with user details
        membership_details_query = (
            select(
                table["membership"].c.id.label("membership_id"),
                table["membership"].c.status,
                table["membership"].c.created_date.label("membership_created_date"),
                table["membership"].c.last_modified_date.label("membership_modified_date"),
                table["user"].c.id.label("user_id"),
                table["user"].c.first_name,
                table["user"].c.last_name,
                table["user"].c.bio,
                table["user"].c.profile_picture,
                table["account"].c.id.label("account_id"),
                table["account"].c.uuid.label("account_uuid"),
                table["account"].c.email,
                table["account"].c.username,
                table["resource"].c.directory.label("profile_picture_directory"),
                table["resource"].c.filename.label("profile_picture_filename"),
            )
            .select_from(
                table["membership"]
                .join(table["user"], table["membership"].c.user_id == table["user"].c.id)
                .join(table["account"], table["user"].c.account_id == table["account"].c.id)
                .outerjoin(table["resource"], table["user"].c.profile_picture == table["resource"].c.id)
            )
            .where(and_(*membership_conditions))
            .order_by(table["membership"].c.last_modified_date.desc())
            .limit(limit)
        )
        
        membership_details_result = session.execute(membership_details_query).fetchall()
        
        members = []
        for membership in membership_details_result:
            membership_dict = membership._mapping
            
            members.append({
                "membership_id": membership_dict["membership_id"],
                "status": membership_dict["status"],
                "membership_created_date": membership_dict["membership_created_date"],
                "membership_modified_date": membership_dict["membership_modified_date"],
                "member": {
                    "user_id": membership_dict["user_id"],
                    "account_id": membership_dict["account_id"],
                    "account_uuid": membership_dict["account_uuid"],
                    "email": membership_dict["email"],
                    "username": membership_dict["username"],
                    "first_name": membership_dict["first_name"],
                    "last_name": membership_dict["last_name"],
                    "bio": membership_dict["bio"],
                    "profile_picture": {
                        "id": membership_dict["profile_picture"],
                        "directory": membership_dict["profile_picture_directory"],
                        "filename": membership_dict["profile_picture_filename"],
                    } if membership_dict["profile_picture"] else None
                }
            })

        # Get total count for pagination info
        total_count_query = (
            select(func.count(table["membership"].c.id))
            .where(and_(*membership_conditions))
        )
        total_count = session.execute(total_count_query).scalar() or 0

        return {
            "organization_id": organization_id,
            "organization_name": org.name,
            "filters": {
                "status_filter": status_filter,
                "start_date": start_date,
                "end_date": end_date,
                "limit": limit
            },
            "total_members": total_count,
            "returned_members": len(members),
            "members": members
        }

    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/comment-analytics/posts", tags=["reports"])
async def get_post_comment_analytics(
    session_token: str = Cookie(None, alias="session_token"),
    start_date: Optional[datetime] = Query(None, description="Start date for filtering (YYYY-MM-DD HH:MM:SS)"),
    end_date: Optional[datetime] = Query(None, description="End date for filtering (YYYY-MM-DD HH:MM:SS)")
):
    """
    Get comment analytics for all posts owned by the organization.
    Returns the total number of comments on organization's posts with date filtering using comment created_date.
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    try:
        # Get organization details from account
        org = (
            session.query(table["organization"])
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        organization_id = org.id

        # Build date filter conditions for comments
        comment_conditions = []
        if start_date:
            comment_conditions.append(table["comment"].c.created_date >= start_date)
        if end_date:
            comment_conditions.append(table["comment"].c.created_date <= end_date)

        # Get posts with comment analytics
        posts_query = (
            select(
                table["post"].c.id.label("post_id"),
                table["post"].c.description.label("post_description"),
                table["post"].c.created_date.label("post_created_date"),
                func.count(table["comment"].c.id).label("comment_count"),
                func.min(table["comment"].c.created_date).label("first_comment_date"),
                func.max(table["comment"].c.created_date).label("last_comment_date")
            )
            .select_from(
                table["post"]
                .outerjoin(
                    table["comment"],
                    and_(
                        table["post"].c.id == table["comment"].c.post_id,
                        *comment_conditions
                    )
                )
            )
            .where(table["post"].c.author == organization_id)
            .group_by(
                table["post"].c.id,
                table["post"].c.description,
                table["post"].c.created_date
            )
            .order_by(table["post"].c.created_date.desc())
        )

        results = session.execute(posts_query).fetchall()

        # Calculate totals
        total_posts = len(results)
        total_comments = sum(row.comment_count for row in results)
        posts_with_comments = sum(1 for row in results if row.comment_count > 0)

        # Format response
        post_analytics = []
        for row in results:
            row_dict = row._mapping
            post_analytics.append({
                "post_id": row_dict["post_id"],
                "post_description": row_dict["post_description"][:100] + "..." if len(row_dict["post_description"]) > 100 else row_dict["post_description"],
                "post_created_date": row_dict["post_created_date"],
                "comment_count": row_dict["comment_count"],
                "first_comment_date": row_dict["first_comment_date"],
                "last_comment_date": row_dict["last_comment_date"]
            })

        return {
            "organization_id": organization_id,
            "organization_name": org.name,
            "filters": {
                "start_date": start_date,
                "end_date": end_date
            },
            "summary": {
                "total_posts": total_posts,
                "total_comments": total_comments,
                "posts_with_comments": posts_with_comments,
                "posts_without_comments": total_posts - posts_with_comments,
                "average_comments_per_post": round(total_comments / total_posts, 2) if total_posts > 0 else 0
            },
            "post_analytics": post_analytics
        }

    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/comment-analytics/events", tags=["reports"])
async def get_event_comment_analytics(
    session_token: str = Cookie(None, alias="session_token"),
    start_date: Optional[datetime] = Query(None, description="Start date for filtering (YYYY-MM-DD HH:MM:SS)"),
    end_date: Optional[datetime] = Query(None, description="End date for filtering (YYYY-MM-DD HH:MM:SS)")
):
    """
    Get comment analytics for all events owned by the organization.
    Returns the total number of comments on organization's events with date filtering using comment created_date.
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    try:
        # Get organization details from account
        org = (
            session.query(table["organization"])
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        organization_id = org.id

        # Build date filter conditions for comments
        comment_conditions = []
        if start_date:
            comment_conditions.append(table["comment"].c.created_date >= start_date)
        if end_date:
            comment_conditions.append(table["comment"].c.created_date <= end_date)

        # Get events with comment analytics
        events_query = (
            select(
                table["event"].c.id.label("event_id"),
                table["event"].c.title.label("event_title"),
                table["event"].c.event_date,
                table["event"].c.created_date.label("event_created_date"),
                func.count(table["comment"].c.id).label("comment_count"),
                func.min(table["comment"].c.created_date).label("first_comment_date"),
                func.max(table["comment"].c.created_date).label("last_comment_date")
            )
            .select_from(
                table["event"]
                .outerjoin(
                    table["comment"],
                    and_(
                        table["event"].c.id == table["comment"].c.event_id,
                        *comment_conditions
                    )
                )
            )
            .where(table["event"].c.organization_id == organization_id)
            .group_by(
                table["event"].c.id,
                table["event"].c.title,
                table["event"].c.event_date,
                table["event"].c.created_date
            )
            .order_by(table["event"].c.event_date.desc())
        )

        results = session.execute(events_query).fetchall()

        # Calculate totals
        total_events = len(results)
        total_comments = sum(row.comment_count for row in results)
        events_with_comments = sum(1 for row in results if row.comment_count > 0)

        # Format response
        event_analytics = []
        for row in results:
            row_dict = row._mapping
            event_analytics.append({
                "event_id": row_dict["event_id"],
                "event_title": row_dict["event_title"],
                "event_date": row_dict["event_date"],
                "event_created_date": row_dict["event_created_date"],
                "comment_count": row_dict["comment_count"],
                "first_comment_date": row_dict["first_comment_date"],
                "last_comment_date": row_dict["last_comment_date"]
            })

        return {
            "organization_id": organization_id,
            "organization_name": org.name,
            "filters": {
                "start_date": start_date,
                "end_date": end_date
            },
            "summary": {
                "total_events": total_events,
                "total_comments": total_comments,
                "events_with_comments": events_with_comments,
                "events_without_comments": total_events - events_with_comments,
                "average_comments_per_event": round(total_comments / total_events, 2) if total_events > 0 else 0
            },
            "event_analytics": event_analytics
        }

    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/comment-analytics/summary", tags=["reports"])
async def get_comment_analytics_summary(
    session_token: str = Cookie(None, alias="session_token"),
    start_date: Optional[datetime] = Query(None, description="Start date for filtering (YYYY-MM-DD HH:MM:SS)"),
    end_date: Optional[datetime] = Query(None, description="End date for filtering (YYYY-MM-DD HH:MM:SS)")
):
    """
    Get a comprehensive summary of comment analytics for both posts and events owned by the organization.
    Returns aggregated statistics with date filtering using comment created_date.
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    try:
        # Get organization details from account
        org = (
            session.query(table["organization"])
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        organization_id = org.id

        # Build date filter conditions for comments
        comment_conditions = []
        if start_date:
            comment_conditions.append(table["comment"].c.created_date >= start_date)
        if end_date:
            comment_conditions.append(table["comment"].c.created_date <= end_date)

        # Get post comment summary
        post_summary_query = (
            select(
                func.count(func.distinct(table["post"].c.id)).label("total_posts"),
                func.count(table["comment"].c.id).label("total_post_comments")
            )
            .select_from(
                table["post"]
                .outerjoin(
                    table["comment"],
                    and_(
                        table["post"].c.id == table["comment"].c.post_id,
                        *comment_conditions
                    )
                )
            )
            .where(table["post"].c.author == organization_id)
        )

        # Get posts with comments count separately
        posts_with_comments_query = (
            select(
                func.count(func.distinct(table["post"].c.id)).label("posts_with_comments")
            )
            .select_from(
                table["post"]
                .join(
                    table["comment"],
                    and_(
                        table["post"].c.id == table["comment"].c.post_id,
                        *comment_conditions
                    )
                )
            )
            .where(table["post"].c.author == organization_id)
        )

        post_result = session.execute(post_summary_query).fetchone()
        posts_with_comments_result = session.execute(posts_with_comments_query).fetchone()

        # Get event comment summary
        event_summary_query = (
            select(
                func.count(func.distinct(table["event"].c.id)).label("total_events"),
                func.count(table["comment"].c.id).label("total_event_comments")
            )
            .select_from(
                table["event"]
                .outerjoin(
                    table["comment"],
                    and_(
                        table["event"].c.id == table["comment"].c.event_id,
                        *comment_conditions
                    )
                )
            )
            .where(table["event"].c.organization_id == organization_id)
        )

        # Get events with comments count separately
        events_with_comments_query = (
            select(
                func.count(func.distinct(table["event"].c.id)).label("events_with_comments")
            )
            .select_from(
                table["event"]
                .join(
                    table["comment"],
                    and_(
                        table["event"].c.id == table["comment"].c.event_id,
                        *comment_conditions
                    )
                )
            )
            .where(table["event"].c.organization_id == organization_id)
        )

        event_result = session.execute(event_summary_query).fetchone()
        events_with_comments_result = session.execute(events_with_comments_query).fetchone()

        # Get daily comment trends (limited to 30 days)
        from datetime import timedelta
        thirty_days_ago = datetime.now() - timedelta(days=30)
        
        trends_conditions = comment_conditions.copy()
        trends_conditions.append(table["comment"].c.created_date >= thirty_days_ago)

        # Separate queries for post and event comments in trends
        post_trends_query = (
            select(
                func.date(table["comment"].c.created_date).label("comment_date"),
                func.count(table["comment"].c.id).label("post_comments")
            )
            .select_from(
                table["comment"]
                .join(table["post"], table["comment"].c.post_id == table["post"].c.id)
            )
            .where(
                and_(
                    table["post"].c.author == organization_id,
                    *trends_conditions
                )
            )
            .group_by(func.date(table["comment"].c.created_date))
        )

        event_trends_query = (
            select(
                func.date(table["comment"].c.created_date).label("comment_date"),
                func.count(table["comment"].c.id).label("event_comments")
            )
            .select_from(
                table["comment"]
                .join(table["event"], table["comment"].c.event_id == table["event"].c.id)
            )
            .where(
                and_(
                    table["event"].c.organization_id == organization_id,
                    *trends_conditions
                )
            )
            .group_by(func.date(table["comment"].c.created_date))
        )

        post_trends_results = session.execute(post_trends_query).fetchall()
        event_trends_results = session.execute(event_trends_query).fetchall()

        # Combine trends data
        trends_data = {}
        for row in post_trends_results:
            row_dict = row._mapping
            date_key = row_dict["comment_date"]
            if date_key not in trends_data:
                trends_data[date_key] = {"post_comments": 0, "event_comments": 0}
            trends_data[date_key]["post_comments"] = row_dict["post_comments"]

        for row in event_trends_results:
            row_dict = row._mapping
            date_key = row_dict["comment_date"]
            if date_key not in trends_data:
                trends_data[date_key] = {"post_comments": 0, "event_comments": 0}
            trends_data[date_key]["event_comments"] = row_dict["event_comments"]

        # Calculate totals
        post_dict = post_result._mapping
        event_dict = event_result._mapping
        posts_with_comments_dict = posts_with_comments_result._mapping
        events_with_comments_dict = events_with_comments_result._mapping

        total_posts = post_dict["total_posts"] or 0
        total_post_comments = post_dict["total_post_comments"] or 0
        posts_with_comments = posts_with_comments_dict["posts_with_comments"] or 0

        total_events = event_dict["total_events"] or 0
        total_event_comments = event_dict["total_event_comments"] or 0
        events_with_comments = events_with_comments_dict["events_with_comments"] or 0

        total_comments = total_post_comments + total_event_comments
        total_content = total_posts + total_events
        content_with_comments = posts_with_comments + events_with_comments

        # Format daily trends
        daily_trends = []
        for date_key in sorted(trends_data.keys(), reverse=True)[:30]:
            daily_trends.append({
                "date": date_key,
                "post_comments": trends_data[date_key]["post_comments"],
                "event_comments": trends_data[date_key]["event_comments"],
                "total_comments": trends_data[date_key]["post_comments"] + trends_data[date_key]["event_comments"]
            })

        return {
            "organization_id": organization_id,
            "organization_name": org.name,
            "filters": {
                "start_date": start_date,
                "end_date": end_date
            },
            "overall_summary": {
                "total_content_items": total_content,
                "total_comments": total_comments,
                "content_with_comments": content_with_comments,
                "content_without_comments": total_content - content_with_comments,
                "average_comments_per_content": round(total_comments / total_content, 2) if total_content > 0 else 0,
                "comment_engagement_rate": round((content_with_comments / total_content) * 100, 2) if total_content > 0 else 0
            },
            "post_summary": {
                "total_posts": total_posts,
                "total_post_comments": total_post_comments,
                "posts_with_comments": posts_with_comments,
                "posts_without_comments": total_posts - posts_with_comments,
                "average_comments_per_post": round(total_post_comments / total_posts, 2) if total_posts > 0 else 0
            },
            "event_summary": {
                "total_events": total_events,
                "total_event_comments": total_event_comments,
                "events_with_comments": events_with_comments,
                "events_without_comments": total_events - events_with_comments,
                "average_comments_per_event": round(total_event_comments / total_events, 2) if total_events > 0 else 0
            },
            "daily_trends": daily_trends
        }

    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
