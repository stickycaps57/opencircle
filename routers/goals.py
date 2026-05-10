from fastapi import APIRouter, HTTPException, Form, Path, Query, Cookie
from lib.database import Database
from sqlalchemy import insert, update, select, delete, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from typing import Optional
from utils.session_utils import get_account_uuid_from_session
from utils.datetime_utils import format_datetime
from datetime import datetime

router = APIRouter(
    prefix="/goals",
    tags=["Goals Management"],
)

db = Database()
table = db.tables


RECOMMENDATION_CATALOG = {
    "LOW_INTERACTIONS_COMMENTS": {
        "title": "Low interactions or comments",
        "message": "Member interaction is currently low. Consider posting more announcements or organizing interactive events.",
        "priority": "high",
    },
    "LOW_EVENT_PARTICIPATION": {
        "title": "Low event participation",
        "message": "Recent events have low participation rates. Consider adjusting event schedules or increasing event promotion.",
        "priority": "high",
    },
    "MEMBERSHIP_DECLINE": {
        "title": "Membership decline",
        "message": "Member departures currently exceed new registrations during this selected period.",
        "priority": "high",
    },
    "HIGH_ENGAGEMENT": {
        "title": "High engagement",
        "message": "The organization currently demonstrates strong member engagement and participation.",
        "priority": "low",
    },
    "LOW_POSTING_ACTIVITY": {
        "title": "Low posting activity",
        "message": "The organization currently has low posting activity. Consider posting announcements or updates more frequently.",
        "priority": "high",
    },
}


def _is_in_middle_timeframe(goal_start, goal_end, now_utc):
    """Return True if current time is in the second half of the goal timeframe and before end."""
    if not goal_start or not goal_end or goal_end <= goal_start:
        return False
    midpoint = goal_start + (goal_end - goal_start) / 2
    return midpoint <= now_utc <= goal_end


def _get_recommendation_code(goal_type, progress_percentage):
    """Map goal type and progress to a frontend-friendly recommendation code."""
    if progress_percentage >= 70:
        return None

    code_map = {
        "engagement": "LOW_INTERACTIONS_COMMENTS",
        "event_participation": "LOW_EVENT_PARTICIPATION",
        "member_growth": "MEMBERSHIP_DECLINE",
        "retention": "MEMBERSHIP_DECLINE",
        "announcement_activity": "LOW_POSTING_ACTIVITY",
    }
    return code_map.get(goal_type)


