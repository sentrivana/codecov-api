import logging
import re
from datetime import datetime
from enum import Enum

from django.conf import settings
from shared.analytics_tracking import analytics_manager

log = logging.getLogger(__name__)


def inject_analytics_owner(method):
    """
    Decorator: promotes type of 'owner' arg to 'AnalyticsOwner'.
    """

    def exec_method(self, owner, **kwargs):
        analytics_owner = AnalyticsOwner(owner, cookies=kwargs.get("cookies", {}))
        return method(self, analytics_owner, **kwargs)

    return exec_method


def inject_analytics_repository(method):
    """
    Decorator: promotes type of second parameter (a repository) to AnalyticsRepository
    """

    def exec_method(self, ownerid, repository):
        analytics_repository = AnalyticsRepository(repository)
        return method(self, ownerid, analytics_repository)

    return exec_method


class AnalyticsEvent(Enum):
    ACCOUNT_ACTIVATED_REPOSITORY_ON_UPLOAD = "Account Activated Repository On Upload"
    ACCOUNT_ACTIVATED_REPOSITORY = "Account Activated Repository"
    ACCOUNT_UPLOADED_COVERAGE_REPORT = "Account Uploaded Coverage Report"
    USER_SIGNED_IN = "User Signed In"
    USER_SIGNED_UP = "User Signed Up"


class AnalyticsOwner:
    """
    An object wrapper around 'Owner' that provides "user_id", "traits",
    and "context" properties.
    """

    def __init__(self, owner, cookies={}, owner_collection_type="users"):
        self.owner = owner
        self.cookies = cookies
        self.owner_collection_type = owner_collection_type

    @property
    def user_id(self):
        return self.owner.ownerid

    @property
    def traits(self):
        return {
            "avatar": self.owner.avatar_url,
            "service": self.owner.service,
            "service_id": self.owner.service_id,
            "plan": self.owner.plan,
            "staff": self.owner.staff,
            "has_yaml": self.owner.yaml is not None,
            # Default values set to make the data readable by Salesforce
            "email": self.owner.email or "unknown@codecov.io",
            "name": self.owner.name or "unknown",
            "username": self.owner.username or "unknown",
            "student": self.owner.student or False,
            "bot": self.owner.bot or False,
            "delinquent": self.owner.delinquent or False,
            "trial_start_date": self.owner.trial_start_date or None,
            "trial_end_date": self.owner.trial_end_date or None,
            "private_access": self.owner.private_access or False,
            "plan_provider": self.owner.plan_provider or "",
            "plan_user_count": self.owner.plan_user_count or 5,
            # Set ms to 0 on dates to match date format required by Salesforce
            "createdAt": self.owner.createstamp.replace(microsecond=0)
            if self.owner.createstamp
            else datetime(2014, 1, 1, 12, 0, 0),
            "updatedAt": self.owner.updatestamp.replace(microsecond=0, tzinfo=None)
            if self.owner.updatestamp
            else datetime(2014, 1, 1, 12, 0, 0),
            "student_created_at": self.owner.student_created_at.replace(microsecond=0)
            if self.owner.student_created_at
            else datetime(2014, 1, 1, 12, 0, 0),
            "student_updated_at": self.owner.student_updated_at.replace(microsecond=0)
            if self.owner.student_updated_at
            else datetime(2014, 1, 1, 12, 0, 0),
        }

    @property
    def context(self):
        """
        Mostly copied from
        https://github.com/codecov/codecov.io/blob/master/app/services/analytics_tracking.py#L107
        """
        context = {"externalIds": []}

        context["externalIds"].append(
            {
                "id": self.owner.service_id,
                "type": f"{self.owner.service}_id",
                "collection": self.owner_collection_type,
                "encoding": "none",
            }
        )

        if self.owner.stripe_customer_id:
            context["externalIds"].append(
                {
                    "id": self.owner.stripe_customer_id,
                    "type": "stripe_customer_id",
                    "collection": self.owner_collection_type,
                    "encoding": "none",
                }
            )

        if self.cookies and self.owner_collection_type == "users":
            marketo_cookie = self.cookies.get("_mkto_trk")
            ga_cookie = self.cookies.get("_ga")
            if marketo_cookie:
                context["externalIds"].append(
                    {
                        "id": marketo_cookie,
                        "type": "marketo_cookie",
                        "collection": "users",
                        "encoding": "none",
                    }
                )
                context["Marketo"] = {"marketo_cookie": marketo_cookie}
            if ga_cookie:
                # id is everything after the "GA.1." prefix
                match = re.match("^.+\.(.+?\..+?)$", ga_cookie)
                if match:
                    ga_client_id = match.group(1)
                    context["externalIds"].append(
                        {
                            "id": ga_client_id,
                            "type": "ga_client_id",
                            "collection": "users",
                            "encoding": "none",
                        }
                    )

        return context


