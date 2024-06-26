import json
import logging
import re
from typing import List
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.utils import timezone
from jwt import PyJWTError
from rest_framework import authentication, exceptions
from rest_framework.exceptions import NotAuthenticated
from rest_framework.views import exception_handler

from codecov_auth.authentication.types import RepositoryAsUser, RepositoryAuthInterface
from codecov_auth.models import (
    OrganizationLevelToken,
    RepositoryToken,
    Service,
    TokenTypeChoices,
)
from core.models import Commit, Repository
from services.repo_providers import RepoProviderService
from upload.helpers import get_global_tokens, get_repo_with_github_actions_oidc_token
from upload.views.helpers import get_repository_from_string
from utils import is_uuid

log = logging.getLogger(__name__)


def repo_auth_custom_exception_handler(exc, context):
    """
    User arrives here if they have correctly supplied a Token or the Tokenless Headers,
    but their Token has not matched with any of our Authentication methods. The goal is to
    give the user something better than "Invalid Token" or "Authentication credentials were not provided."
    """
    response = exception_handler(exc, context)
    if response is not None:
        try:
            exc_code = response.data["detail"].code
        except TypeError:
            return response
        if exc_code == NotAuthenticated.default_code:
            response.data["detail"] = (
                "Failed token authentication, please double-check that your repository token matches in the Codecov UI, "
                "or review the docs https://docs.codecov.com/docs/adding-the-codecov-token"
            )
    return response


class LegacyTokenRepositoryAuth(RepositoryAuthInterface):
    def __init__(self, repository, auth_data):
        self._auth_data = auth_data
        self._repository = repository

    def get_scopes(self):
        return [TokenTypeChoices.UPLOAD]

    def get_repositories(self):
        return [self._repository]

    def allows_repo(self, repository):
        return repository in self.get_repositories()


class OIDCTokenRepositoryAuth(LegacyTokenRepositoryAuth):
    pass


class TableTokenRepositoryAuth(RepositoryAuthInterface):
    def __init__(self, repository, token):
        self._token = token
        self._repository = repository

    def get_scopes(self):
        return [self._token.token_type]

    def get_repositories(self):
        return [self._repository]

    def allows_repo(self, repository):
        return repository in self.get_repositories()


class OrgLevelTokenRepositoryAuth(RepositoryAuthInterface):
    def __init__(self, token: OrganizationLevelToken) -> None:
        self._token = token
        self._org = token.owner

    def get_scopes(self):
        return [self._token.token_type]

    def allows_repo(self, repository):
        return repository.author.ownerid == self._org.ownerid

    def get_repositories_queryset(self) -> QuerySet:
        """Returns the QuerySet that generates get_repositories list.
        Because QuerySets are lazy you can add further filters on top of it improving performance.
        """
        return Repository.objects.filter(author=self._org)

    def get_repositories(self) -> List[Repository]:
        # This might be an expensive function depending on the owner in question (thousands of repos)
        # Consider using get_repositories_queryset if possible and adding more filters to it
        return list(Repository.objects.filter(author=self._org).all())


class TokenlessAuth(RepositoryAuthInterface):
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def get_scopes(self):
        return [TokenTypeChoices.UPLOAD]

    def allows_repo(self, repository):
        return repository in self.get_repositories()

    def get_repositories(self) -> List[Repository]:
        return [self._repository]


class RepositoryLegacyQueryTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        token = request.GET.get("token")
        if not token:
            return None
        try:
            token = UUID(token)
        except ValueError:
            return None
        try:
            repository = Repository.objects.get(upload_token=token)
        except Repository.DoesNotExist:
            return None
        return (
            RepositoryAsUser(repository),
            LegacyTokenRepositoryAuth(repository, {"token": token}),
        )


class RepositoryLegacyTokenAuthentication(authentication.TokenAuthentication):
    def authenticate_credentials(self, token):
        try:
            token = UUID(token)
            repository = Repository.objects.get(upload_token=token)
        except (ValueError, TypeError, Repository.DoesNotExist):
            return None  # continue to next auth class
        return (
            RepositoryAsUser(repository),
            LegacyTokenRepositoryAuth(repository, {"token": token}),
        )


class RepositoryTokenAuthentication(authentication.TokenAuthentication):
    keyword = "Repotoken"

    def authenticate_credentials(self, key):
        try:
            token = RepositoryToken.objects.select_related("repository").get(key=key)
        except RepositoryToken.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid token.")

        if not token.repository.active:
            raise exceptions.AuthenticationFailed("User inactive or deleted.")
        if token.valid_until is not None and token.valid_until <= timezone.now():
            raise exceptions.AuthenticationFailed("Invalid token.")
        return (
            RepositoryAsUser(token.repository),
            TableTokenRepositoryAuth(token.repository, token),
        )