def compute_and_sync_progress(session, goal):
    """
    For goals whose progress can be derived from existing data, compute the
    current value live and persist it to goal_progress, then return a dict
    with current_value, progress_percentage, and updated_date.

    Returns None for goal types that require manual progress updates.
    """
    current_value = None

    if goal.goal_type == "member_growth":
        # Count memberships that moved to 'approved' within the goal date range
        result = session.execute(
            select(func.count())
            .select_from(table["membership"])
            .where(
                table["membership"].c.organization_id == goal.organization_id,
                table["membership"].c.status == "approved",
                table["membership"].c.last_modified_date >= goal.start_date,
                table["membership"].c.last_modified_date <= goal.end_date,
            )
        ).scalar()
        current_value = result or 0

    elif goal.goal_type == "event_participation":
        # Count distinct accepted (joined) RSVPs across all organization events
        # whose event_date falls within the goal date range
        result = session.execute(
            select(func.count())
            .select_from(
                table["rsvp"].join(
                    table["event"],
                    table["rsvp"].c.event_id == table["event"].c.id,
                )
            )
            .where(
                table["event"].c.organization_id == goal.organization_id,
                table["rsvp"].c.status == "joined",
                table["event"].c.event_date >= goal.start_date,
                table["event"].c.event_date <= goal.end_date,
            )
        ).scalar()
        current_value = result or 0

    elif goal.goal_type == "engagement":
        # Get the organization owner account_id (author of organization posts)
        org_account_id = session.execute(
            select(table["organization"].c.account_id).where(
                table["organization"].c.id == goal.organization_id
            )
        ).scalar()

        # Subquery: account_ids of approved members in this organization
        member_account_ids = (
            select(table["account"].c.id)
            .select_from(
                table["membership"]
                .join(table["user"], table["membership"].c.user_id == table["user"].c.id)
                .join(table["account"], table["user"].c.account_id == table["account"].c.id)
            )
            .where(
                table["membership"].c.organization_id == goal.organization_id,
                table["membership"].c.status == "approved",
            )
            .scalar_subquery()
        )

        # Subquery: account_uuids of those same members (for shares table)
        member_account_uuids = (
            select(table["account"].c.uuid)
            .select_from(
                table["membership"]
                .join(table["user"], table["membership"].c.user_id == table["user"].c.id)
                .join(table["account"], table["user"].c.account_id == table["account"].c.id)
            )
            .where(
                table["membership"].c.organization_id == goal.organization_id,
                table["membership"].c.status == "approved",
            )
            .scalar_subquery()
        )

        # Comments by members on posts authored by the organization
        comment_count = session.execute(
            select(func.count())
            .select_from(
                table["comment"].join(
                    table["post"],
                    table["comment"].c.post_id == table["post"].c.id,
                )
            )
            .where(
                table["comment"].c.author.in_(member_account_ids),
                table["post"].c.author == org_account_id,
                table["comment"].c.created_date >= goal.start_date,
                table["comment"].c.created_date <= goal.end_date,
            )
        ).scalar() or 0

        # Shares by members of organization posts (content_type=1)
        share_post_count = session.execute(
            select(func.count())
            .select_from(
                table["shares"].join(
                    table["post"],
                    table["shares"].c.content_id == table["post"].c.id,
                )
            )
            .where(
                table["shares"].c.account_uuid.in_(member_account_uuids),
                table["shares"].c.content_type == 1,
                table["post"].c.author == org_account_id,
                table["shares"].c.date_created >= goal.start_date,
                table["shares"].c.date_created <= goal.end_date,
            )
        ).scalar() or 0

        # Shares by members of organization events (content_type=2)
        share_event_count = session.execute(
            select(func.count())
            .select_from(
                table["shares"].join(
                    table["event"],
                    table["shares"].c.content_id == table["event"].c.id,
                )
            )
            .where(
                table["shares"].c.account_uuid.in_(member_account_uuids),
                table["shares"].c.content_type == 2,
                table["event"].c.organization_id == goal.organization_id,
                table["shares"].c.date_created >= goal.start_date,
                table["shares"].c.date_created <= goal.end_date,
            )
        ).scalar() or 0

        current_value = comment_count + share_post_count + share_event_count

    elif goal.goal_type == "announcement_activity":
        # Count organization announcements (posts authored by organization account)
        org_account_id = session.execute(
            select(table["organization"].c.account_id).where(
                table["organization"].c.id == goal.organization_id
            )
        ).scalar()

        result = session.execute(
            select(func.count())
            .select_from(table["post"])
            .where(
                table["post"].c.author == org_account_id,
                table["post"].c.created_date >= goal.start_date,
                table["post"].c.created_date <= goal.end_date,
            )
        ).scalar()
        current_value = result or 0

    elif goal.goal_type == "retention":
        # Leave rate = (members who left during timeframe / total member records) * 100
        left_count = session.execute(
            select(func.count())
            .select_from(table["membership"])
            .where(
                table["membership"].c.organization_id == goal.organization_id,
                table["membership"].c.status == "left",
                table["membership"].c.last_modified_date >= goal.start_date,
                table["membership"].c.last_modified_date <= goal.end_date,
            )
        ).scalar() or 0

        total_members = session.execute(
            select(func.count())
            .select_from(table["membership"])
            .where(
                table["membership"].c.organization_id == goal.organization_id,
                table["membership"].c.status.in_(["approved", "left"]),
            )
        ).scalar() or 0

        leave_rate = (left_count / total_members * 100) if total_members > 0 else 0
        current_value = round(leave_rate)

    if current_value is None:
        return None

    if goal.goal_type == "retention":
        # Lower leave rate is better for retention goals
        if goal.target_value > 0:
            progress_percentage = min((goal.target_value / max(current_value, 1)) * 100, 100)
        else:
            progress_percentage = 100 if current_value == 0 else 0
    else:
        progress_percentage = (
            min(current_value / goal.target_value * 100, 100)
            if goal.target_value > 0
            else 0
        )

    # Determine status
    now = datetime.utcnow()
    if goal.goal_type == "retention":
        if current_value <= goal.target_value:
            new_status = "achieved"
        elif now > goal.end_date:
            new_status = "behind_target"
        else:
            new_status = "in_progress"
    elif progress_percentage >= 100:
        new_status = "achieved"
    elif now > goal.end_date:
        new_status = "behind_target"
    else:
        new_status = "in_progress"

    updated_at = datetime.utcnow()

    # Upsert into goal_progress
    existing = session.query(table["goal_progress"]).filter_by(goal_id=goal.id).first()
    if existing:
        session.execute(
            update(table["goal_progress"])
            .where(table["goal_progress"].c.goal_id == goal.id)
            .values(
                current_value=current_value,
                progress_percentage=progress_percentage,
                last_modified_date=updated_at,
            )
        )
    else:
        session.execute(
            insert(table["goal_progress"]).values(
                goal_id=goal.id,
                current_value=current_value,
                progress_percentage=progress_percentage,
                last_modified_date=updated_at,
            )
        )

    # Sync goal status
    session.execute(
        update(table["goal"])
        .where(table["goal"].c.id == goal.id)
        .values(status=new_status)
    )
    session.commit()

    return {
        "current_value": current_value,
        "progress_percentage": progress_percentage,
        "status": new_status,
        "updated_date": format_datetime(updated_at),
    }