class AnalyticsRepository:
    """
    Wrapper object around Repository to provide a similar "traits" field as in AnalyticsOwner above.
    """

    def __init__(self, repo):
        self.repo = repo

    @property
    def traits(self):
        return {
            "repoid": self.repo.repoid,
            "ownerid": self.repo.author.ownerid,
            "service_id": self.repo.service_id,
            "name": self.repo.name,
            "private": self.repo.private,
            "branch": self.repo.branch,
            "updatestamp": self.repo.updatestamp,
            "language": self.repo.language,
            "active": self.repo.active,
            "deleted": self.repo.deleted,
            "activated": self.repo.activated,
            "bot": self.repo.bot,
            "using_integration": self.repo.using_integration,
            "hookid": self.repo.hookid,
            "has_yaml": self.repo.yaml is not None,
        }


class AnalyticsService:
    """
    Various methods for emitting events related to user actions.
    """

    @inject_analytics_owner
    def user_signed_up(self, analytics_owner, **kwargs):
        event_properties = {
            **analytics_owner.traits,
            "signup_department": kwargs.get("utm_department") or "marketing",
            "signup_campaign": kwargs.get("utm_campaign") or "",
            "signup_medium": kwargs.get("utm_medium") or "",
            "signup_source": kwargs.get("utm_source") or "direct",
            "signup_content": kwargs.get("utm_content") or "",
            "signup_term": kwargs.get("utm_term") or "",
        }
        analytics_manager.track_event(
            AnalyticsEvent.USER_SIGNED_UP.value,
            is_enterprise=settings.IS_ENTERPRISE,
            event_data=event_properties,
        )

    @inject_analytics_owner
    def user_signed_in(self, analytics_owner, **kwargs):
        event_properties = {
            **analytics_owner.traits,
            "signup_department": kwargs.get("utm_department") or "marketing",
            "signup_campaign": kwargs.get("utm_campaign") or "",
            "signup_medium": kwargs.get("utm_medium") or "",
            "signup_source": kwargs.get("utm_source") or "direct",
            "signup_content": kwargs.get("utm_content") or "",
            "signup_term": kwargs.get("utm_term") or "",
        }
        analytics_manager.track_event(
            AnalyticsEvent.USER_SIGNED_IN.value,
            is_enterprise=settings.IS_ENTERPRISE,
            event_data=event_properties,
        )

    @inject_analytics_repository
    def account_activated_repository(self, current_user_ownerid, analytics_repository):
        event_data = {
            **analytics_repository.traits,
            "user_id": current_user_ownerid,
        }
        analytics_manager.track_event(
            AnalyticsEvent.ACCOUNT_ACTIVATED_REPOSITORY.value,
            is_enterprise=settings.IS_ENTERPRISE,
            event_data=event_data,
            context={"groupId": analytics_repository.repo.author.ownerid},
        )

    @inject_analytics_repository
    def account_activated_repository_on_upload(self, org_ownerid, analytics_repository):
        analytics_manager.track_event(
            AnalyticsEvent.ACCOUNT_ACTIVATED_REPOSITORY_ON_UPLOAD.value,
            is_enterprise=settings.IS_ENTERPRISE,
            event_data=analytics_repository.traits,
            context={"groupId": org_ownerid},
        )

    def account_uploaded_coverage_report(self, org_ownerid, upload_details):
        analytics_manager.track_event(
            AnalyticsEvent.ACCOUNT_UPLOADED_COVERAGE_REPORT.value,
            is_enterprise=settings.IS_ENTERPRISE,
            event_data=upload_details,
            context={"groupId": org_ownerid},
        )