class GlobalTokenAuthentication(authentication.TokenAuthentication):
    def authenticate(self, request):
        global_tokens = get_global_tokens()
        token = self.get_token(request)
        repoid = self.get_repoid(request)
        owner = self.get_owner(request)
        using_global_token = True if token in global_tokens else False
        service = global_tokens[token] if using_global_token else None

        if using_global_token:
            try:
                repository = Repository.objects.get(
                    author__service=service,
                    repoid=repoid,
                    author__username=owner.username,
                )
            except ObjectDoesNotExist:
                raise exceptions.AuthenticationFailed(
                    "Could not find a repository, try using repo upload token"
                )
        else:
            return None  # continue to next auth class
        return (
            RepositoryAsUser(repository),
            LegacyTokenRepositoryAuth(repository, {"token": token}),
        )

    def get_token(self, request):
        # TODO
        pass

    def get_repoid(self, request):
        # TODO
        pass

    def get_owner(self, request):
        # TODO
        pass


class OrgLevelTokenAuthentication(authentication.TokenAuthentication):
    def authenticate_credentials(self, key):
        if is_uuid(key):  # else, continue to next auth class
            # Actual verification for org level tokens
            token = OrganizationLevelToken.objects.filter(token=key).first()

            if token is None:
                return None
            if token.valid_until and token.valid_until <= timezone.now():
                raise exceptions.AuthenticationFailed("Token is expired.")

            return (
                token.owner,
                OrgLevelTokenRepositoryAuth(token),
            )


class GitHubOIDCTokenAuthentication(authentication.TokenAuthentication):
    def authenticate_credentials(self, token):
        if not token or is_uuid(token):
            return None  # continue to next auth class

        try:
            repository = get_repo_with_github_actions_oidc_token(token)
        except (ObjectDoesNotExist, PyJWTError) as e:
            return None  # continue to next auth class

        log.info(
            "GitHubOIDCTokenAuthentication Success",
            extra=dict(repository=str(repository)),  # Repo<author/name>
        )

        return (
            RepositoryAsUser(repository),
            OIDCTokenRepositoryAuth(repository, {"token": token}),
        )


class TokenlessAuthentication(authentication.TokenAuthentication):
    # TODO: replace this with the message from repo_auth_custom_exception_handler
    auth_failed_message = "Not valid tokenless upload"

    def _get_info_from_request_path(
        self, request
    ) -> tuple[Repository, str | None] | None:
        path_info = request.get_full_path_info()
        # The repo part comes from https://stackoverflow.com/a/22312124
        upload_views_prefix_regex = (
            r"\/upload\/(\w+)\/([\w\.@:_/\-~]+)\/commits(?:\/([a-f0-9]{40}))?"
        )
        match = re.search(upload_views_prefix_regex, path_info)

        if match is None:
            raise exceptions.AuthenticationFailed(self.auth_failed_message)

        service = match.group(1)
        encoded_slug = match.group(2)
        commitid = match.group(3)

        # Validate provider
        try:
            service_enum = Service(service)
        except ValueError:
            raise exceptions.AuthenticationFailed(self.auth_failed_message)

        # Validate that next group exists and decode slug
        repo = get_repository_from_string(service_enum, encoded_slug)
        if repo is None:
            # Purposefully using the generic message so that we don't tell that
            # we don't have a certain repo
            raise exceptions.AuthenticationFailed(self.auth_failed_message)

        return repo, commitid

    def get_branch(self, request, commitid=None):
        if commitid:
            commit = Commit.objects.filter(commitid=commitid).first()
            if not commit:
                raise exceptions.AuthenticationFailed(self.auth_failed_message)
            return commit.branch
        else:
            try:
                body = json.loads(str(request.body, "utf8"))
            except json.JSONDecodeError:
                return None
            else:
                return body.get("branch")

    def authenticate(self, request):
        repository, commitid = self._get_info_from_request_path(request)

        if repository is None or repository.private:
            raise exceptions.AuthenticationFailed(self.auth_failed_message)

        branch = self.get_branch(request, commitid)

        if (branch and ":" in branch) or request.method == "GET":
            return (
                RepositoryAsUser(repository),
                TokenlessAuth(repository),
            )
        else:
            raise exceptions.AuthenticationFailed(self.auth_failed_message)
