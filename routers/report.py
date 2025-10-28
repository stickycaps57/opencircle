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
