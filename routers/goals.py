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
                updated_date=updated_at,
            )
        )
    else:
        session.execute(
            insert(table["goal_progress"]).values(
                goal_id=goal.id,
                current_value=current_value,
                progress_percentage=progress_percentage,
                updated_date=updated_at,
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
    description: Optional[str] = Form(None),
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

        # Insert goal
        stmt = insert(table["goal"]).values(
            organization_id=organization_id,
            goal_type=goal_type,
            title=title,
            description=description,
            target_value=target_value,
            start_date=start_date,
            end_date=end_date,
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
            "description": description,
            "start_date": start_date,
            "end_date": end_date,
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
                    "description": goal_data["description"],
                    "target_value": goal_data["target_value"],
                    "start_date": format_datetime(goal_data["start_date"]),
                    "end_date": format_datetime(goal_data["end_date"]),
                    "status": goal_data["status"],
                    "created_date": format_datetime(goal_data["created_date"]),
                    "last_modified_date": format_datetime(
                        goal_data["last_modified_date"]
                    ),
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
        session.expire(goal)
        goal = session.query(table["goal"]).filter_by(id=goal_id).first()

        goal_dict = {
            "id": goal.id,
            "organization_id": goal.organization_id,
            "goal_type": goal.goal_type,
            "title": goal.title,
            "description": goal.description,
            "target_value": goal.target_value,
            "start_date": format_datetime(goal.start_date),
            "end_date": format_datetime(goal.end_date),
            "status": goal.status,
            "created_date": format_datetime(goal.created_date),
            "last_modified_date": format_datetime(goal.last_modified_date),
        }

        if live:
            goal_dict["progress"] = live
        else:
            # Fall back to the last manually stored progress record
            progress = (
                session.query(table["goal_progress"])
                .filter_by(goal_id=goal_id)
                .order_by(table["goal_progress"].c.updated_date.desc())
                .first()
            )
            if progress:
                goal_dict["progress"] = {
                    "id": progress.id,
                    "current_value": progress.current_value,
                    "progress_percentage": float(progress.progress_percentage),
                    "updated_date": format_datetime(progress.updated_date),
                }
            else:
                goal_dict["progress"] = {
                    "current_value": 0,
                    "progress_percentage": 0.0,
                }

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
    description: Optional[str] = Form(None),
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

        # Build update values
        update_values = {}
        if title is not None:
            update_values["title"] = title
        if description is not None:
            update_values["description"] = description
        if target_value is not None:
            update_values["target_value"] = target_value
        if start_date is not None:
            update_values["start_date"] = start_date
        if end_date is not None:
            update_values["end_date"] = end_date
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
                    updated_date=datetime.utcnow(),
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
            session.expire(goal)
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
                    .order_by(table["goal_progress"].c.updated_date.desc())
                    .first()
                )
                if progress:
                    progress_data["current_value"] = progress.current_value
                    progress_data["progress_percentage"] = float(
                        progress.progress_percentage
                    )
                    progress_data["updated_date"] = format_datetime(progress.updated_date)
                else:
                    progress_data["current_value"] = 0
                    progress_data["progress_percentage"] = 0.0

            progress_list.append(progress_data)

        return {"goals_progress": progress_list, "count": len(progress_list)}

    except HTTPException as e:
        raise e
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()


@router.post("/{organization_id}/recommendations", tags=["Create Recommendation"])
async def create_recommendation(
    organization_id: int = Path(...),
    recommendation_type: str = Form(...),
    title: str = Form(...),
    message: str = Form(...),
    priority: str = Form("medium"),
    session_token: str = Cookie(None, alias="session_token"),
):
    """Create a recommendation for an organization"""
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

        # Validate recommendation_type
        valid_types = [
            "low_engagement",
            "low_participation",
            "membership_decline",
            "low_event_attendance",
            "announcement_decline",
        ]
        if recommendation_type not in valid_types:
            raise HTTPException(status_code=400, detail="Invalid recommendation_type")

        # Validate priority
        valid_priorities = ["low", "medium", "high"]
        if priority not in valid_priorities:
            raise HTTPException(status_code=400, detail="Invalid priority")

        # Insert recommendation
        stmt = insert(table["recommendation"]).values(
            organization_id=organization_id,
            recommendation_type=recommendation_type,
            title=title,
            message=message,
            priority=priority,
            dismissed=False,
        )

        result = session.execute(stmt)
        session.commit()
        recommendation_id = result.inserted_primary_key[0]

        return {
            "id": recommendation_id,
            "organization_id": organization_id,
            "recommendation_type": recommendation_type,
            "title": title,
            "message": message,
            "priority": priority,
            "dismissed": False,
            "message": "Recommendation created successfully",
        }

    except HTTPException as e:
        session.rollback()
        raise e
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()


@router.get("/{organization_id}/recommendations", tags=["Get Recommendations"])
async def get_recommendations(
    organization_id: int = Path(...),
    dismissed: Optional[bool] = Query(None),
    priority: Optional[str] = Query(None),
    session_token: str = Cookie(None, alias="session_token"),
):
    """Get recommendations for an organization"""
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
        query = select(table["recommendation"]).where(
            table["recommendation"].c.organization_id == organization_id
        )

        if dismissed is not None:
            query = query.where(table["recommendation"].c.dismissed == dismissed)
        if priority:
            query = query.where(table["recommendation"].c.priority == priority)

        recommendations = session.execute(query).fetchall()

        recommendations_list = []
        for rec in recommendations:
            rec_data = rec._mapping
            recommendations_list.append(
                {
                    "id": rec_data["id"],
                    "organization_id": rec_data["organization_id"],
                    "recommendation_type": rec_data["recommendation_type"],
                    "title": rec_data["title"],
                    "message": rec_data["message"],
                    "priority": rec_data["priority"],
                    "dismissed": rec_data["dismissed"],
                    "created_date": format_datetime(rec_data["created_date"]),
                    "dismissed_date": format_datetime(rec_data["dismissed_date"]),
                }
            )

        return {
            "recommendations": recommendations_list,
            "count": len(recommendations_list),
        }

    except HTTPException as e:
        raise e
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()


@router.put("/recommendations/{recommendation_id}/dismiss", tags=["Dismiss Recommendation"])
async def dismiss_recommendation(
    recommendation_id: int = Path(...),
    session_token: str = Cookie(None, alias="session_token"),
):
    """Dismiss a recommendation"""
    session = db.session

    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Get recommendation and verify ownership
        rec = (
            session.query(table["recommendation"]).filter_by(id=recommendation_id).first()
        )
        if not rec:
            raise HTTPException(status_code=404, detail="Recommendation not found")

        organization = (
            session.query(table["organization"])
            .filter_by(id=rec.organization_id)
            .first()
        )
        account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
        if not account or account.id != organization.account_id:
            raise HTTPException(status_code=403, detail="Unauthorized")

        # Update recommendation
        stmt = (
            update(table["recommendation"])
            .where(table["recommendation"].c.id == recommendation_id)
            .values(dismissed=True, dismissed_date=datetime.utcnow())
        )
        session.execute(stmt)
        session.commit()

        return {
            "message": "Recommendation dismissed successfully",
            "recommendation_id": recommendation_id,
        }

    except HTTPException as e:
        session.rollback()
        raise e
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()
