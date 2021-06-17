import random
import uuid

import factory

from reports import models
from hashlib import sha1
from factory.django import DjangoModelFactory
from codecov_auth.tests.factories import OwnerFactory
from core.tests.factories import CommitFactory


class CommitReportFactory(DjangoModelFactory):
    class Meta:
        model = models.CommitReport

    commit = factory.SubFactory(CommitFactory)


class ReportSessionFactory(DjangoModelFactory):
    class Meta:
        model = models.ReportSession

    build_code = factory.Sequence(lambda n: f"{n}")
    report = factory.SubFactory(CommitReportFactory)
