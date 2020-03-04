import celery_config
from celery import Celery

from celery import signature, chain


celery_app = Celery("tasks")
celery_app.config_from_object(celery_config)


class TaskService(object):
    def __init__(self, queue='new_tasks'):
        self.queue = queue

    def _create_signature(self, name, args=None, kwargs=None):
        """
        Create Celery signature
        """
        return signature(name, args=args, kwargs=kwargs, queue=self.queue, app=celery_app)

    def status_set_pending(self, repoid, commitid, branch, on_a_pull_request):
        self._create_signature(
            'app.tasks.status.SetPending',
            kwargs=dict(
                repoid=repoid,
                commitid=commitid,
                branch=branch,
                on_a_pull_request=on_a_pull_request
            )
        ).apply_async()

    def notify(self, repoid, commitid):
        self._create_signature(
            'app.tasks.notify.Notify',
            kwargs=dict(repoid=repoid, commitid=commitid)
        ).apply_async()

    def refresh(self, ownerid, username, sync_teams=True, sync_repos=True, using_integration=False):
        """
        !!!
        Copied from https://github.com/codecov/codecov.io/blob/master/app/services/task.py
        !!!

        Send sync_teams and/or sync_repos task message

        If running both tasks on new worker, we create a chain with sync_teams to run
        first so that when sync_repos starts it has the most up to date teams/groups
        data for the user. Otherwise, we may miss some repos.
        """
        chain_to_call = []
        if sync_teams:
            chain_to_call.append(self._create_signature(
                'app.tasks.sync_teams.SyncTeams',
                kwargs=dict(
                    ownerid=ownerid,
                    username=username,
                    using_integration=using_integration
                )
            ))

        if sync_repos:
            chain_to_call.append(self._create_signature(
                'app.tasks.sync_repos.SyncRepos',
                kwargs=dict(
                    ownerid=ownerid,
                    username=username,
                    using_integration=using_integration
                )
            ))

        return chain(*chain_to_call).apply_async()