@router.post("/", tags=["Create Goal"])
async def create_goal(
    organization_id: int = Form(...),
    goal_type: str = Form(...),
    title: str = Form(...),
    target_value: int = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    session_token: str = Cookie(None, alias="session_token"),
):
    """Create a new goal for an organization"""
    session = db.session

    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Verify the user owns the organization
        organization_query = (
            select(table["organization"].c.id, table["organization"].c.account_id)
            .where(table["organization"].c.id == organization_id)
        )
        org_result = session.execute(organization_query).first()

        if not org_result:
            raise HTTPException(status_code=404, detail="Organization not found")

        org_account_id = org_result._mapping["account_id"]

        # Verify the account matches
        account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
        if not account or account.id != org_account_id:
            raise HTTPException(status_code=403, detail="Unauthorized")

        # Normalize and validate date inputs so API responses always use ISO datetime format
        try:
            start_date_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end_date_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid date format. Use ISO format, e.g. 2026-05-10 or 2026-05-10T00:00:00Z",
            )

        # Validate goal_type
        valid_goal_types = [
            "member_growth",
            "event_participation",
            "engagement",
            "announcement_activity",
            "retention",
        ]
        if goal_type not in valid_goal_types:
            raise HTTPException(status_code=400, detail="Invalid goal_type")

        # Prevent duplicate goals of the same type for the same date range (date-only match)
        similar_goal = session.execute(
            select(table["goal"].c.id)
            .where(
                table["goal"].c.organization_id == organization_id,
                table["goal"].c.goal_type == goal_type,
                func.date(table["goal"].c.start_date) == start_date_dt.date(),
                func.date(table["goal"].c.end_date) == end_date_dt.date(),
            )
            .limit(1)
        ).first()
        if similar_goal:
            raise HTTPException(
                status_code=400,
                detail="You've already created a similar goal.",
            )

        # Insert goal
        stmt = insert(table["goal"]).values(
            organization_id=organization_id,
            goal_type=goal_type,
            title=title,
            target_value=target_value,
            start_date=start_date_dt,
            end_date=end_date_dt,
            status="in_progress",
        )

        result = session.execute(stmt)
        session.commit()
        goal_id = result.inserted_primary_key[0]

        # Initialize goal progress
        progress_stmt = insert(table["goal_progress"]).values(
            goal_id=goal_id, current_value=0, progress_percentage=0.00
        )
        session.execute(progress_stmt)
        session.commit()

        return {
            "id": goal_id,
            "organization_id": organization_id,
            "goal_type": goal_type,
            "title": title,
            "target_value": target_value,
            "start_date": format_datetime(start_date_dt),
            "end_date": format_datetime(end_date_dt),
            "status": "in_progress",
            "message": "Goal created successfully",
        }

    except HTTPException as e:
        session.rollback()
        raise e
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()


