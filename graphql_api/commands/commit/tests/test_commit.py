from django.test import TransactionTestCase
from unittest.mock import patch

from codecov_auth.tests.factories import OwnerFactory
from core.tests.factories import RepositoryFactory, CommitFactory
from ..commit import CommitCommands


class CommitCommandsTest(TransactionTestCase):
    def setUp(self):
        self.user = OwnerFactory(username="codecov-user")
        self.repository = RepositoryFactory()
        self.commit = CommitFactory()
        self.command = CommitCommands(self.user, "github")

    @patch("graphql_api.commands.commit.commit.FetchCommitInteractor.execute")
    def test_fetch_commit_delegate_to_interactor(self, interactor_mock):
        commit_id = "123"
        self.command.fetch_commit(self.repository, commit_id)
        interactor_mock.assert_called_once_with(self.repository, commit_id)

    @patch("graphql_api.commands.commit.commit.GetFinalYamlInteractor.execute")
    def test_get_final_yaml_delegate_to_interactor(self, interactor_mock):
        self.command.get_final_yaml(self.commit)
        interactor_mock.assert_called_once_with(self.commit)