@router.get("/{organization_id}", tags=["Get Organization Goals"])
async def get_organization_goals(
    organization_id: int = Path(...),
    status: Optional[str] = Query(None),
    goal_type: Optional[str] = Query(None),
    session_token: str = Cookie(None, alias="session_token"),
):
    """Get all goals for an organization with optional filtering"""
    session = db.session

    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Verify organization exists
        org = (
            session.query(table["organization"])
            .filter_by(id=organization_id)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Build query
        query = select(table["goal"]).where(
            table["goal"].c.organization_id == organization_id
        )

        if status:
            query = query.where(table["goal"].c.status == status)
        if goal_type:
            query = query.where(table["goal"].c.goal_type == goal_type)

        goals = session.execute(query).fetchall()

        goals_list = []
        for goal in goals:
            goal_data = goal._mapping
            goals_list.append(
                {
                    "id": goal_data["id"],
                    "organization_id": goal_data["organization_id"],
                    "goal_type": goal_data["goal_type"],
                    "title": goal_data["title"],
                    "target_value": goal_data["target_value"],
                    "start_date": format_datetime(goal_data["start_date"]),
                    "end_date": format_datetime(goal_data["end_date"]),
                    "status": goal_data["status"],
                    "created_date": format_datetime(goal_data["created_date"]),
                    "last_modified_date": format_datetime(goal_data["last_modified_date"]),
                }
            )

        return {"goals": goals_list, "count": len(goals_list)}

    except HTTPException as e:
        raise e
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()


@router.get("/details/{goal_id}", tags=["Get Goal Details"])
async def get_goal_details(
    goal_id: int = Path(...),
    session_token: str = Cookie(None, alias="session_token"),
):
    """Get details of a specific goal with its progress"""
    session = db.session

    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Get goal
        goal = session.query(table["goal"]).filter_by(id=goal_id).first()
        if not goal:
            raise HTTPException(status_code=404, detail="Goal not found")

        # For automatable goal types, compute progress live from source data
        live = compute_and_sync_progress(session, goal)

        # Re-fetch goal to pick up any status change written by compute_and_sync_progress
        goal = session.query(table["goal"]).filter_by(id=goal_id).first()

        goal_dict = {
            "id": goal.id,
            "organization_id": goal.organization_id,
            "goal_type": goal.goal_type,
            "title": goal.title,
            "target_value": goal.target_value,
            "start_date": format_datetime(goal.start_date),
            "end_date": format_datetime(goal.end_date),
            "status": goal.status,
            "created_date": format_datetime(goal.created_date),
            "last_modified_date": format_datetime(goal.last_modified_date),
        }

        if live:
            goal_dict["progress"] = live
            progress_percentage = float(live.get("progress_percentage", 0.0))
        else:
            # Fall back to the last manually stored progress record
            progress = (
                session.query(table["goal_progress"])
                .filter_by(goal_id=goal_id)
                .order_by(table["goal_progress"].c.last_modified_date.desc())
                .first()
            )
            if progress:
                goal_dict["progress"] = {
                    "id": progress.id,
                    "current_value": progress.current_value,
                    "progress_percentage": float(progress.progress_percentage),
                    "updated_date": format_datetime(progress.last_modified_date),
                }
                progress_percentage = float(progress.progress_percentage)
            else:
                goal_dict["progress"] = {
                    "current_value": 0,
                    "progress_percentage": 0.0,
                }
                progress_percentage = 0.0

        recommendation = {}
        now_utc = datetime.utcnow()
        if _is_in_middle_timeframe(goal.start_date, goal.end_date, now_utc):
            code = _get_recommendation_code(goal.goal_type, progress_percentage)
            if code:
                template = RECOMMENDATION_CATALOG[code]
                recommendation = {
                    "recommendation_code": code,
                    "recommendation_type": code,
                    "title": template["title"],
                    "message": template["message"],
                    "priority": template["priority"],
                    "progress_percentage": progress_percentage,
                    "threshold_percentage": 70.0,
                }

        goal_dict["recommendation"] = recommendation

        return goal_dict

    except HTTPException as e:
        raise e
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()


@router.put("/{goal_id}", tags=["Update Goal"])
async def update_goal(
    goal_id: int = Path(...),
    title: Optional[str] = Form(None),
    target_value: Optional[int] = Form(None),
    start_date: Optional[str] = Form(None),
    end_date: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    session_token: str = Cookie(None, alias="session_token"),
):
    """Update a goal"""
    session = db.session

    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Get goal and verify ownership
        goal = session.query(table["goal"]).filter_by(id=goal_id).first()
        if not goal:
            raise HTTPException(status_code=404, detail="Goal not found")

        organization = (
            session.query(table["organization"])
            .filter_by(id=goal.organization_id)
            .first()
        )
        account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
        if not account or account.id != organization.account_id:
            raise HTTPException(status_code=403, detail="Unauthorized")

        # Parse dates if provided so update comparisons/storage are consistent
        parsed_start_date = goal.start_date
        parsed_end_date = goal.end_date
        if start_date is not None:
            try:
                parsed_start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid start_date format. Use ISO format, e.g. 2026-05-10 or 2026-05-10T00:00:00Z",
                )
        if end_date is not None:
            try:
                parsed_end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid end_date format. Use ISO format, e.g. 2026-05-10 or 2026-05-10T00:00:00Z",
                )

        # Prevent creating a duplicate date-range goal via updates (same org + type + date-only range)
        similar_goal = session.execute(
            select(table["goal"].c.id)
            .where(
                table["goal"].c.organization_id == goal.organization_id,
                table["goal"].c.goal_type == goal.goal_type,
                func.date(table["goal"].c.start_date) == parsed_start_date.date(),
                func.date(table["goal"].c.end_date) == parsed_end_date.date(),
                table["goal"].c.id != goal_id,
            )
            .limit(1)
        ).first()
        if similar_goal:
            raise HTTPException(
                status_code=400,
                detail="You've already created a similar goal.",
            )

        # Build update values
        update_values = {}
        if title is not None:
            update_values["title"] = title
        if target_value is not None:
            update_values["target_value"] = target_value
        if start_date is not None:
            update_values["start_date"] = parsed_start_date
        if end_date is not None:
            update_values["end_date"] = parsed_end_date
        if status is not None:
            valid_statuses = ["achieved", "in_progress", "behind_target"]
            if status not in valid_statuses:
                raise HTTPException(status_code=400, detail="Invalid status")
            update_values["status"] = status

        if not update_values:
            raise HTTPException(status_code=400, detail="No fields to update")

        stmt = update(table["goal"]).where(table["goal"].c.id == goal_id).values(update_values)
        session.execute(stmt)
        session.commit()

        return {"message": "Goal updated successfully", "goal_id": goal_id}

    except HTTPException as e:
        session.rollback()
        raise e
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()


@router.delete("/{goal_id}", tags=["Delete Goal"])
async def delete_goal(
    goal_id: int = Path(...),
    session_token: str = Cookie(None, alias="session_token"),
):
    """Delete a goal"""
    session = db.session

    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Get goal and verify ownership
        goal = session.query(table["goal"]).filter_by(id=goal_id).first()
        if not goal:
            raise HTTPException(status_code=404, detail="Goal not found")

        organization = (
            session.query(table["organization"])
            .filter_by(id=goal.organization_id)
            .first()
        )
        account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
        if not account or account.id != organization.account_id:
            raise HTTPException(status_code=403, detail="Unauthorized")

        # Delete goal (cascade will handle goal_progress)
        stmt = delete(table["goal"]).where(table["goal"].c.id == goal_id)
        session.execute(stmt)
        session.commit()

        return {"message": "Goal deleted successfully", "goal_id": goal_id}

    except HTTPException as e:
        session.rollback()
        raise e
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()


@router.put("/{goal_id}/progress", tags=["Update Goal Progress"])
async def update_goal_progress(
    goal_id: int = Path(...),
    current_value: int = Form(...),
    session_token: str = Cookie(None, alias="session_token"),
):
    """Update progress for a goal"""
    session = db.session

    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Get goal and verify ownership
        goal = session.query(table["goal"]).filter_by(id=goal_id).first()
        if not goal:
            raise HTTPException(status_code=404, detail="Goal not found")

        organization = (
            session.query(table["organization"])
            .filter_by(id=goal.organization_id)
            .first()
        )
        account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
        if not account or account.id != organization.account_id:
            raise HTTPException(status_code=403, detail="Unauthorized")

        # Calculate progress percentage
        progress_percentage = min(
            (current_value / goal.target_value * 100) if goal.target_value > 0 else 0,
            100,
        )

        # Update goal progress
        progress = (
            session.query(table["goal_progress"]).filter_by(goal_id=goal_id).first()
        )
        if progress:
            stmt = (
                update(table["goal_progress"])
                .where(table["goal_progress"].c.goal_id == goal_id)
                .values(
                    current_value=current_value,
                    progress_percentage=progress_percentage,
                    last_modified_date=datetime.utcnow(),
                )
            )
            session.execute(stmt)
        else:
            stmt = insert(table["goal_progress"]).values(
                goal_id=goal_id,
                current_value=current_value,
                progress_percentage=progress_percentage,
            )
            session.execute(stmt)

        # Update goal status based on progress
        if progress_percentage >= 100:
            new_status = "achieved"
        else:
            new_status = "in_progress"

        stmt = (
            update(table["goal"]).where(table["goal"].c.id == goal_id).values(status=new_status)
        )
        session.execute(stmt)
        session.commit()

        return {
            "goal_id": goal_id,
            "current_value": current_value,
            "progress_percentage": progress_percentage,
            "status": new_status,
            "message": "Goal progress updated successfully",
        }

    except HTTPException as e:
        session.rollback()
        raise e
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()


@router.get("/{organization_id}/progress", tags=["Get All Goal Progress"])
async def get_all_goal_progress(
    organization_id: int = Path(...),
    session_token: str = Cookie(None, alias="session_token"),
):
    """Get progress for all goals in an organization"""
    session = db.session

    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Verify organization exists
        org = (
            session.query(table["organization"])
            .filter_by(id=organization_id)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Get all goals for organization with their progress
        goals = session.query(table["goal"]).filter_by(organization_id=organization_id).all()

        progress_list = []
        for goal in goals:
            # For automatable goal types, compute progress live from source data
            live = compute_and_sync_progress(session, goal)

            # Re-fetch to pick up any status change
            goal = session.query(table["goal"]).filter_by(id=goal.id).first()

            progress_data = {
                "goal_id": goal.id,
                "goal_type": goal.goal_type,
                "title": goal.title,
                "target_value": goal.target_value,
                "status": goal.status,
            }

            if live:
                progress_data.update(live)
            else:
                progress = (
                    session.query(table["goal_progress"])
                    .filter_by(goal_id=goal.id)
                    .order_by(table["goal_progress"].c.last_modified_date.desc())
                    .first()
                )
                if progress:
                    progress_data["current_value"] = progress.current_value
                    progress_data["progress_percentage"] = float(
                        progress.progress_percentage
                    )
                    progress_data["updated_date"] = format_datetime(progress.last_modified_date)
                else:
                    progress_data["current_value"] = 0
                    progress_data["progress_percentage"] = 0.0

            progress_list.append(progress_data)

        # Ensure all date fields in progress_list are formatted
        for item in progress_list:
            if "updated_date" in item:
                item["updated_date"] = format_datetime(item["updated_date"])
        return {"goals_progress": progress_list, "count": len(progress_list)}

    except HTTPException as e:
        raise e
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()

